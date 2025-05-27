import asyncio
import logging
import json
import os
from playwright.async_api import async_playwright, Error as PlaywrightError
from bs4 import BeautifulSoup

# Настройка минимального логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Подавление HTTP-логов
logging.getLogger('httpx').setLevel(logging.WARNING)

async def get_info_kad_arbitr(inn: str, cdp_endpoint="http://localhost:9222") -> str:
    """Получение данных с kad.arbitr.ru через сохранение и парсинг HTML-файла."""
    url = "https://kad.arbitr.ru/"
    html_file = f"kad_{inn}.html"
    async with async_playwright() as p:
        try:
            logger.info(f"Подключение к CDP по адресу: {cdp_endpoint}")
            browser = await p.chromium.connect_over_cdp(cdp_endpoint)
            page = await browser.contexts[0].new_page()

            try:
                logger.info(f"Загружаю страницу kad.arbitr.ru")
                await page.goto(url, wait_until="domcontentloaded", timeout=10000)

                # Проверка полной загрузки: ожидание поля ввода
                logger.info("Ожидаю поле ввода 'Участник дела'")
                await page.wait_for_selector("div#sug-participants textarea", timeout=10000)
                logger.debug("Поле ввода найдено, страница готова к взаимодействию")

                # Проверка и закрытие всплывающего уведомления
                notification = await page.query_selector("div.b-promo_notification")
                if notification:
                    logger.info("Обнаружено всплывающее уведомление, пытаюсь закрыть")
                    close_button = await page.query_selector("a.b-promo_notification-popup-close")
                    if close_button:
                        await close_button.click()
                        await page.wait_for_timeout(500)
                        logger.info("Уведомление закрыто")
                    else:
                        logger.warning("Кнопка закрытия уведомления не найдена")

                # Проверка на капчу
                captcha = await page.query_selector("div.b-pravocaptcha")
                if captcha:
                    logger.error(f"Обнаружена капча для ИНН {inn}")
                    return json.dumps({"error": "Обнаружена капча, попробуйте позже"}, ensure_ascii=False, indent=2)

                # Ввод ИНН в поле "Участник дела"
                logger.info(f"Ввожу ИНН {inn} в поле 'Участник дела'")
                await page.fill("div#sug-participants textarea", inn)
                await page.wait_for_timeout(500)  # Короткая пауза после ввода

                # Нажатие кнопки "Найти"
                logger.info("Нажимаю кнопку 'Найти'")
                await page.click("div#b-form-submit button")

                # Ожидание загрузки результатов
                logger.info("Ожидаю результаты поиска")
                await page.wait_for_timeout(5000)  # Ожидание 5 секунд для рендеринга

            except PlaywrightError as e:
                logger.error(f"Ошибка при загрузке страницы или взаимодействии для ИНН {inn}: {str(e)}")
                # Сохраняем HTML для отладки
                try:
                    content = await page.content()
                    with open(html_file, "w", encoding="utf-8") as f:
                        f.write(content)
                    logger.info(f"HTML-код страницы сохранен в {html_file} для отладки")
                except Exception as save_error:
                    logger.error(f"Ошибка при сохранении HTML-кода: {str(save_error)}")
                return json.dumps({"error": f"Ошибка загрузки страницы или взаимодействия: {str(e)}"},
                                 ensure_ascii=False, indent=2)
            finally:
                # Сохранение HTML-кода страницы в файл
                try:
                    content = await page.content()
                    with open(html_file, "w", encoding="utf-8") as f:
                        f.write(content)
                    logger.info(f"HTML-код страницы сохранен в {html_file}")
                except Exception as save_error:
                    logger.error(f"Ошибка при сохранении HTML-кода для ИНН {inn}: {str(save_error)}")
                await page.close()
                await browser.close()

        except PlaywrightError as e:
            logger.error(f"Ошибка подключения к CDP для ИНН {inn}: {str(e)}")
            return json.dumps({"error": f"Ошибка подключения к браузеру: {str(e)}"}, ensure_ascii=False, indent=2)

    # Парсинг сохраненного HTML-файла
    try:
        with open(html_file, "r", encoding="utf-8") as f:
            content = f.read()
        soup = BeautifulSoup(content, 'html.parser')

        # Проверка на отсутствие результатов
        no_results = soup.find('div', class_='b-noResults')
        if no_results and no_results.get('class', []) != ['b-noResults', 'g-hidden']:
            logger.info(f"Данные для ИНН {inn}: Ничего не найдено")
            return json.dumps({"cases": []}, ensure_ascii=False, indent=2)

        result = {"cases": []}
        # Поиск таблицы с результатами
        table = soup.find('table', id='b-cases')
        if not table:
            logger.warning(f"Таблица результатов не найдена для ИНН {inn}")
            return json.dumps({"cases": []}, ensure_ascii=False, indent=2)

        rows = table.find('tbody').find_all('tr')
        logger.info(f"Найдено строк в таблице для ИНН {inn}: {len(rows)}")

        for row in rows:
            case = {}
            # Номер дела
            num_case = row.find('a', class_='num_case')
            case['case_number'] = num_case.get_text(strip=True) if num_case else ''

            # Дата регистрации
            date = row.find('div', class_='bankruptcy')
            case['registration_date'] = date.find('span').get_text(strip=True) if date and date.find('span') else ''

            # Судья и инстанция
            court_cell = row.find('td', class_='court')
            if court_cell:
                judge = court_cell.find('div', class_='judge')
                case['judge'] = judge.get_text(strip=True) if judge else ''
                instance = court_cell.find_all('div')[-1]  # Последний div в td.court
                case['current_instance'] = instance.get_text(strip=True) if instance else ''

            # Истец
            plaintiff = row.find('td', class_='plaintiff').find('span', class_='js-rollover')
            case['plaintiff'] = plaintiff.get_text(strip=True) if plaintiff else ''

            # Ответчик
            respondent = row.find('td', class_='respondent').find('span', class_='js-rollover')
            case['respondent'] = respondent.get_text(strip=True) if respondent else ''

            # ИНН (из rolloverHtml)
            rollover = row.find('span', class_='js-rolloverHtml')
            if rollover:
                inn_span = rollover.find('span', class_='g-highlight')
                case['inn'] = inn_span.get_text(strip=True) if inn_span else ''

            result['cases'].append(case)

        logger.info(f"Данные для ИНН {inn} успешно получены")
        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as parse_error:
        logger.error(f"Ошибка при парсинге HTML-файла для ИНН {inn}: {str(parse_error)}")
        return json.dumps({"error": f"Ошибка парсинга HTML: {str(parse_error)}"}, ensure_ascii=False, indent=2)
    finally:
        # Удаление HTML-файла после парсинга
        try:
            if os.path.exists(html_file):
                os.remove(html_file)
                logger.info(f"HTML-файл {html_file} удален")
        except Exception as delete_error:
            logger.error(f"Ошибка при удалении HTML-файла для ИНН {inn}: {str(delete_error)}")