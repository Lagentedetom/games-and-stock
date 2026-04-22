#!/usr/bin/env python3
"""
fetch_tweet_stats.py — snapshot semanal de metricas de tweets @Games_and_Stock.

Lee data/tweets_log.csv, coge los tweet_ids publicados (status=published)
de los ultimos N dias, llama al endpoint batch GET /2/tweets de X API v2
pidiendo public_metrics + organic_metrics, y graba un snapshot en
data/tweet_stats.csv (una fila por tweet y por fecha de snapshot).

Pensado para correr en cron semanal (viernes) desde GitHub Actions, pero
tambien se puede ejecutar local:

    python scripts/fetch_tweet_stats.py [--days 30]

Variables de entorno (mismas que tweet.py):
    X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET

Sin dependencias externas: solo stdlib.
"""
import argparse
import base64
import csv
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(SCRIPT_DIR, '..')
LOG_PATH = os.path.join(ROOT_DIR, 'data', 'tweets_log.csv')
STATS_PATH = os.path.join(ROOT_DIR, 'data', 'tweet_stats.csv')

API_URL = "https://api.twitter.com/2/tweets"
TWEET_FIELDS = "public_metrics,non_public_metrics,organic_metrics,created_at,text"

STATS_COLUMNS = [
    'checked_at', 'tweet_id', 'created_at', 'age_days',
    'type', 'slot',
    'impressions', 'likes', 'retweets', 'replies', 'quotes', 'bookmarks',
    'url_clicks', 'profile_clicks', 'engagement_rate', 'text_preview',
]


# ─── OAuth 1.0a helpers (copiados del estilo de tweet.py) ─────────────────

def percent_encode(s):
    return quote(str(s), safe='')


def create_oauth_signature(method, url, params, consumer_secret, token_secret):
    sorted_params = '&'.join(
        f'{percent_encode(k)}={percent_encode(v)}'
        for k, v in sorted(params.items())
    )
    base_string = f'{method}&{percent_encode(url)}&{percent_encode(sorted_params)}'
    signing_key = f'{percent_encode(consumer_secret)}&{percent_encode(token_secret)}'
    signature = hmac.new(signing_key.encode('utf-8'), base_string.encode('utf-8'), hashlib.sha1).digest()
    return base64.b64encode(signature).decode('utf-8')


def oauth_get(url, query_params, api_key, api_secret, access_token, access_token_secret):
    """GET con OAuth 1.0a. Incluye los query_params en el signature base string."""
    oauth_params = {
        'oauth_consumer_key': api_key,
        'oauth_nonce': uuid.uuid4().hex,
        'oauth_signature_method': 'HMAC-SHA1',
        'oauth_timestamp': str(int(time.time())),
        'oauth_token': access_token,
        'oauth_version': '1.0',
    }
    # Para el signature base string hay que incluir TODOS los params (oauth + query).
    signing_params = {**oauth_params, **query_params}
    signature = create_oauth_signature('GET', url, signing_params, api_secret, access_token_secret)
    oauth_params['oauth_signature'] = signature

    auth_header = 'OAuth ' + ', '.join(
        f'{percent_encode(k)}="{percent_encode(v)}"'
        for k, v in sorted(oauth_params.items())
    )

    full_url = f"{url}?{urlencode(query_params)}"
    req = Request(full_url, method='GET')
    req.add_header('Authorization', auth_header)

    try:
        with urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode('utf-8'))
    except HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        print(f"ERROR X API {e.code}: {body[:400]}", file=sys.stderr)
        raise


# ─── Data loading ─────────────────────────────────────────────────────────

def load_published_tweets(days_back):
    if not os.path.exists(LOG_PATH):
        print(f"ERROR: no existe {LOG_PATH}", file=sys.stderr)
        sys.exit(1)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    tweets = []
    with open(LOG_PATH) as f:
        reader = csv.DictReader(f)
        for r in reader:
            tid = (r.get('tweet_id') or '').strip()
            if not tid:
                continue
            status = (r.get('status') or '').strip().lower()
            if status == 'test' or status.startswith('error'):
                continue
            try:
                dt = datetime.fromisoformat(r['datetime'].replace('Z', '+00:00'))
            except Exception:
                continue
            if dt < cutoff:
                continue
            tweets.append({
                'tweet_id': tid,
                'datetime': dt,
                'type': r.get('type', ''),
                'slot': r.get('slot', ''),
                'text': r.get('text', ''),
            })
    # Dedup (keep first occurrence — earliest log row for that id)
    seen, unique = set(), []
    for t in tweets:
        if t['tweet_id'] in seen:
            continue
        seen.add(t['tweet_id'])
        unique.append(t)
    return unique


def fetch_metrics(tweet_ids, api_key, api_secret, access_token, access_token_secret):
    results = []
    for i in range(0, len(tweet_ids), 100):
        chunk = tweet_ids[i:i+100]
        query = {'ids': ','.join(chunk), 'tweet.fields': TWEET_FIELDS}
        data = oauth_get(API_URL, query, api_key, api_secret, access_token, access_token_secret)
        results.extend(data.get('data', []) or [])
        for err in data.get('errors', []) or []:
            print(f"[warn] {err.get('resource_id', '?')}: {err.get('detail') or err.get('title')}", file=sys.stderr)
    return results


def build_rows(tweet_objs, meta_by_id, checked_at):
    rows = []
    for t in tweet_objs:
        pub = t.get('public_metrics') or {}
        org = t.get('organic_metrics') or {}

        impressions = org.get('impression_count') if org else None
        if impressions is None:
            impressions = pub.get('impression_count', 0)

        url_clicks = org.get('url_link_clicks') if org else None
        profile_clicks = org.get('user_profile_clicks') if org else None

        likes = pub.get('like_count', 0)
        retweets = pub.get('retweet_count', 0)
        replies = pub.get('reply_count', 0)
        quotes = pub.get('quote_count', 0)
        bookmarks = pub.get('bookmark_count', 0)

        engagement = likes + retweets + replies + quotes + bookmarks
        eng_rate = round(engagement / impressions, 4) if impressions else 0.0

        created_at = t.get('created_at', '')
        age_days = 0
        if created_at:
            try:
                dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                age_days = (checked_at - dt).days
            except Exception:
                pass

        meta = meta_by_id.get(t['id'], {})
        text_full = t.get('text') or meta.get('text', '')
        text_preview = text_full[:100].replace('\n', ' ').replace('\r', ' ')

        rows.append({
            'checked_at': checked_at.isoformat(),
            'tweet_id': t['id'],
            'created_at': created_at,
            'age_days': age_days,
            'type': meta.get('type', ''),
            'slot': meta.get('slot', ''),
            'impressions': impressions,
            'likes': likes,
            'retweets': retweets,
            'replies': replies,
            'quotes': quotes,
            'bookmarks': bookmarks,
            'url_clicks': url_clicks if url_clicks is not None else '',
            'profile_clicks': profile_clicks if profile_clicks is not None else '',
            'engagement_rate': eng_rate,
            'text_preview': text_preview,
        })
    rows.sort(key=lambda r: r.get('created_at', ''), reverse=True)
    return rows


def append_snapshot(rows):
    file_exists = os.path.exists(STATS_PATH)
    with open(STATS_PATH, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=STATS_COLUMNS)
        if not file_exists:
            writer.writeheader()
        for r in rows:
            writer.writerow(r)


def print_summary(rows):
    if not rows:
        print("\nNo tweets con metricas.")
        return
    total_impr = sum(r['impressions'] or 0 for r in rows)
    total_eng = sum(r['likes']+r['retweets']+r['replies']+r['quotes']+r['bookmarks'] for r in rows)
    total_clicks = sum(r['url_clicks'] for r in rows if isinstance(r['url_clicks'], int))
    total_profile = sum(r['profile_clicks'] for r in rows if isinstance(r['profile_clicks'], int))
    avg_eng_rate = sum(r['engagement_rate'] for r in rows) / len(rows)

    print(f"\n{'='*90}")
    print(f"📊 Snapshot Games & Stock — {len(rows)} tweets")
    print(f"{'='*90}")
    print(f"Total impresiones     : {total_impr:,}")
    print(f"Total engagement      : {total_eng} (likes+RT+replies+quotes+bookmarks)")
    print(f"Total clics enlace    : {total_clicks}")
    print(f"Total clics perfil    : {total_profile}")
    print(f"Eng. rate promedio    : {avg_eng_rate:.2%}")

    top = sorted(rows, key=lambda r: r['impressions'] or 0, reverse=True)[:5]
    print(f"\n🏆 Top 5 por impresiones:")
    for i, r in enumerate(top, 1):
        print(f"  {i}. [{r['impressions']:>5} impr] {r['slot']:<8} {r['type']:<22} — {r['text_preview'][:60]}")

    # Top by engagement rate (min 20 impressions to avoid noise)
    sig = [r for r in rows if (r['impressions'] or 0) >= 20]
    if sig:
        top_eng = sorted(sig, key=lambda r: r['engagement_rate'], reverse=True)[:5]
        print(f"\n🔥 Top 5 por engagement rate (min 20 impr):")
        for i, r in enumerate(top_eng, 1):
            print(f"  {i}. [{r['engagement_rate']:.1%}  {r['impressions']:>4} impr] {r['type']:<22} — {r['text_preview'][:60]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=30, help='Lookback window in days (default 30)')
    parser.add_argument('--no-append', action='store_true', help="Don't write to CSV, only print")
    args = parser.parse_args()

    required = ['X_API_KEY', 'X_API_SECRET', 'X_ACCESS_TOKEN', 'X_ACCESS_TOKEN_SECRET']
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"ERROR: missing env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(3)

    tweets = load_published_tweets(args.days)
    print(f"Found {len(tweets)} published tweets in the last {args.days} days")
    if not tweets:
        return

    objs = fetch_metrics(
        [t['tweet_id'] for t in tweets],
        os.environ['X_API_KEY'], os.environ['X_API_SECRET'],
        os.environ['X_ACCESS_TOKEN'], os.environ['X_ACCESS_TOKEN_SECRET'],
    )
    print(f"Got metrics for {len(objs)} tweets from X API")

    meta_by_id = {t['tweet_id']: t for t in tweets}
    checked_at = datetime.now(timezone.utc)
    rows = build_rows(objs, meta_by_id, checked_at)

    if not args.no_append:
        append_snapshot(rows)
        print(f"✅ Snapshot grabado en {STATS_PATH}")

    print_summary(rows)


if __name__ == '__main__':
    main()
