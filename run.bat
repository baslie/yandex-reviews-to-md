@echo off
chcp 65001 >nul

echo ===============================================
echo   Yandex Reviews to Markdown
echo ===============================================
echo.
echo Скрипт скачивает отзывы о компании с Яндекс.Карт,
echo сохраняет их в файл Markdown и выкачивает аватары
echo авторов и прикреплённые фотографии в подкаталог
echo "reviews_<id>_media".
echo.
echo -----------------------------------------------
echo   Примеры ввода:
echo -----------------------------------------------
echo   https://yandex.ru/profile/44307431220
echo   https://yandex.ru/maps/org/retroznak/44307431220/
echo   44307431220
echo -----------------------------------------------
echo   Дополнительные флаги (необязательно):
echo     --sort date-new ^| date-old ^| rating-high ^| rating-low
echo     --no-download-media    (не качать фото, оставить URL)
echo -----------------------------------------------
echo.
set /p INPUT="Введите ссылку или ID компании: "
echo.

if "%INPUT%"=="" (
    echo [!] Ошибка: ничего не введено.
    pause
    exit /b 1
)

python "%~dp0yandex_reviews_to_md.py" "%INPUT%"

echo.
echo ===============================================
echo   Готово! Нажмите любую клавишу для выхода.
echo ===============================================
pause >nul
