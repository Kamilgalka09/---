"""Текст сводки о сбитых БПЛА для Telegram: табличка без картинки (дешево)."""
from __future__ import annotations

import html
from datetime import datetime

from parse import Losses
from regions import short_label
from state import MSK


def _short(name: str) -> str:
    return short_label(name).replace(" обл.", "")


def build_losses_message(losses: Losses, post_date: str = "") -> str:
    """Две колонки в <pre>: ровно, компактно и без рекламного подвала источника."""
    names = [_short(r) for r in losses.regions] or ["—"]
    width = max(len(n) for n in names) + 3
    half = (len(names) + 1) // 2
    left, right = names[:half], names[half:]
    rows = []
    for i, a in enumerate(left):
        b = right[i] if i < len(right) else ""
        rows.append(f"{a:<{width}}{b}".rstrip())

    when = ""
    if post_date:
        try:
            dt = datetime.fromisoformat(post_date.replace("Z", "+00:00")).astimezone(MSK)
            when = f" · {dt:%d.%m.%Y %H:%M} МСК"
        except Exception:
            when = ""

    head = (f"🛡️ <b>Сбито БПЛА: {losses.total}</b>\n"
            f"<i>{html.escape(losses.period)}{when}</i>\n\n")
    table = "\n".join(rows)
    return (head + f"<pre>{html.escape(table)}</pre>"
            + f"\n\n<i>Регионов: {len(losses.regions)} · источник: @radarrussiia</i>")
