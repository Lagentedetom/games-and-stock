#!/usr/bin/env python3
"""
fetch_ga_stats.py — snapshot semanal de trafico del dashboard via GA4 Data API.

Consulta la propiedad GA4 del dashboard Games & Stock y graba un snapshot en
data/ga_stats.csv con metricas agregadas + breakdown por idioma y fuente.

Pensado para correr el viernes junto a fetch_tweet_stats.py.

Variables de entorno:
    GA_PROPERTY_ID            — ID numerico de la propiedad GA4 (NO el measurement ID)
    GA_SERVICE_ACCOUNT_JSON   — contenido JSON de la service account (como string)

Si no estan las dos variables, el script sale con exit 0 (no-op) para que el
workflow no falle si aun no se ha configurado.

Dependencies (instaladas en el workflow):
    google-analytics-data
"""
import argparse
import csv
import json
import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(SCRIPT_DIR, '..')
STATS_PATH = os.path.join(ROOT_DIR, 'data', 'ga_stats.csv')

STATS_COLUMNS = [
    'checked_at',
    'window_start',
    'window_end',
    'scope',           # 'total', 'es', 'en', or source-label like 'src:twitter'
    'pageviews',
    'sessions',
    'users',
    'new_users',
    'avg_engagement_time_sec',
]


def _setup_credentials():
    """
    Write the service account JSON from env var to a temp file and set
    GOOGLE_APPLICATION_CREDENTIALS so the google-analytics-data lib picks it up.
    """
    sa_json = os.environ.get('GA_SERVICE_ACCOUNT_JSON', '').strip()
    if not sa_json:
        return False
    # Validate it parses
    try:
        json.loads(sa_json)
    except json.JSONDecodeError as e:
        print(f"ERROR: GA_SERVICE_ACCOUNT_JSON is not valid JSON: {e}", file=sys.stderr)
        sys.exit(4)

    tmp = tempfile.NamedTemporaryFile(
        mode='w', suffix='.json', prefix='ga_sa_', delete=False
    )
    tmp.write(sa_json)
    tmp.close()
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = tmp.name
    return True


def _run_report(client, property_id, start_date, end_date, dimensions, metrics,
                dimension_filter=None, limit=10):
    """Thin wrapper around runReport."""
    from google.analytics.data_v1beta.types import (
        DateRange, Dimension, Metric, RunReportRequest, FilterExpression,
    )
    req = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        limit=limit,
    )
    if dimension_filter is not None:
        req.dimension_filter = dimension_filter
    return client.run_report(req)


def _row_from_response(resp, scope, checked_at, start_date, end_date):
    """Take a GA4 RunReportResponse aggregating a single scope, return a CSV row dict."""
    # Totals are accessible via resp.rows[0] when no dimensions are set.
    if not resp.rows:
        return {
            'checked_at': checked_at.isoformat(),
            'window_start': start_date,
            'window_end': end_date,
            'scope': scope,
            'pageviews': 0,
            'sessions': 0,
            'users': 0,
            'new_users': 0,
            'avg_engagement_time_sec': 0.0,
        }
    row = resp.rows[0]
    mv = [m.value for m in row.metric_values]
    return {
        'checked_at': checked_at.isoformat(),
        'window_start': start_date,
        'window_end': end_date,
        'scope': scope,
        'pageviews': int(float(mv[0] or 0)),
        'sessions': int(float(mv[1] or 0)),
        'users': int(float(mv[2] or 0)),
        'new_users': int(float(mv[3] or 0)),
        'avg_engagement_time_sec': round(float(mv[4] or 0), 1),
    }


def fetch_snapshot(property_id, start_date, end_date):
    """
    Run the GA4 queries and return a list of CSV rows covering:
    - total
    - es (pagePath NOT starting with /en/)
    - en (pagePath starting with /en/)
    - top 5 sources/mediums
    """
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        Filter, FilterExpression,
    )
    client = BetaAnalyticsDataClient()
    checked_at = datetime.now(timezone.utc)

    metrics = [
        'screenPageViews',
        'sessions',
        'totalUsers',
        'newUsers',
        'averageSessionDuration',
    ]

    rows = []

    # 1. TOTAL
    resp = _run_report(client, property_id, start_date, end_date, [], metrics, limit=1)
    rows.append(_row_from_response(resp, 'total', checked_at, start_date, end_date))

    # 2. EN subsection (pagePath starts with /en/)
    en_filter = FilterExpression(filter=Filter(
        field_name='pagePath',
        string_filter=Filter.StringFilter(
            match_type=Filter.StringFilter.MatchType.BEGINS_WITH,
            value='/en/',
        ),
    ))
    resp_en = _run_report(client, property_id, start_date, end_date, [], metrics,
                          dimension_filter=en_filter, limit=1)
    rows.append(_row_from_response(resp_en, 'en', checked_at, start_date, end_date))

    # 3. ES subsection (NOT beginning with /en/)
    es_filter = FilterExpression(
        not_expression=FilterExpression(filter=Filter(
            field_name='pagePath',
            string_filter=Filter.StringFilter(
                match_type=Filter.StringFilter.MatchType.BEGINS_WITH,
                value='/en/',
            ),
        )),
    )
    resp_es = _run_report(client, property_id, start_date, end_date, [], metrics,
                          dimension_filter=es_filter, limit=1)
    rows.append(_row_from_response(resp_es, 'es', checked_at, start_date, end_date))

    # 4. Top sources (sessionSource dimension)
    from google.analytics.data_v1beta.types import (
        Dimension, Metric, DateRange, RunReportRequest,
    )
    req = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name='sessionSource')],
        metrics=[Metric(name=m) for m in metrics],
        limit=10,
    )
    resp_src = client.run_report(req)
    for r in resp_src.rows:
        source = r.dimension_values[0].value or '(none)'
        mv = [m.value for m in r.metric_values]
        rows.append({
            'checked_at': checked_at.isoformat(),
            'window_start': start_date,
            'window_end': end_date,
            'scope': f'src:{source}',
            'pageviews': int(float(mv[0] or 0)),
            'sessions': int(float(mv[1] or 0)),
            'users': int(float(mv[2] or 0)),
            'new_users': int(float(mv[3] or 0)),
            'avg_engagement_time_sec': round(float(mv[4] or 0), 1),
        })

    return rows


def append_snapshot(rows):
    file_exists = os.path.exists(STATS_PATH)
    with open(STATS_PATH, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=STATS_COLUMNS)
        if not file_exists:
            writer.writeheader()
        for r in rows:
            writer.writerow(r)


def print_summary(rows, start_date, end_date):
    if not rows:
        print("No GA data.")
        return

    print(f"\n{'='*80}")
    print(f"📊 Google Analytics snapshot  {start_date} → {end_date}")
    print(f"{'='*80}")
    totals = next((r for r in rows if r['scope'] == 'total'), None)
    es = next((r for r in rows if r['scope'] == 'es'), None)
    en = next((r for r in rows if r['scope'] == 'en'), None)
    if totals:
        print(f"TOTAL: {totals['pageviews']} pageviews · {totals['sessions']} sesiones · "
              f"{totals['users']} usuarios ({totals['new_users']} nuevos) · "
              f"engagement medio {totals['avg_engagement_time_sec']}s")
    if es:
        print(f"  ES:  {es['pageviews']} pv · {es['sessions']} s · {es['users']} u")
    if en:
        print(f"  EN:  {en['pageviews']} pv · {en['sessions']} s · {en['users']} u")

    sources = [r for r in rows if r['scope'].startswith('src:')]
    if sources:
        print(f"\n🔗 Top fuentes (sessionSource):")
        for r in sorted(sources, key=lambda x: -x['sessions'])[:8]:
            print(f"  {r['scope'].replace('src:', ''):<25} {r['sessions']:>4} sesiones · "
                  f"{r['users']:>4} usuarios · {r['avg_engagement_time_sec']:>5}s avg")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=7, help='Ventana en dias (default 7)')
    parser.add_argument('--no-append', action='store_true')
    args = parser.parse_args()

    if not _setup_credentials():
        print("GA_SERVICE_ACCOUNT_JSON no configurado — skip GA stats.", file=sys.stderr)
        return

    property_id = os.environ.get('GA_PROPERTY_ID', '').strip()
    if not property_id:
        print("GA_PROPERTY_ID no configurado — skip GA stats.", file=sys.stderr)
        return

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=args.days - 1)
    start_str = start.isoformat()
    end_str = end.isoformat()

    print(f"Querying GA4 property {property_id} from {start_str} to {end_str}...")
    rows = fetch_snapshot(property_id, start_str, end_str)
    print(f"Got {len(rows)} rows")

    if not args.no_append:
        append_snapshot(rows)
        print(f"✅ Snapshot grabado en {STATS_PATH}")

    print_summary(rows, start_str, end_str)


if __name__ == '__main__':
    main()
