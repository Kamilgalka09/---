"""Минимальный клиент Telegram Bot API (без сторонних telegram-библиотек)."""
from __future__ import annotations

import requests

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(RuntimeError):
    pass


def _call(token: str, method: str, timeout: int = 60, **kwargs):
    try:
        r = requests.post(API.format(token=token, method=method), timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        # не тащим текст исключения: в нём бывает URL с токеном бота
        raise TelegramError(f"сеть недоступна ({type(exc).__name__})") from None
    try:
        data = r.json()
    except ValueError:
        raise TelegramError(f"неожиданный ответ Telegram: {r.status_code}")
    if not data.get("ok"):
        raise TelegramError(f"{data.get('error_code')}: {data.get('description')}")
    return data["result"]


def get_me(token: str) -> dict:
    return _call(token, "getMe", timeout=20)


def send_photo(token: str, chat_id: str, image_path, caption: str = "") -> dict:
    with open(image_path, "rb") as fh:
        return _call(
            token, "sendPhoto",
            data={"chat_id": chat_id, "caption": caption[:1024], "parse_mode": "HTML"},
            files={"photo": (str(image_path).split("\\")[-1], fh, "image/png")},
        )


def send_document(token: str, chat_id: str, image_path, caption: str = "") -> dict:
    with open(image_path, "rb") as fh:
        return _call(
            token, "sendDocument",
            data={"chat_id": chat_id, "caption": caption[:1024], "parse_mode": "HTML"},
            files={"document": (str(image_path).split("\\")[-1], fh, "image/png")},
        )


def send_message(token: str, chat_id: str, text: str) -> dict:
    return _call(token, "sendMessage",
                 data={"chat_id": chat_id, "text": text[:4096], "parse_mode": "HTML"})
