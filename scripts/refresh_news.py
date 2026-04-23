#!/usr/bin/env python3
"""
refresh_news.py — mantiene las noticias del dashboard frescas.

Cada noticia en games_data.json tiene 3 posibles lifecycles:
- 'evergreen'   : contexto estable, no caduca
- 'pre_event'   : anuncia un evento futuro (con event_date). Si el evento ya
                  pasó, se DEGRADA (se oculta o se transforma).
- 'post_event'  : análisis después de un evento. Se genera automáticamente
                  cuando un 'pre_event' caduca (si hay datos suficientes), o
                  cuando un juego de la watchlist cruza su release date.

Este script, ejecutado a diario desde update-dashboard.yml:
  1. Revisa cada 'pre_event' con event_date < hoy y NO relevante → oculta.
  2. Para juegos de la watchlist (tier1/2/3) cuya release_date ya pasó y no
     están representados en las noticias como post_event, añade una noticia
     post_event auto-generada con el delta del ticker desde el lanzamiento
     (usando price_history si tenemos el precio de esa fecha).
  3. Refresca el campo `title`/`body` de las noticias post_event existentes
     para que el "hace N días" esté siempre al día.

El JS del dashboard ya filtra las pre_event caducadas en el cliente, pero
este script las LIMPIA del JSON para no acumular basura y genera contenido
nuevo post-launch de forma automática. Con esto, la sección de noticias no
requiere mantenimiento manual.
"""
import json
import os
import re
from datetime import datetime, timezone, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(SCRIPT_DIR, '..')
DATA_PATH = os.path.join(ROOT_DIR, 'data', 'games_data.json')

# ───── helpers ─────

MONTHS_ES = {
    'ene':1, 'feb':2, 'mar':3, 'abr':4, 'may':5, 'jun':6,
    'jul':7, 'ago':8, 'sep':9, 'oct':10, 'nov':11, 'dic':12,
}
MONTHS_EN = {
    'jan':1, 'feb':2, 'mar':3, 'apr':4, 'may':5, 'jun':6,
    'jul':7, 'aug':8, 'sep':9, 'oct':10, 'nov':11, 'dec':12,
}


def parse_release_date(s):
    """Parse strings like '17 Abr 2026' (ES) or 'Apr 17, 2026' (EN). Returns date or None."""
    if not s or not isinstance(s, str):
        return None
    # ES: "17 Abr 2026"
    m = re.match(r'^(\d{1,2})\s+([A-Za-zéí]+)\s+(\d{4})$', s.strip())
    if m:
        day, mkey, year = int(m.group(1)), m.group(2)[:3].lower(), int(m.group(3))
        month = MONTHS_ES.get(mkey) or MONTHS_EN.get(mkey)
        if month:
            try:
                return datetime(year, month, day).date()
            except ValueError:
                return None
    # EN: "Apr 17, 2026"
    m = re.match(r'^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$', s.strip())
    if m:
        mkey, day, year = m.group(1)[:3].lower(), int(m.group(2)), int(m.group(3))
        month = MONTHS_EN.get(mkey)
        if month:
            try:
                return datetime(year, month, day).date()
            except ValueError:
                return None
    return None


def price_on_or_after(series, target_date):
    """Find the first price entry on/after target_date. Returns price or None."""
    if not series:
        return None
    target_iso = target_date.isoformat() if hasattr(target_date, 'isoformat') else str(target_date)
    for entry in series:
        if entry.get('date', '') >= target_iso:
            return entry.get('price')
    return None


def latest_price(series):
    if not series:
        return None
    return series[-1].get('price')


def format_date_es(d):
    months = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic']
    return f"{d.day} {months[d.month-1]} {d.year}"


def format_date_en(d):
    months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    return f"{months[d.month-1]} {d.day}, {d.year}"


# ───── transformers ─────

def purge_stale_pre_events(news_list, today, stats):
    """Remove pre_event news whose event_date has passed by > grace_days."""
    GRACE_DAYS = 1  # drop the day after the event
    kept = []
    for n in news_list:
        if n.get('lifecycle') != 'pre_event':
            kept.append(n)
            continue
        ed_str = n.get('event_date')
        if not ed_str:
            kept.append(n)
            continue
        try:
            ed = datetime.fromisoformat(ed_str).date()
        except ValueError:
            kept.append(n)
            continue
        if (today - ed).days > GRACE_DAYS:
            stats['purged_stale'] += 1
            continue
        kept.append(n)
    return kept


def refresh_post_event_titles(news_list, today, stats, lang='es'):
    """Update 'hace N días' / 'N days ago' counters in post_event news."""
    for n in news_list:
        if n.get('lifecycle') != 'post_event':
            continue
        ed_str = n.get('event_date')
        if not ed_str:
            continue
        try:
            ed = datetime.fromisoformat(ed_str).date()
        except ValueError:
            continue
        days = (today - ed).days
        if days < 0:
            continue
        # Rewrite the "hace N días" / "N days ago" phrase if present in title.
        if lang == 'es':
            new_title = re.sub(r'hace \d+ d[ií]as?', f'hace {days} día{"s" if days != 1 else ""}', n.get('title', ''), flags=re.IGNORECASE)
        else:
            new_title = re.sub(r'\d+ days? ago', f'{days} day{"s" if days != 1 else ""} ago', n.get('title', ''), flags=re.IGNORECASE)
        if new_title != n.get('title'):
            n['title'] = new_title
            stats['title_refreshed'] += 1


def auto_generate_post_launch_news(data, today, stats):
    """
    For each game in tier1/2/3 whose release date has passed in the last 14 days,
    if there's no post_event news for that game yet, generate one automatically.

    Requires price_history for the ticker to compute a delta; falls back to
    "precio actual X, datos hist\u00f3ricos no disponibles" if missing.
    """
    history = data.get('price_history', {}) or {}
    analysts_by_ticker = {a['ticker']: a for a in (data.get('analysts') or [])}

    for lang in ('es', 'en'):
        news_list = data['news'].get(lang, [])
        # Identify existing post_event news by ticker + approximate date
        existing_keys = {
            (n.get('ticker', ''), n.get('event_date', ''))
            for n in news_list
            if n.get('lifecycle') == 'post_event'
        }

        for tier in ('tier1', 'tier2', 'tier3'):
            for g in (data.get('games', {}).get(tier) or []):
                ticker = g.get('ticker', '')
                if not ticker:
                    continue
                rel_raw = g.get('release')
                rel_str = rel_raw[lang] if isinstance(rel_raw, dict) else rel_raw
                rel_date = parse_release_date(rel_str)
                if rel_date is None:
                    continue
                days_since = (today - rel_date).days
                if days_since < 0 or days_since > 14:
                    continue  # not launched yet, or older than 2 weeks (we trust manual post-event)

                key = (ticker, rel_date.isoformat())
                if key in existing_keys:
                    continue

                # Compute delta if possible
                launch_price = price_on_or_after(history.get(ticker, []), rel_date)
                now_price = latest_price(history.get(ticker, [])) or analysts_by_ticker.get(ticker, {}).get('price')
                # Normalize now_price to float if formatted
                now_price_float = None
                if isinstance(now_price, (int, float)):
                    now_price_float = float(now_price)
                elif isinstance(now_price, str):
                    m = re.search(r'([\d.]+)', now_price)
                    if m:
                        try:
                            now_price_float = float(m.group(1))
                        except ValueError:
                            pass

                # Name, company
                name = g.get('name', '')
                company = g.get('company', '')

                if launch_price and now_price_float:
                    pct = round((now_price_float / launch_price - 1) * 100, 2)
                    sign = '+' if pct >= 0 else ''
                    if lang == 'es':
                        title = f'{name} lanzó hace {days_since} día{"s" if days_since != 1 else ""}'
                        body = (
                            f'{company}. Precio de ${ticker} al lanzamiento: ~${launch_price:.2f}. '
                            f'Hoy: ~${now_price_float:.2f} ({sign}{pct}%).'
                        )
                    else:
                        title = f'{name} launched {days_since} day{"s" if days_since != 1 else ""} ago'
                        body = (
                            f'{company}. ${ticker} price at launch: ~${launch_price:.2f}. '
                            f'Today: ~${now_price_float:.2f} ({sign}{pct}%).'
                        )
                else:
                    if lang == 'es':
                        title = f'{name} lanzó hace {days_since} día{"s" if days_since != 1 else ""}'
                        body = f'{company}. Pendiente de datos históricos para calcular el delta de ${ticker}.'
                    else:
                        title = f'{name} launched {days_since} day{"s" if days_since != 1 else ""} ago'
                        body = f'{company}. Historical price data pending for ${ticker} delta.'

                news_list.insert(0, {
                    'ticker': ticker,
                    'category': 'post_launch',
                    'color': 'blue',
                    'lifecycle': 'post_event',
                    'event_date': rel_date.isoformat(),
                    'date': rel_date.isoformat(),
                    'source': 'Analysis · Games & Stock',
                    'url': '',
                    'title': title,
                    'body': body,
                })
                stats['auto_generated'] += 1
                print(f'  + auto-generated post_event for {name} ({ticker}, {lang})')


# ───── main ─────

def main():
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    today = datetime.now(timezone.utc).date()
    stats = {'purged_stale': 0, 'title_refreshed': 0, 'auto_generated': 0}

    for lang in ('es', 'en'):
        news_list = data.get('news', {}).get(lang, [])
        news_list = purge_stale_pre_events(news_list, today, stats)
        refresh_post_event_titles(news_list, today, stats, lang)
        data['news'][lang] = news_list

    auto_generate_post_launch_news(data, today, stats)

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"refresh_news.py done. Stats: {stats}")


if __name__ == '__main__':
    main()
