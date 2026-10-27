"""Радар БПЛА/ракет: читает канал-источник, обновляет карту и шлёт её в Telegram.

Запуск:
    python bot.py            # постоянный цикл опроса
    python bot.py --once     # один проход (для планировщика)
    python bot.py --send     # отрисовать текущее состояние и отправить
    python bot.py --check    # проверить токен и чат
"""
from __future__ import annotations

import re
import sys
import time
import traceback
from datetime import datetime

import config
from fetch_tg import fetch_page, fetch_posts, parse_posts
from maprender import MapRenderer
from parse import lexicon_status, parse_losses, parse_post
from regions import RegionIndex
from report import build_losses_message
from state import MSK, ThreatState
from tg_api import TelegramError, get_me, send_document, send_message, send_photo

INITIAL_PAGES = 2
LOG_PATH = config.LOG_PATH
_LOCK = None


def log(msg: str) -> None:
    # в логах и исключениях не должно быть токена бота
    msg = re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot<id>:<token>", str(msg))
    line = f"[{datetime.now(MSK):%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 2_000_000:
            LOG_PATH.replace(LOG_PATH.with_suffix(".old.log"))
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def single_instance() -> bool:
    """Не даём запустить второй экземпляр: иначе в канал уйдут дубли карт."""
    global _LOCK
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 47653))
        s.listen(1)
        _LOCK = s
        return True
    except OSError:
        return False


def build_caption(state: ThreatState) -> str:
    res = state.summary()
    lines = ["<b>Карта воздушных угроз</b>"]
    if res["rocket"]:
        lines.append("🔴 Ракетная опасность: " + ", ".join(short(r) for r in res["rocket"]))
    if res["bpla"]:
        lines.append("🟠 Опасность БПЛА: " + ", ".join(short(r) for r in res["bpla"]))
    if not res["rocket"] and not res["bpla"]:
        lines.append("🟢 Активных угроз нет")
    lines.append(f"<i>{datetime.now(MSK):%d.%m.%Y %H:%M} МСК</i>")
    return "\n".join(lines)


def short(name: str) -> str:
    from regions import short_label
    return short_label(name)


class Radar:
    def __init__(self) -> None:
        self.index = RegionIndex()
        self.state = ThreatState(config.STATE_PATH, ttl_minutes=config.TTL_MINUTES)
        self.renderer = MapRenderer(self.index)

    # ---------- источник ----------
    def bootstrap(self) -> None:
        """Первый запуск: восстанавливаем картину по последним постам."""
        posts = fetch_posts(config.SOURCE_CHANNEL, pages=INITIAL_PAGES)
        if not posts:
            log("канал не отдал постов")
            return
        applied = 0
        for p in posts:
            parsed = parse_post(p["text"], self.index)
            if parsed.kind != "ignore" and self.state.apply(parsed):
                applied += 1
        self.state.last_post_id = posts[-1]["id"]
        self.state.save()
        log(f"старт: {len(posts)} постов просмотрено, изменений {applied}, "
            f"активных регионов {len(self.state.regions)}")

    def poll_once(self) -> tuple[bool, list[str]]:
        """Возвращает (изменилось ли, список сообщений для лога)."""
        page = fetch_page(config.SOURCE_CHANNEL)
        posts = [p for p in parse_posts(page) if p["id"] > self.state.last_post_id]
        changed = False
        notes = []
        for p in posts:
            parsed = parse_post(p["text"], self.index)
            if parsed.kind == "ignore":
                notes.append(f"{p['id']} пропуск: {parsed.reason}")
                losses = parse_losses(p["text"], self.index)
                sig = f"{p['date']}|{losses.signature}" if losses else ""
                if losses and sig != self.state.last_summary:
                    self.state.pending_summary.append({
                        "text": build_losses_message(losses, p["date"]),
                        "signature": sig,
                    })
                    notes.append(f"{p['id']} сводка о сбитых: {losses.total} БПЛА, "
                                 f"регионов {len(losses.regions)} — в очередь")
            else:
                did = self.state.apply(parsed)
                changed = changed or did
                notes.append(f"{p['id']} {parsed.kind} {','.join(parsed.types)} "
                             f"{', '.join(short(r) for r in parsed.regions)[:70]}")
            self.state.last_post_id = max(self.state.last_post_id, p["id"])
        if posts:
            self.state.save()
        if self.state.expire():
            changed = True
            notes.append("истёк TTL у части регионов")
            self.state.save()
        if self.flush_summaries():
            notes.append("сводка о сбитых отправлена в канал")
        return changed, notes

    def flush_summaries(self) -> bool:
        """Отправляет очередь сводок о сбитых. Неудача — пробуем на следующем опросе."""
        sent = False
        while self.state.pending_summary:
            item = self.state.pending_summary[0]
            if not config.BOT_TOKEN or not config.CHAT_ID:
                log("сводка готова, но BOT_TOKEN/CHAT_ID не заданы")
                return sent
            try:
                send_message(config.BOT_TOKEN, config.CHAT_ID, item["text"])
            except TelegramError as exc:
                log(f"сводка не отправлена: {exc}")
                return sent
            self.state.last_summary = item.get("signature", "")
            self.state.pending_summary.pop(0)
            self.state.save()
            log(f"сводка о сбитых отправлена в {config.CHAT_ID}")
            sent = True
        return sent

    # ---------- карта ----------
    def render(self, path=None):
        from pathlib import Path
        out = Path(path or config.OUT_PATH)
        self.renderer.render(self.state, out)
        return out

    def publish(self, path) -> None:
        if not config.BOT_TOKEN or not config.CHAT_ID:
            log("BOT_TOKEN/CHAT_ID не заданы — карта сохранена локально")
            return
        caption = build_caption(self.state)
        sender = send_document if config.SEND_AS_DOCUMENT else send_photo
        sender(config.BOT_TOKEN, config.CHAT_ID, path, caption)
        log(f"карта отправлена в {config.CHAT_ID}")


def main() -> None:
    argv = set(sys.argv[1:])
    if "--check" in argv:
        if not config.BOT_TOKEN:
            print("BOT_TOKEN не задан в .env")
            return
        me = get_me(config.BOT_TOKEN)
        print("бот:", me.get("username"), "| чат:", config.CHAT_ID or "не задан")
        return

    radar = Radar()
    log(f"база формулировок: {lexicon_status()}")
    if "--send" in argv:
        p = radar.render()
        radar.publish(p)
        log(f"отправлено: {p}")
        return

    if "--once" in argv:
        radar.bootstrap() if not radar.state.last_post_id else None
        changed, notes = radar.poll_once()
        for n in notes:
            log(n)
        if changed:
            radar.publish(radar.render())
        log(f"состояние: {len(radar.state.regions)} регионов под угрозой")
        return

    # постоянный цикл
    if not single_instance():
        log("бот уже запущен — второй экземпляр не нужен")
        return
    had_state = bool(radar.state.last_post_id)
    if had_state:
        log(f"продолжаю с поста {radar.state.last_post_id}")
    else:
        radar.bootstrap()
    # сначала догоняем то, что пришло; карту шлём, только если обстановка изменилась
    # (или это самый первый запуск) — чтобы рестарт не спамил одинаковыми картами
    first_changed = False
    try:
        first_changed, notes = radar.poll_once()
        for n in notes:
            log(n)
    except Exception as exc:
        log(f"первый опрос не удался: {exc}")
    if first_changed or not had_state:
        radar.publish(radar.render())
    while True:
        try:
            # сводки пробуем отправить даже если канал-источник сейчас недоступен
            radar.flush_summaries()
            changed, notes = radar.poll_once()
            for n in notes:
                log(n)
            if changed:
                radar.publish(radar.render())
        except TelegramError as exc:
            log(f"ошибка Telegram: {exc}")
        except Exception:
            log("сбой опроса:\n" + traceback.format_exc(limit=2))
        time.sleep(config.POLL_SECONDS)


if __name__ == "__main__":
    main()
