import os
import re
import logging
import asyncio
import json
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.error import TimedOut
from parsers import get_info_efrsb, get_info_kad_arbitr

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка переменных из .env файла
load_dotenv()

# Настройка токена
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
PROXY_API_URL = os.getenv('PROXY_API_URL')


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start."""
    logger.info(f"Пользователь {update.effective_user.id} запустил команду /start")
    try:
        await update.message.reply_text(
            "Уважаемый пользователь,\n\n"
            "Я бот для поиска информации по ИНН на сайтах ЕФРСБ и Кад.арбитр. "
            "Введите ИНН (10 или 12 цифр) для поиска."
        )
    except TimedOut:
        logger.warning("Тайм-аут при выполнении команды /start. Пробуем снова.")
        await asyncio.sleep(2)
        await update.message.reply_text(
            "Уважаемый пользователь,\n\n"
            "Я бот для поиска информации по ИНН на сайтах ЕФРСБ и Кад.арбитр. "
            "Введите ИНН (10 или 12 цифр) для поиска."
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений."""
    inn = update.message.text.strip()

    # Валидация ИНН
    if not re.match(r'^\d{10}$|^\d{12}$', inn):
        try:
            await update.message.reply_text("Ошибка: ИНН должен содержать 10 или 12 цифр.")
            return
        except TimedOut:
            logger.warning("Тайм-аут при отправке ошибки валидации ИНН. Пробуем снова.")
            await asyncio.sleep(2)
            await update.message.reply_text("Ошибка: ИНН должен содержать 10 или 12 цифр.")
            return

    # Отправка сообщения об обработке
    waiting_message = await update.message.reply_text("Обработка данных начата. Пожалуйста, ожидайте.")

    try:
        # Получение данных с сайтов
        efrsb_data = await get_info_efrsb(inn, cdp_endpoint="http://localhost:9222")
        kad_arbitr_data = await get_info_kad_arbitr(inn, cdp_endpoint="http://localhost:9222")

        # Парсинг JSON-строк в словари
        try:
            efrsb_data = json.loads(efrsb_data)
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON для ЕФРСБ (ИНН {inn}): {str(e)}")
            efrsb_data = {"error": f"Ошибка парсинга JSON: {str(e)}"}

        try:
            kad_arbitr_data = json.loads(kad_arbitr_data)
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON для Кад.арбитр (ИНН {inn}): {str(e)}")
            kad_arbitr_data = {"error": f"Ошибка парсинга JSON: {str(e)}"}

        # Формирование отчета в формате оригинального текстового файла
        report = [f"Отчет по должнику (ИНН: {inn})", "============================="]

        # 1. Основные данные
        report.append("\n1. Основные данные")
        report.append("-------------------")
        report.append(f"- ИНН: {inn}")

        # 2. ЕФРСБ
        report.append("\n2. ЕФРСБ")
        report.append("-------------------")
        if isinstance(efrsb_data, dict):
            if "error" in efrsb_data:
                error_msg = efrsb_data.get("error", "Неизвестная ошибка")
                if "Timeout" in error_msg or "net::ERR_TIMED_OUT" in error_msg:
                    report.append("- Статус: Недоступно из-за превышения времени ожидания загрузки страницы")
                elif "Неверный формат" in error_msg:
                    report.append("- Статус: Не проверено из-за неверного формата. Проверьте формат")
                else:
                    report.append(f"- Статус: Ошибка: {error_msg}")
            else:
                individuals = efrsb_data.get("individuals", [])
                legal_entities = efrsb_data.get("legal_entities", [])
                if not (individuals or legal_entities):
                    report.append("- Банкротство: Не найдено")
                else:
                    report.append("- Банкротство:")
                    if individuals:
                        for idx, person in enumerate(individuals, 1):
                            report.append(f"  - Физическое лицо {idx}:")
                            report.append(f"    - ФИО: {person.get('full_name', 'Неизвестно')}")
                            report.append(f"    - Адрес: {person.get('address', 'Неизвестно')}")
                            report.append(f"    - Статус: {person.get('status', 'Неизвестно')}")
                            report.append(f"    - Дата статуса: {person.get('status_date', 'Неизвестно')}")
                            report.append(f"    - Номер дела: {person.get('court_case_number', 'Неизвестно')}")
                            report.append(
                                f"    - Арбитражный управляющий: {person.get('arbitration_manager', 'Неизвестно')}")
                    if legal_entities:
                        for idx, entity in enumerate(legal_entities, 1):
                            report.append(f"  - Юридическое лицо {idx}:")
                            report.append(f"    - Название: {entity.get('name', 'Неизвестно')}")
                            report.append(f"    - ИНН: {entity.get('inn', 'Неизвестно')}")
                            report.append(f"    - Статус: {entity.get('status', 'Неизвестно')}")
                            report.append(f"    - Дата статуса: {entity.get('status_date', 'Неизвестно')}")
                            report.append(f"    - Номер дела: {entity.get('court_case_number', 'Неизвестно')}")
                            report.append(
                                f"    - Арбитражный управляющий: {entity.get('arbitration_manager', 'Неизвестно')}")
        else:
            report.append("- Банкротство: Ошибка: Некорректные данные")

        # 3. Кад.арбитр
        report.append("\n3. Кад.арбитр")
        report.append("-------------------")
        if isinstance(kad_arbitr_data, dict):
            if "error" in kad_arbitr_data:
                error_msg = kad_arbitr_data.get("error", "Неизвестная ошибка")
                if "Timeout" in error_msg or "net::ERR_TIMED_OUT" in error_msg:
                    report.append("- Статус: Недоступно из-за превышения времени ожидания загрузки страницы")
                elif "Неверный формат" in error_msg:
                    report.append("- Статус: Не проверено из-за неверного формата. Проверьте формат")
                elif "капча" in error_msg.lower():
                    report.append("- Статус: Обнаружена капча, попробуйте позже")
                else:
                    report.append(f"- Статус: Ошибка: {error_msg}")
            else:
                cases = kad_arbitr_data.get("cases", [])
                if not cases:
                    report.append("- Судебные дела: Не найдены")
                else:
                    report.append("- Судебные дела:")
                    for idx, case in enumerate(cases, 1):
                        report.append(f"  - Дело {idx}:")
                        report.append(f"    - Номер дела: {case.get('case_number', 'Неизвестно')}")
                        report.append(f"    - Дата регистрации: {case.get('registration_date', 'Неизвестно')}")
                        report.append(f"    - Судья: {case.get('judge', 'Неизвестно')}")
                        report.append(f"    - Текущая инстанция: {case.get('current_instance', 'Неизвестно')}")
                        report.append(f"    - Истец: {case.get('plaintiff', 'Неизвестно')}")
                        report.append(f"    - Ответчик: {case.get('respondent', 'Неизвестно')}")
        else:
            report.append("- Судебные дела: Ошибка: Некорректные данные")

        report.append("=============================")
        response = "\n".join(report)

        # Удаление сообщения об ожидании
        await waiting_message.delete()

        # Отправка результата
        for attempt in range(3):
            try:
                await update.message.reply_text(response)
                return
            except TimedOut:
                logger.warning(f"Тайм-аут при отправке результата (попытка {attempt + 1}/3).")
                await asyncio.sleep(2)
        logger.error("Не удалось отправить результат после 3 попыток.")
        await update.message.reply_text("Ошибка связи с сервером. Пожалуйста, попробуйте снова.")

    except Exception as e:
        logger.error(f"Ошибка при обработке данных для ИНН {inn}: {e}")
        await waiting_message.delete()
        try:
            await update.message.reply_text(f"Произошла ошибка: {e}. Пожалуйста, попробуйте снова.")
        except TimedOut:
            logger.warning("Тайм-аут при отправке ошибки. Пробуем снова.")
            await asyncio.sleep(2)
            await update.message.reply_text(f"Произошла ошибка: {e}. Пожалуйста, попробуйте снова.")


def main():
    """Запуск Telegram-бота."""
    try:
        application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        logger.info("Запуск бота...")
        print("Бот запущен")
        application.run_polling()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Остановка бота...")
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
        print(f"Ошибка при запуске бота: {e}")
        exit(1)


if __name__ == '__main__':
    main()