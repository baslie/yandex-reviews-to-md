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


# --- Патч для устаревшей библиотеки yandex_reviews_parser ---------------------
def _apply_parser_patch() -> None:
    """
    Исправляет устаревшие CSS-селекторы в библиотеке yandex_reviews_parser.

    Библиотека не обновлялась с 2023 года, а Яндекс изменил вёрстку страницы.
    Этот патч автоматически применяется при запуске скрипта.
    """
    from dataclasses import asdict
    from selenium.webdriver.common.by import By
    from selenium.common.exceptions import NoSuchElementException
    from yandex_reviews_parser.parsers import Parser
    from yandex_reviews_parser.helpers import ParserHelper
    from yandex_reviews_parser.storage import Review

    def _patched_get_data_item(self, elem):
        """Исправленная версия метода __get_data_item с актуальными селекторами."""
        try:
            name = elem.find_element(By.XPATH, ".//span[@itemprop='name']").text
        except NoSuchElementException:
            name = None

        try:
            icon_href = elem.find_element(By.XPATH, ".//div[@class='user-icon-view__icon']").get_attribute('style')
            icon_href = icon_href.split('"')[1]
        except NoSuchElementException:
            icon_href = None

        try:
            date = elem.find_element(By.XPATH, ".//meta[@itemprop='datePublished']").get_attribute('content')
        except NoSuchElementException:
            date = None

        # ИСПРАВЛЕНО: новый селектор для текста отзыва
        try:
            text = elem.find_element(By.XPATH, ".//*[contains(@class, 'business-review-view__body')]").text
        except NoSuchElementException:
            text = None

        # ИСПРАВЛЕНО: используем meta itemprop вместо подсчёта span
        try:
            rating_meta = elem.find_element(By.XPATH, ".//meta[@itemprop='ratingValue']")
            stars = int(float(rating_meta.get_attribute('content')))
        except NoSuchElementException:
            stars = 0

        try:
            answer = elem.find_element(By.CLASS_NAME, "business-review-view__comment-expand")
            if answer:
                self.driver.execute_script("arguments[0].click()", answer)
                answer = elem.find_element(By.CLASS_NAME, "business-review-comment-content__bubble").text
            else:
                answer = None
        except NoSuchElementException:
            answer = None

        item = Review(
            name=name,
            icon_href=icon_href,
            date=ParserHelper.form_date(date),
            text=text,
            stars=stars,
            answer=answer
        )
        return asdict(item)

    # Применяем патч: заменяем приватный метод класса
    Parser._Parser__get_data_item = _patched_get_data_item


_apply_parser_patch()


# --- Патч для ошибки Chrome на Windows ----------------------------------------
def _apply_chrome_patch() -> None:
    """
    Исправляет ошибку WinError 6 при закрытии Chrome на Windows.

    При garbage collection вызывается Chrome.__del__, который пытается
    повторно вызвать quit() после того, как драйвер уже закрыт.
    """
    import undetected_chromedriver

    original_del = undetected_chromedriver.Chrome.__del__

    def patched_del(self):
        try:
            original_del(self)
        except OSError:
            pass  # Игнорируем ошибку неверного дескриптора на Windows

    undetected_chromedriver.Chrome.__del__ = patched_del


_apply_chrome_patch()


# --- Патч для прогресса парсинга ----------------------------------------------
# Глобальный callback для отображения прогресса (устанавливается в main)
_progress_callback = None


def _apply_progress_patch() -> None:
    """
    Добавляет отображение прогресса при парсинге отзывов.

    Патчит метод Parser.__get_data_reviews() для вызова callback
    при обработке каждого отзыва.
    """
    from selenium.webdriver.common.by import By
    from yandex_reviews_parser.parsers import Parser

    def _patched_get_data_reviews(self) -> list:
        reviews = []
        elements = self.driver.find_elements(
            By.CLASS_NAME, "business-reviews-card-view__review"
        )
        if len(elements) > 1:
            self._Parser__scroll_to_bottom(elements[-1])
            elements = self.driver.find_elements(
                By.CLASS_NAME, "business-reviews-card-view__review"
            )

        total = len(elements)
        for idx, elem in enumerate(elements, 1):
            reviews.append(self._Parser__get_data_item(elem))
            if _progress_callback:
                _progress_callback(idx, total)
        return reviews

    Parser._Parser__get_data_reviews = _patched_get_data_reviews


_apply_progress_patch()
# ------------------------------------------------------------------------------


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
__version__ = "0.3.0"

# Символы для спиннера (ASCII-совместимые для Windows)
_SPINNER_FRAMES: str = "|/-\\"


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

    match = re.search(r"/(\d{6,})(?:/|\?|$)", source)
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
        f"**Рейтинг:** {company['rating']}/5  \n"
        f"**Всего голосов:** {company['count_rating']}\n"
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
        md.append((review.get("text") or "").strip() or "_(текст отсутствует)_")
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
    global _progress_callback

    # Создаём прогресс-бар (если tqdm доступен)
    pbar = None
    stop_event = None
    spinner_thread = None

    # Спиннер для этапа запуска браузера и загрузки страницы
    startup_stop_event = threading.Event()
    startup_spinner_thread = threading.Thread(
        target=show_spinner,
        args=("Запуск браузера и загрузка страницы", startup_stop_event),
        daemon=True,
    )
    startup_spinner_thread.start()
    startup_spinner_stopped = False

    if tqdm:
        # pbar создаётся лениво — только после остановки спиннера
        def on_progress(current: int, total: int) -> None:
            nonlocal startup_spinner_stopped, pbar
            # Останавливаем спиннер запуска при первом отзыве
            if not startup_spinner_stopped:
                startup_spinner_stopped = True
                startup_stop_event.set()
                startup_spinner_thread.join()
                # Создаём прогресс-бар только сейчас
                pbar = tqdm(total=total, desc="Парсинг отзывов", unit="отзыв", ncols=80)

            if pbar.total != total:
                pbar.total = total
                pbar.refresh()
            pbar.n = current
            pbar.refresh()

        _progress_callback = on_progress
    else:
        # Fallback: показываем спиннер если tqdm недоступен
        # Спиннер запуска уже работает, переключим текст при первом отзыве
        stop_event = threading.Event()

        def on_progress_fallback(current: int, total: int) -> None:
            nonlocal startup_spinner_stopped, spinner_thread
            if not startup_spinner_stopped:
                startup_spinner_stopped = True
                startup_stop_event.set()
                startup_spinner_thread.join()
                # Запускаем спиннер парсинга
                spinner_thread = threading.Thread(
                    target=show_spinner,
                    args=("  + Идёт парсинг...", stop_event),
                    daemon=True,
                )
                spinner_thread.start()

        _progress_callback = on_progress_fallback

    start_ts = time.perf_counter()

    try:
        data = yp.parse()
    except KeyboardInterrupt:  # graceful shutdown
        # Останавливаем спиннер запуска, если ещё работает
        if not startup_spinner_stopped:
            startup_stop_event.set()
            startup_spinner_thread.join()
        if pbar:
            pbar.close()
        elif stop_event and spinner_thread:
            stop_event.set()
            spinner_thread.join()
        sys.exit("\n[-] Операция прервана пользователем (Ctrl+C)")
    finally:
        _progress_callback = None
        # Останавливаем спиннер запуска, если ещё работает
        if not startup_spinner_stopped:
            startup_stop_event.set()
            startup_spinner_thread.join()
        if pbar:
            pbar.close()
        elif stop_event and spinner_thread:
            stop_event.set()
            spinner_thread.join()

    elapsed = time.perf_counter() - start_ts
    count_reviews = len(data["company_reviews"])
    logging.info("Скачано отзывов: %s (время: %.1f с)", count_reviews, elapsed)

    # --- Форматирование --------------------------------------------------------
    md_text = build_markdown(data, verbose=args.verbose)
    output_path = _validate_output(args.output, company_id)
    output_path.write_text(md_text, encoding="utf-8")

    print(f"[+] Markdown сохранён: {output_path}")


# ------------------------------------------------------------------------------
if __name__ == "__main__":
    main()
