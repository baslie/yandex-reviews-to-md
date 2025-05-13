#!/usr/bin/env python3
"""
yandex_reviews_to_md.py
~~~~~~~~~~~~~~~~~~~~~~~
CLI-утилита для массовой выгрузки отзывов о компаниях с сервиса «Яндекс Карты»
в единый Markdown-файл. Скрипт получает ID компании или URL страницы с отзывами,
обращается к неофициальному парсеру YandexParser и сохраняет результат в
читаемом формате, снабжая пользователя детальной индикацией прогресса.

Запуск:
    python yandex_reviews_to_md.py https://yandex.ru/maps/org/1234567 --output reviews.md
    python yandex_reviews_to_md.py 1234567 --output reviews.md
"""

from __future__ import annotations

import argparse
import itertools
import logging
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from yandex_reviews_parser.utils import YandexParser

# --- Опциональные зависимости -------------------------------------------------
try:
    from colorama import just_fix_windows_console  # type: ignore
    just_fix_windows_console()
except ModuleNotFoundError:
    # Отсутствие colorama не критично – просто цвета будут не настолько корректны на Windows
    pass

try:
    from tqdm import tqdm
except ModuleNotFoundError:  # pragma: no cover
    tqdm = None  # type: ignore
# ------------------------------------------------------------------------------

__all__ = ["main"]
__version__ = "0.2.0"

# Символы для «танцующего» спиннера (braille)
_SPINNER_FRAMES: str = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


# ------------------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------------------------
def extract_id(source: str) -> int:
    """
    Вычленяет числовой идентификатор компании из переданной строки.

    Аргументы:
        source: URL страницы «Яндекс Карт» или строка-число.

    Возвращает:
        int: ID компании.

    Исключения:
        ValueError: если ID извлечь не удалось.
    """
    if source.isdigit():
        return int(source)

    match = re.search(r"/(\d{6,})/", source)
    if match:
        return int(match.group(1))

    raise ValueError("Не удалось определить ID компании из переданной строки.")


def show_spinner(prefix: str, stop_event: threading.Event) -> None:
    """
    Отображает в stdout псевдографический спиннер, пока не будет установлен `stop_event`.

    Использует «невидимую» каретку `\\r` для обновления строки без переноса.

    Args:
        prefix: Текст перед спиннером.
        stop_event: Флаг завершения.
    """
    for char in itertools.cycle(_SPINNER_FRAMES):
        if stop_event.is_set():
            break
        sys.stdout.write(f"\r{prefix} {char}")
        sys.stdout.flush()
        time.sleep(0.12)

    # Стереть строку после завершения
    sys.stdout.write("\r" + " " * (len(prefix) + 2) + "\r")
    sys.stdout.flush()


def build_markdown(data: Dict[str, Any], verbose: bool = False) -> str:
    """
    Преобразует сырые данные парсера в Markdown-текст.

    Args:
        data: Результат `YandexParser.parse()`.
        verbose: Выводить ли прогресс в консоль.

    Returns:
        Готовый Markdown.
    """
    company: Dict[str, Any] = data["company_info"]
    reviews: List[Dict[str, Any]] = data["company_reviews"]

    md: List[str] = []

    # Шапка
    md.append(f"# {company['name']}\n")
    md.append(
        f"**Рейтинг:** {company['rating']} ⭐  \n"
        f"**Всего голосов:** {company['count_rating']}  \n"
        f"**Звёзд на Яндекс.Картах:** {company['stars']}/5\n"
    )
    md.append("\n---\n")
    md.append("## Отзывы\n")

    iterable = (
        tqdm(  # type: ignore[arg-type]
            enumerate(reviews, 1),
            total=len(reviews),
            desc="Форматируем",
            ncols=80,
            unit="отзыв",
            colour=None,
        )
        if tqdm and not verbose
        else enumerate(reviews, 1)
    )

    for idx, review in iterable:
        if verbose and idx % 25 == 0:
            logging.info("  ...сформировано %s/%s", idx, len(reviews))

        date_str = datetime.fromtimestamp(review["date"]).strftime("%d.%m.%Y")
        md.append(f"### {idx}. {review['name']} — {date_str}")
        md.append(f"**Оценка:** {review['stars']}/5\n")
        md.append(review["text"].strip() or "_(текст отсутствует)_")
        if answer := review.get("answer"):
            md.append(f"\n> **Ответ компании:** {answer.strip()}")
        md.append("\n---\n")

    return "\n".join(md)


# ------------------------------------------------------------------------------
def _configure_logging(verbose: bool) -> None:
    """Единообразная настройка логгера."""
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname).1s %(asctime)s │ %(message)s",
        datefmt="%H:%M:%S",
    )


def _validate_output(path_str: str | None, company_id: int) -> Path:
    """
    Проверяет корректность выходного пути и формирует `Path`.

    Args:
        path_str: Строка из аргумента CLI `--output`.
        company_id: Fallback-ID для имени файла.

    Returns:
        pathlib.Path: Абсолютный путь для записи.
    """
    if not path_str:
        return Path(f"reviews_{company_id}.md").absolute()

    path = Path(path_str).expanduser().absolute()

    if path.is_dir():
        path = path / f"reviews_{company_id}.md"

    # Создаём каталоги, если их нет
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    return path


# ----------------------------------- CLI --------------------------------------
def main() -> None:  # noqa: C901 – сложность обусловлена CLI
    """Точка входа CLI-скрипта."""
    argp = argparse.ArgumentParser(
        prog="yandex-reviews-to-md",
        description=(
            "Скачать отзывы компании с Яндекс.Карт и сохранить их в файл Markdown "
            "с подробной индикацией прогресса."
        ),
    )
    argp.add_argument("input", nargs="?", help="URL с отзывами или ID компании")
    argp.add_argument("-o", "--output", help="Файл назначения (.md или каталог)")
    argp.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Больше сообщений о ходе работы",
    )
    args = argp.parse_args()

    _configure_logging(args.verbose)

    # --- Ввод ID компании ------------------------------------------------------
    input_value = args.input or input("Введите URL страницы с отзывами или ID компании: ").strip()
    try:
        company_id = extract_id(input_value)
    except ValueError as exc:
        sys.exit(f"Ошибка: {exc}")

    logging.info("Запускаю парсер для ID %s", company_id)
    yp = YandexParser(company_id)

    # --- Парсинг ---------------------------------------------------------------
    stop_event = threading.Event()
    spinner_thread = threading.Thread(
        target=show_spinner,
        args=("  + Идёт парсинг...", stop_event),
        daemon=True,
    )
    start_ts = time.perf_counter()
    spinner_thread.start()

    try:
        data = yp.parse()
    except KeyboardInterrupt:  # graceful shutdown
        stop_event.set()
        spinner_thread.join()
        sys.exit("\n[-] Операция прервана пользователем (Ctrl+C)")
    finally:
        stop_event.set()
        spinner_thread.join()

    elapsed = time.perf_counter() - start_ts
    count_reviews = len(data["company_reviews"])
    logging.info("Скачано отзывов: %s (время: %.1f с)", count_reviews, elapsed)

    # --- Форматирование --------------------------------------------------------
    md_text = build_markdown(data, verbose=args.verbose)
    output_path = _validate_output(args.output, company_id)
    output_path.write_text(md_text, encoding="utf-8")

    print(f"[+] Markdown сохранён ➜ {output_path}")


# ------------------------------------------------------------------------------
if __name__ == "__main__":
    main()
