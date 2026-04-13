#!/usr/bin/env python3
"""
Reads games_data.json and updates the date and price fields
in the existing HTML dashboards (ES and EN).
This script does targeted replacements to keep the handcrafted HTML intact.
"""

import json
import os
import re
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(SCRIPT_DIR, '..')
DATA_PATH = os.path.join(ROOT_DIR, 'data', 'games_data.json')
ES_PATH = os.path.join(ROOT_DIR, 'index.html')
EN_PATH = os.path.join(ROOT_DIR, 'en', 'index.html')

MONTHS_ES = {
    1: 'Ene', 2: 'Feb', 3: 'Mar', 4: 'Abr', 5: 'May', 6: 'Jun',
    7: 'Jul', 8: 'Ago', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dic'
}

MONTHS_EN = {
    1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'May', 6: 'Jun',
    7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dec'
}


def load_data():
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def format_date_es(date_str):
    """Convert 2026-04-13 to '13 Abr 2026'"""
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    return f"{dt.day} {MONTHS_ES[dt.month]} {dt.year}"


def format_date_en(date_str):
    """Convert 2026-04-13 to 'Apr 13, 2026'"""
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    return f"{MONTHS_EN[dt.month]} {dt.day}, {dt.year}"


def update_html(html_content, data, lang='es'):
    """Update dates and prices in the HTML content."""
    date_str = data['last_updated']

    if lang == 'es':
        formatted_date = format_date_es(date_str)
        # Update header date
        html_content = re.sub(
            r'Actualizado: \d+ \w+ \d{4}',
            f'Actualizado: {formatted_date}',
            html_content
        )
        # Update section dates
        html_content = re.sub(
            r'(Opinion de Analistas|Noticias Clave del Sector) &mdash; \d+ \w+ \d{4}',
            lambda m: f'{m.group(1)} &mdash; {formatted_date}',
            html_content
        )
        # Update footer date
        html_content = re.sub(
            r'Datos de \d+ \w+ \d{4}',
            f'Datos de {formatted_date}',
            html_content
        )
    else:
        formatted_date = format_date_en(date_str)
        html_content = re.sub(
            r'Updated: \w+ \d+, \d{4}',
            f'Updated: {formatted_date}',
            html_content
        )
        html_content = re.sub(
            r'(Analyst Opinions|Key Sector News) &mdash; \w+ \d+, \d{4}',
            lambda m: f'{m.group(1)} &mdash; {formatted_date}',
            html_content
        )
        html_content = re.sub(
            r'Data as of \w+ \d+, \d{4}',
            f'Data as of {formatted_date}',
            html_content
        )

    # Update stock prices in the analyst table
    for analyst in data.get('analysts', []):
        ticker = analyst['ticker']
        price = analyst['price']
        # Match the price cell after the ticker
        pattern = rf'(<span class="ticker">{re.escape(ticker)}</span></td>.*?<td>)(~\$[\d.,]+(?:\s*<span[^>]*>[^<]*</span>)?|~[\d.,]+ PLN|Muy golpeada|Heavily hit)'
        html_content = re.sub(pattern, lambda m: m.group(1) + price, html_content, flags=re.DOTALL)

    return html_content


def main():
    data = load_data()
    print(f"Loaded data, last updated: {data['last_updated']}")

    # Update Spanish dashboard
    with open(ES_PATH, 'r', encoding='utf-8') as f:
        es_html = f.read()
    es_html = update_html(es_html, data, lang='es')
    with open(ES_PATH, 'w', encoding='utf-8') as f:
        f.write(es_html)
    print(f"Updated: {ES_PATH}")

    # Update English dashboard
    with open(EN_PATH, 'r', encoding='utf-8') as f:
        en_html = f.read()
    en_html = update_html(en_html, data, lang='en')
    with open(EN_PATH, 'w', encoding='utf-8') as f:
        f.write(en_html)
    print(f"Updated: {EN_PATH}")

    print("Done! Both dashboards updated.")


if __name__ == '__main__':
    main()
