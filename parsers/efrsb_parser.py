import asyncio
import logging
import re
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

async def get_info_efrsb(inn: str, cdp_endpoint="http://localhost:9222") -> str:
    """Получение данных с ЕФРСБ через сохранение и парсинг HTML-файла."""
    url = f"https://bankrot.fedresurs.ru/bankrupts?searchString={inn}"
    html_file = f"page_{inn}.html"
    async with async_playwright() as p:
        try:
            logger.info(f"Подключение к CDP по адресу: {cdp_endpoint}")
            browser = await p.chromium.connect_over_cdp(cdp_endpoint)
            page = await browser.contexts[0].new_page()

            try:
                logger.info(f"Загружаю страницу ЕФРСБ: {url}")
                await page.goto(url, wait_until="networkidle")
                # Ожидание 3 секунды для рендеринга Angular-приложения
                await page.wait_for_timeout(3000)

            except PlaywrightError as e:
                logger.error(f"Ошибка при загрузке страницы для ИНН {inn}: {str(e)}")
                return json.dumps({"error": f"Ошибка загрузки страницы: {str(e)}"}, ensure_ascii=False, indent=2)
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

        no_result = soup.find('div', class_='no-result-msg__header')
        if no_result and not soup.find('div', class_='u-card-result'):
            logger.info(f"Данные ЕФРСБ для ИНН {inn}: Ничего не найдено")
            return json.dumps({"legal_entities": [], "individuals": []}, ensure_ascii=False, indent=2)

        result = {"legal_entities": [], "individuals": []}
        cards = soup.find_all('div', class_='u-card-result')
        logger.info(f"Найдено карточек для ИНН {inn}: {len(cards)}")

        if not cards:
            logger.warning(f"Карточки не найдены для ИНН {inn}")
            return json.dumps({"legal_entities": [], "individuals": []}, ensure_ascii=False, indent=2)

        for card in cards:
            entry = {}
            name = card.find('div', class_='u-card-result__name')
            entry['name' if 'ОГРН' in card.get_text() else 'full_name'] = name.get_text(
                strip=True) if name else ''
            address = card.find('div', class_='u-card-result__value_adr')
            entry['address'] = address.get_text(strip=True) if address else ''
            inn_elem = card.find('span', class_='u-card-result__point', string='ИНН')
            if inn_elem:
                inn_value = inn_elem.find_next('span', class_='u-card-result__value')
                entry['inn'] = inn_value.get_text(strip=True) if inn_value else ''
            if 'ОГРН' in card.get_text():
                ogrn_elem = card.find('span', class_='u-card-result__point', string='ОГРН')
                if ogrn_elem:
                    ogrn_value = ogrn_elem.find_next('span', class_='u-card-result__value')
                    entry['ogrn'] = ogrn_value.get_text(strip=True) if ogrn_value else ''
                result['legal_entities'].append(entry)
            else:
                snils_elem = card.find('span', class_='u-card-result__point', string='СНИЛС')
                if snils_elem:
                    snils_value = snils_elem.find_next('span', class_='u-card-result__value')
                    entry['snils'] = snils_value.get_text(strip=True) if snils_value else ''
                result['individuals'].append(entry)
            status = card.find('div', class_='u-card-result__value_item-property')
            entry['status'] = status.get_text(strip=True) if status else ''
            status_date = card.find('div', class_='status-date')
            entry['status_date'] = status_date.get_text(strip=True) if status_date else ''
            court_case = card.find('div', class_='u-card-result__court-case')
            if court_case:
                court_case_value = court_case.find('div', class_='u-card-result__value')
                entry['court_case_number'] = court_case_value.get_text(strip=True) if court_case_value else ''
            manager = card.find('div', class_='u-card-result__manager')
            if manager:
                manager_value = manager.find('div', class_='u-card-result__value')
                entry['arbitration_manager'] = manager_value.get_text(strip=True) if manager_value else ''

        logger.info(f"Данные ЕФРСБ для ИНН {inn} успешно получены")
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