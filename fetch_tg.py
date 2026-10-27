"""Загрузка постов публичного Telegram-канала через веб-превью t.me/s/."""
from __future__ import annotations

import html
import re
import time
import urllib.request
from datetime import datetime, timezone

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"

_BLOCK = re.compile(r'<div class="tgme_widget_message_wrap[^"]*"')
_POST_ID = re.compile(r'data-post="[^/]+/(\d+)"')
_TEXT = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
_TIME = re.compile(r'<time datetime="([^"]+)"')
_TAG = re.compile(r"<[^>]+>")


def _strip_tags(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    fragment = re.sub(r"</p>", "\n", fragment)
    fragment = _TAG.sub("", fragment)
    text = html.unescape(fragment)
    text = text.replace("\u200b", "")
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join([ln for ln in lines if ln])


def fetch_page(channel: str, before: int | None = None, timeout: int = 15,
               attempts: int = 3) -> str:
    """Страница канала. t.me периодически рвёт соединение — делаем повторы."""
    url = f"https://t.me/s/{channel}"
    if before:
        url += f"?before={before}"
    last_error: Exception | None = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ru,en"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "ignore")
        except Exception as exc:  # noqa: BLE001 — сеть нестабильна
            last_error = exc
            time.sleep(1.5 * (i + 1))
    raise last_error if last_error else RuntimeError("не удалось загрузить канал")


def parse_posts(page: str) -> list[dict]:
    """Возвращает посты в порядке публикации: {id, date, text}."""
    starts = [m.start() for m in _BLOCK.finditer(page)]
    posts = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(page)
        block = page[start:end]
        mid = _POST_ID.search(block)
        if not mid:
            continue
        text_m = _TEXT.search(block)
        text = _strip_tags(text_m.group(1)) if text_m else ""
        time_m = _TIME.search(block)
        date = time_m.group(1) if time_m else ""
        posts.append({"id": int(mid.group(1)), "date": date, "text": text})
    posts.sort(key=lambda p: p["id"])
    return posts


def fetch_posts(channel: str, pages: int = 1, before: int | None = None) -> list[dict]:
    """Несколько страниц истории (20 постов на страницу)."""
    result: list[dict] = []
    cursor = before
    for _ in range(pages):
        page = fetch_page(channel, cursor)
        batch = parse_posts(page)
        if not batch:
            break
        result = batch + result
        cursor = batch[0]["id"]
    # уникализируем по id
    seen, uniq = set(), []
    for p in result:
        if p["id"] in seen:
            continue
        seen.add(p["id"])
        uniq.append(p)
    return uniq


def parse_date(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)
