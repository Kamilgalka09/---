"""Разбор текста поста: что за угроза, по каким регионам.

Все формулировки живут в базе `data/lexicon.json` — код только применяет правила.
Порядок: реклама/шум → сводка/прогноз → отбой → частичный отбой → тревога.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from regions import RegionIndex

LEXICON_PATH = Path(__file__).parent / "data" / "lexicon.json"

FOOTER_RE = re.compile(
    r"(?i)^.*(?:радар по всей россии|radarrussiia|max\.ru/join|наш канал в мах).*$"
)
LINKS_RE = re.compile(r"https?://\S+|@\w+")

# Запасной минимум, если lexicon.json потерялся или битый: бот продолжает работать.
DEFAULT_LEXICON: dict = {
    "threat_words": {"bpla": ["бпла", "беспилот", "дрон"], "rocket": ["ракет"]},
    "strong_live_markers": ["опасн", "угроз", "атак", "тревог", "фиксац", "сбит",
                            "пролет", "подлет", "работа пво", "прилет", "попадан",
                            "меры безопасности", "обломк"],
    "weak_live_markers": ["летит", "летят", "в сторону", "в направлении", "курс", "ожида"],
    "alert_only_markers": ["меры безопасности", "работа пво", "фиксац", "сбит"],
    "clear_markers": ["отбой"],
    "clear_all_markers": ["по всем", "всех ранее", "всем регионам"],
    "partial_clear_markers": ["опасность сохраняется", "сохраняется опасность"],
    "hard_summary_markers": ["прогноз обстановки", "предстоящую ночь",
                             "за прошедшую ночь", "уничтожено", "силами пво",
                             "силами противовоздушной", "итоги", "статистик",
                             "оперативная сводка", "аналитик"],
    "weak_summary_markers": ["уничтожен", "перехвачен", "погиб", "пострадав"],
    "ignore_markers": ["реклама", "подписывайтесь", "розыгрыш", "обратная связь",
                       "наш канал", "партнер", "радар в мах", "не наблюдаем",
                       "обстановке тихо", "обстановка тихо"],
}


@dataclass
class Parsed:
    kind: str                      # alert | clear | clear_all | ignore
    types: list[str] = field(default_factory=list)   # bpla | rocket
    regions: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class Losses:
    """Сводка «за ночь/за смену сбито N БПЛА над территориями …»."""
    total: int
    period: str
    regions: list[str] = field(default_factory=list)
    signature: str = ""


_NIGHT_MARKERS = (
    ("за прошедшую ночь", "За прошедшую ночь"),
    ("за минувшую ночь", "За минувшую ночь"),
    ("прошедшей ночью", "Прошедшей ночью"),
    ("за сутки", "За сутки"),
    ("за ночь", "За ночь"),
)
_TIME_RANGE_RE = re.compile(r"с\s*(\d{1,2}[:.]\d{2})\s*до\s*(\d{1,2}[:.]\d{2})")
_COUNT_RE = re.compile(r"(\d{1,4})\s*(?:бпла|беспилот\w*|дрон\w*)")
_COUNT_FALLBACK_RE = re.compile(r"уничтожен\w*\s+(\d{1,4})")


def normalize(text: str) -> str:
    return text.replace("ё", "е").replace("Ё", "Е").lower()


def _read_lexicon(path: Path | None = None) -> dict | None:
    """Читает базу и проверяет обязательные разделы. None — файл битый/недописан."""
    try:
        data = json.loads((path or LEXICON_PATH).read_text(encoding="utf-8"))
    except Exception:
        return None
    required = ("threat_words", "strong_live_markers", "clear_markers",
                "alert_only_markers", "hard_summary_markers")
    return data if all(k in data for k in required) else None


LEXICON = _read_lexicon() or DEFAULT_LEXICON
_LEX_MTIME = 0.0


def current_lexicon() -> dict:
    """Отдаёт базу формулировок и подхватывает правки lexicon.json без перезапуска.

    Битый (недописанный) файл не подменяет рабочую базу: пробуем снова на следующем посте.
    """
    global LEXICON, _LEX_MTIME
    try:
        mtime = LEXICON_PATH.stat().st_mtime
    except OSError:
        return LEXICON
    if mtime != _LEX_MTIME:
        fresh = _read_lexicon()
        if fresh is not None:
            LEXICON = fresh
            _LEX_MTIME = mtime
    return LEXICON


def lexicon_status() -> str:
    lex = current_lexicon()
    markers = sum(len(v) for k, v in lex.items() if isinstance(v, list))
    return f"v{lex.get('version', '?')}, маркеров: {markers}"


current_lexicon()


def clean_text(text: str) -> str:
    """Обрезает рекламный подвал канала и ссылки."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if FOOTER_RE.match(line.strip()):
            lines = lines[:i]
            break
    text = "\n".join(lines)
    text = LINKS_RE.sub("", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def _first(low: str, markers) -> str:
    for m in markers or ():
        if m and m in low:
            return m
    return ""


def _types_from_words(lex: dict, low: str) -> list[str]:
    words = lex.get("threat_words", {})
    types = []
    if _first(low, words.get("rocket", ())):
        types.append("rocket")
    if _first(low, words.get("bpla", ())):
        types.append("bpla")
    return types


def parse_losses(text: str, index: RegionIndex) -> Losses | None:
    """Сводка о сбитых за период (2 раза в сутки). Карту не трогает — только отдельный пост."""
    body = clean_text(text)
    low = normalize(body)
    if "уничтожен" not in low:
        return None
    weapon = any(w in low for w in ("бпла", "беспилот", "дрон"))
    if not weapon and not any(w in low for w in ("пво", "противовоздушн")):
        return None

    period = ""
    for marker, label in _NIGHT_MARKERS:
        if marker in low:
            period = label
            break
    if not period:
        m = _TIME_RANGE_RE.search(low)
        if m:
            period = f"С {m.group(1).replace('.', ':')} до {m.group(2).replace('.', ':')}"
    if not period:
        return None

    m = _COUNT_RE.search(low) or _COUNT_FALLBACK_RE.search(low)
    if not m:
        return None
    total = int(m.group(1))
    if total <= 0:
        return None

    regions = index.find(body)
    if not regions:
        return None
    return Losses(total, period, regions, f"{total}|{period}|{','.join(regions)}")


def parse_post(text: str, index: RegionIndex, lexicon: dict | None = None) -> Parsed:
    lex = lexicon or current_lexicon()
    body = clean_text(text)
    low = normalize(body)

    if not low:
        return Parsed("ignore", reason="пустой текст")

    regions = index.find(body)

    # 1. Реклама, призывы, посты «у нас тихо».
    hit = _first(low, lex.get("ignore_markers"))
    if hit:
        return Parsed("ignore", regions=regions, reason=f"реклама/шум: {hit}")

    # 2. Прогнозы и сводки за период — их нельзя проецировать на карту.
    hit = _first(low, lex.get("hard_summary_markers"))
    if hit:
        return Parsed("ignore", regions=regions, reason=f"сводка/прогноз: {hit}")

    rocket_hit = _first(low, lex["threat_words"].get("rocket"))
    bpla_hit = _first(low, lex["threat_words"].get("bpla"))
    strong = _first(low, lex.get("strong_live_markers"))
    weak = _first(low, lex.get("weak_live_markers"))
    alert_only = _first(low, lex.get("alert_only_markers"))

    # 3. Отбой (и его опасная разновидность «отбой, но опасность сохраняется»).
    clear_hit = _first(low, lex.get("clear_markers"))
    if clear_hit:
        types = _types_from_words(lex, low)
        if _first(low, lex.get("partial_clear_markers")):
            if not types:
                types = ["bpla"]
            if not regions:
                return Parsed("ignore", reason="тревога без региона")
            return Parsed("alert", types, regions, "отбой с оговоркой: опасность сохраняется")
        if not types:
            types = ["rocket", "bpla"]
        if _first(low, lex.get("clear_all_markers")):
            return Parsed("clear_all", types, regions, "отбой по всем объявленным регионам")
        if not regions:
            return Parsed("ignore", reason="отбой без региона")
        return Parsed("clear", types, regions, "отбой")

    # 4. Слабая сводка («уничтожено», «погиб») отбрасывается, если нет живого маркера.
    hit = _first(low, lex.get("weak_summary_markers"))
    if hit and not strong:
        return Parsed("ignore", regions=regions, reason=f"итоговая сводка: {hit}")

    # 5. Тревога.
    threat_tone = strong or weak or alert_only or _first(
        low, ("опасн", "угроз", "атак", "тревог"))
    types = []
    if rocket_hit and threat_tone:
        types.append("rocket")
    if bpla_hit and threat_tone:
        types.append("bpla")
    if not types and alert_only and regions:
        types.append("bpla")           # «Меры безопасности», «Работа ПВО» без слова «БПЛА»
    if not types and regions and (strong or weak or alert_only):
        # Регион + тревожный тон без названного типа («приготовиться к атаке») —
        # канал про БПЛА, поэтому считаем дронами.
        types.append(lex.get("default_type", "bpla"))
    if not types and regions and (rocket_hit or bpla_hit):
        # Страховка: новая формулировка, которой ещё нет в базе, но регион и тип угрозы
        # названы прямо. Лучше показать на карте, чем потерять сообщение.
        if rocket_hit:
            types.append("rocket")
        if bpla_hit:
            types.append("bpla")
    if not types:
        return Parsed("ignore", regions=regions, reason="нет признака угрозы")
    if not regions:
        return Parsed("ignore", reason="тревога без региона")

    why = strong or weak or alert_only or "фоллбэк: регион + тип угрозы"
    return Parsed("alert", types, regions, f"тревога: {why}")
