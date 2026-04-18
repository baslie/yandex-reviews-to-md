---
name: collect-yandex-reviews
description: Собирает отзывы компаний с Яндекс.Карт в Markdown через локальный скрипт yandex_reviews_to_md.py. Сначала проверяет окружение (Python, yandex_reviews_parser, tqdm, colorama, selenium, Chrome), потом ведёт пользователя по викторине (URL или ID, сортировка, скачивать ли медиа, путь сохранения) и поддерживает выгрузку нескольких организаций за одну сессию. Используй когда пользователь просит «собрать отзывы», «выгрузить отзывы», «спарсить отзывы», «yandex reviews», «отзывы с Яндекс.Карт», «отзывы из Яндекса», «спарсить компанию», или присылает ссылку yandex.ru/maps/org/... либо yandex.ru/profile/...
allowed-tools: Bash, AskUserQuestion, Read
---

# Collect Yandex Reviews (локальный скилл)

Оборачивает CLI-скрипт `yandex_reviews_to_md.py` из этого репозитория в интерактивный диалог. Поддерживает выгрузку **нескольких организаций за одну сессию**: после каждой компании скилл спрашивает, нужна ли следующая.

## Критично: кодировка на Windows

Скрипт выводит кириллицу. Нативная Windows-кодировка `cp1251` ломает вывод — **всегда** запускай Python с `PYTHONIOENCODING=utf-8`:

```bash
PYTHONIOENCODING=utf-8 python yandex_reviews_to_md.py ...
```

## Шаг 1 — Проверка окружения

Запусти один Bash-вызов и оцени результат:

```bash
echo "--- python ---"
python --version 2>&1 || echo "MISSING:python"
echo "--- script ---"
ls yandex_reviews_to_md.py 2>&1 || echo "MISSING:script"
echo "--- libs ---"
PYTHONIOENCODING=utf-8 python -c "import yandex_reviews_parser, tqdm, colorama, selenium; print('OK')" 2>&1 || echo "MISSING:libs"
echo "--- chrome ---"
where chrome 2>&1 || where chrome.exe 2>&1 || echo "MISSING:chrome"
```

Анализ:

| Маркер | Действие |
|---|---|
| `MISSING:python` | Python не установлен или не в PATH. Сообщи пользователю: «Установи Python 3.8+ с python.org и добавь в PATH» — **остановись**. |
| `MISSING:script` | Не та рабочая директория. Сообщи: «Запусти Claude Code из корня репозитория `yandex-reviews-to-md`» — **остановись**. |
| `MISSING:libs` | Покажи команду установки и **остановись**: `pip install yandex_reviews_parser tqdm colorama selenium` |
| `MISSING:chrome` | Не критично (Selenium может найти Edge/Chromium). Только предупреди: «Chrome не найден в PATH — если парсер упадёт на запуске браузера, установи Chrome с google.com/chrome». |
| Всё OK | Идём к Шагу 2. |

## Шаг 2 — Викторина по одной компании

Один вызов `AskUserQuestion` с **четырьмя** вопросами в массиве `questions`:

1. **header**: `Компания`, **question**: `URL страницы отзывов или ID компании Яндекс.Карт?`, **multiSelect**: false, **options**: `[{label: "Other", description: "Введу URL или ID вручную"}]`. (Свободный ввод — пользователь напишет ссылку/ID в поле Other.)
2. **header**: `Сортировка`, **question**: `Как сортировать отзывы?`, **multiSelect**: false, **options**: `[{label: "date-new", description: "Сначала новые (по умолчанию)"}, {label: "date-old", description: "Сначала старые"}, {label: "rating-high", description: "Сначала с высокой оценкой"}, {label: "rating-low", description: "Сначала с низкой оценкой"}]`.
3. **header**: `Медиа`, **question**: `Скачивать аватары и фото локально?`, **multiSelect**: false, **options**: `[{label: "Да", description: "Скачать в подкаталог *_media/"}, {label: "Нет", description: "Оставить только URL в Markdown"}]`.
4. **header**: `Куда сохранить`, **question**: `Куда положить результат?`, **multiSelect**: false, **options**: `[{label: "Текущая директория", description: "reviews_<id>.md рядом со скриптом"}, {label: "Other", description: "Укажу свой путь к каталогу или .md-файлу"}]`.

После ответа собери в памяти: `INPUT`, `SORT`, `MEDIA`, `OUTPUT`.

## Шаг 3 — Запуск парсера

Собери и выполни команду (опции добавляй только при нужных значениях):

```bash
PYTHONIOENCODING=utf-8 python yandex_reviews_to_md.py "<INPUT>" --sort <SORT> [--no-download-media] [-o "<OUTPUT>"]
```

Правила:
- `--no-download-media` добавлять только если на вопрос «Медиа» выбрано «Нет».
- `-o "<OUTPUT>"` добавлять только если выбрано «Other» с конкретным путём.
- `INPUT` оборачивать в двойные кавычки — там может быть `&` или `?`.

После завершения скрипта прочитай его stdout и найди путь к созданному `.md` (скрипт пишет его в логе) либо вычисли по шаблону `reviews_<id>.md`. Запомни: `URL/ID`, имя `.md`-файла, сортировку, медиа-флаг, статус (успех/ошибка).

## Шаг 4 — Ещё одна компания?

Спроси одним `AskUserQuestion`:

- **header**: `Ещё одна?`, **question**: `Собрать отзывы по ещё одной компании?`, **multiSelect**: false, **options**: `[{label: "Да", description: "Запустить викторину для следующей компании"}, {label: "Нет", description: "Завершить и показать сводку"}]`.

Если «Да» — вернись к **Шагу 2** (новая викторина, копится в общем списке результатов). Если «Нет» — Шаг 5.

## Шаг 5 — Итоговая сводка

Выведи Markdown-таблицу со всеми обработанными компаниями за сессию:

```
| # | Компания (URL/ID) | Файл | Сортировка | Медиа | Статус |
|---|-------------------|------|------------|-------|--------|
| 1 | 44307431220       | reviews_44307431220.md | date-new | Да | Успех |
| 2 | https://yandex.ru/profile/12345 | reviews_12345.md | rating-low | Нет | Успех |
```

Если какие-то запуски упали — в столбце «Статус» покажи коротко причину (капча, таймаут, неверный URL и т.п.).

## Типичные ошибки

| Симптом | Причина и решение |
|---|---|
| `ModuleNotFoundError: yandex_reviews_parser` | Не выполнен `pip install` — повтори Шаг 1 и предложи команду. |
| `UnicodeEncodeError` / кракозябры | Забыт `PYTHONIOENCODING=utf-8` перед `python`. |
| `selenium.common.exceptions.WebDriverException` | Chrome не установлен/устарел — установи свежий Chrome. |
| Скрипт виснет, потом «капча» | Яндекс показал анти-бота. Подожди 10–15 минут или смени IP — это ограничение источника, не скилла. |
| `ValueError: не удалось извлечь ID` | Введена битая ссылка. Покажи поддерживаемые форматы из README и предложи переввести. |
