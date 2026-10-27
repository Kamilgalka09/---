#!/usr/bin/env python3
"""Упаковка проекта в zip-архив для загрузки на Amvera."""
import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Упаковка радара БПЛА для хостинга")
    parser.add_argument("--version", default="1.0", help="Версия архива (по умолчанию 1.0)")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    output_dir = root / "dist"
    archive_name = f"radar-bot-hosting_{args.version}.zip"
    archive_path = output_dir / archive_name

    print("=== Радар БПЛА — упаковка для хостинга ===")
    print()

    # Создаём директорию вывода
    output_dir.mkdir(exist_ok=True)

    # Файлы, которые должны войти в архив
    included_files = [
        "bot.py",
        "config.py",
        "fetch_tg.py",
        "maprender.py",
        "parse.py",
        "regions.py",
        "report.py",
        "state.py",
        "tg_api.py",
        "amvera.yaml",
        "requirements.txt",
        "README.md",
        ".env.example",
        "data/lexicon.json",
        "data/regions.geojson",
        "assets/fonts/NotoSans-Bold.ttf",
        "assets/fonts/NotoSans-Regular.ttf",
    ]

    # Проверяем наличие всех файлов
    missing = []
    for f in included_files:
        path = root / f
        if path.exists():
            print(f"[+] {f}")
        else:
            print(f"[-] НЕ НАЙДЕН: {f}")
            missing.append(f)

    if missing:
        print()
        print(f"[-] Пропущены файлы: {', '.join(missing)}")
        sys.exit(1)

    print()

    # Удаляем старый архив
    if archive_path.exists():
        archive_path.unlink()
        print("[x] Удалён старый архив")

    # Создаём zip-архив
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in included_files:
            src = root / f
            zf.write(src, f)

    size_mb = archive_path.stat().st_size / (1024 * 1024)
    print()
    print(f"[+] Архив создан: {archive_path}")
    print(f"    Размер: {size_mb:.2f} МБ")
    print()
    print("=== Готово! ===")
    print(f"Загрузите {archive_name} в Amvera через панель проектов.")


if __name__ == "__main__":
    main()
