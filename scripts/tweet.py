#!/usr/bin/env python3
"""
Generates and publishes tweets for @Games_and_Stock based on dashboard data.
Reads games_data.json, selects content type based on day/time slot,
generates a tweet, publishes via X API v2, and logs to tweets_log.csv.

Usage:
  python tweet.py --slot morning|midday|evening|weekend
  python tweet.py --test  (generates but doesn't publish)
"""

import json
import os
import csv
import hashlib
import random
import argparse
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import quote
import hmac
import base64
import time
import uuid

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(SCRIPT_DIR, '..')
DATA_PATH = os.path.join(ROOT_DIR, 'data', 'games_data.json')
LOG_PATH = os.path.join(ROOT_DIR, 'data', 'tweets_log.csv')

# ─── X API Authentication ───────────────────────────────────────────────

def get_env(key):
    val = os.environ.get(key)
    if not val:
        raise ValueError(f"Missing environment variable: {key}")
    return val


def percent_encode(s):
    return quote(str(s), safe='')


def create_oauth_signature(method, url, params, consumer_secret, token_secret):
    sorted_params = '&'.join(
        f'{percent_encode(k)}={percent_encode(v)}'
        for k, v in sorted(params.items())
    )
    base_string = f'{method}&{percent_encode(url)}&{percent_encode(sorted_params)}'
    signing_key = f'{percent_encode(consumer_secret)}&{percent_encode(token_secret)}'
    signature = hmac.new(
        signing_key.encode('utf-8'),
        base_string.encode('utf-8'),
        hashlib.sha1
    ).digest()
    return base64.b64encode(signature).decode('utf-8')


def post_tweet(text):
    """Post a tweet using X API v2 with OAuth 1.0a."""
    api_key = get_env('X_API_KEY')
    api_secret = get_env('X_API_SECRET')
    access_token = get_env('X_ACCESS_TOKEN')
    access_token_secret = get_env('X_ACCESS_TOKEN_SECRET')

    url = 'https://api.x.com/2/tweets'
    method = 'POST'

    oauth_params = {
        'oauth_consumer_key': api_key,
        'oauth_nonce': uuid.uuid4().hex,
        'oauth_signature_method': 'HMAC-SHA1',
        'oauth_timestamp': str(int(time.time())),
        'oauth_token': access_token,
        'oauth_version': '1.0',
    }

    signature = create_oauth_signature(method, url, oauth_params, api_secret, access_token_secret)
    oauth_params['oauth_signature'] = signature

    auth_header = 'OAuth ' + ', '.join(
        f'{percent_encode(k)}="{percent_encode(v)}"'
        for k, v in sorted(oauth_params.items())
    )

    body = json.dumps({'text': text}).encode('utf-8')
    req = Request(url, data=body, method='POST')
    req.add_header('Authorization', auth_header)
    req.add_header('Content-Type', 'application/json')

    response = urlopen(req)
    result = json.loads(response.read().decode('utf-8'))
    return result


# ─── Tweet Generation ────────────────────────────────────────────────────

def load_data():
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_recent_tweets(max_days=7):
    """Load recent tweets to avoid repetition."""
    recent = []
    if not os.path.exists(LOG_PATH):
        return recent
    with open(LOG_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            recent.append(row)
    return recent[-30:]


def get_tweet_type(slot, weekday):
    """Determine tweet type based on slot and day of week."""
    if slot == 'weekend':
        return random.choice(['gaming_casual', 'week_preview'])

    schedule = {
        'morning': ['market_data', 'investment_signal', 'market_data', 'investment_signal', 'weekly_recap'],
        'midday': ['game_analysis', 'sector_context', 'game_comparison', 'game_analysis', 'gaming_fact'],
        'evening': ['engagement', 'dashboard_highlight', 'poll', 'dashboard_highlight', 'weekend_question'],
    }

    types = schedule.get(slot, ['market_data'])
    return types[weekday] if weekday < len(types) else types[0]


def generate_market_data(data):
    """Generate a tweet about a specific ticker/signal."""
    analysts = data.get('analysts', [])
    pick = random.choice([a for a in analysts if a.get('upside_class') == 'green'] or analysts)
    ticker = pick['ticker']
    rating = pick['rating']
    price = pick['price']
    catalyst = pick['catalyst']['en']

    templates = [
        f"${ticker} — {rating}\n\nCurrent: {price}\nKey catalyst: {catalyst}\n\nFull analysis on our dashboard.\n\n#Gaming #Stocks #Investment",
        f"Analyst consensus on ${ticker}: {rating}\n\nPrice: {price}\nWhat's driving it: {catalyst}\n\nMore data at Games & Stock dashboard.\n\n#GameInvesting #StockMarket",
        f"${ticker} update:\nRating: {rating}\nPrice: {price}\n\n{catalyst}\n\nTrack all gaming stocks on our dashboard.\n\n#GamingStocks #{ticker}",
    ]
    return random.choice(templates)


def generate_investment_signal(data):
    """Generate a tweet about investment signals from the dashboard."""
    tier1 = data['games']['tier1']
    game = random.choice(tier1)
    name = game['name']
    ticker = game['ticker']
    signal = game['signal']['en']
    score = game.get('score', '?')
    desc = game['description']['en']

    short_desc = desc[:100] + '...' if len(desc) > 100 else desc

    templates = [
        f"{name} — Signal: {signal}\n\nSignal Score: {score}/100\n${ticker}\n\n{short_desc}\n\n#Gaming #Investing",
        f"Our Signal Score for {name}: {score}/100 ({signal})\n\nTicker: ${ticker}\n{short_desc}\n\nFull breakdown on our dashboard.\n\n#GamingStocks",
    ]
    return random.choice(templates)


def generate_game_analysis(data):
    """Generate a tweet analyzing a specific game's stock impact."""
    all_games = data['games']['tier1'] + data['games']['tier2']
    game = random.choice(all_games)
    name = game['name']
    ticker = game['ticker']
    company = game['company']
    signal = game['signal']['en']

    templates = [
        f"{name} by {company}\n\nStock signal: {signal}\nTicker: ${ticker}\n\nHow will this launch affect the stock? We track it on our dashboard.\n\n#GameAnalysis #Stocks",
        f"Tracking: {name} ({company})\n\nOur signal: {signal} | ${ticker}\n\nWe analyze the correlation between game launches and stock movements.\n\n#GamingInvestor",
    ]
    return random.choice(templates)


def generate_sector_context(data):
    """Generate a tweet about gaming sector trends."""
    kpis = data['kpis']
    corr = data['correlations'][0]

    templates = [
        f"Did you know?\n\nThe correlation between sustained Google Trends hype and pre-launch stock movement is r = {corr['value']}.\n\nConsistent interest predicts stock gains better than peak hype.\n\nData from 6 major launches.\n\n#GamingStocks #DataDriven",
        f"Gaming stocks tracker:\n\n{kpis['games_watchlist']} games monitored\nBest upside: {kpis['best_upside']} ({kpis['best_upside_note']})\nTop correlation: r = {kpis['top_correlation']}\n\nUpdated daily on our dashboard.\n\n#GamingIndustry #StockMarket",
        f"Historical insight:\n\nBest case: {kpis['historical_max']} ({kpis['historical_max_note']})\nWorst case: {kpis['worst_crash']} ({kpis['worst_crash_note']})\n\nThe gaming-stock connection is real — but timing matters.\n\n#Investing #Gaming",
    ]
    return random.choice(templates)


def generate_engagement(data):
    """Generate an engagement tweet (question/poll)."""
    templates = [
        "Which game launch will impact stocks the most in 2026?\n\nA) GTA VI ($TTWO)\nB) Zelda OoT Remake ($NTDOY)\nC) Silent Hill Townfall ($KNAMF)\nD) Pragmata ($CCOEY)\n\nReply with your pick!\n\n#GamingStocks #Poll",
        "Hot take: GTA VI will move $TTWO more than any single game has moved a stock in the last 10 years.\n\nAgree or disagree?\n\n#GTAVI #TTWO #GamingInvestor",
        "What's your gaming stock strategy?\n\n1. Buy pre-launch, sell at release\n2. Buy post-launch dip\n3. Hold long term\n4. Avoid gaming stocks entirely\n\nLet us know!\n\n#StockStrategy #Gaming",
        "Quick poll: Do you check Google Trends before investing in gaming stocks?\n\nOur data shows a 0.749 correlation between Trends consistency and pre-launch stock gains.\n\nThoughts?\n\n#DataDriven #Investing",
    ]
    return random.choice(templates)


def generate_dashboard_highlight(data):
    """Generate a tweet highlighting a specific dashboard feature."""
    templates = [
        f"Games & Stock Dashboard — updated daily\n\n{data['kpis']['games_watchlist']} games tracked\n7 companies analyzed\nSignal Scores based on Google Trends + timing + acceleration\n\nCheck it out (link in bio)\n\n#GamingStocks #Dashboard",
        "Our Signal Score formula:\n\n40% — Google Trends level\n25% — Time window to launch\n20% — Trend acceleration\n15% — Consistency\n\n0-100 scale. Free. Updated daily.\n\nLink in bio.\n\n#StockAnalysis #Gaming",
        "We identified 4 hype patterns that predict stock movement:\n\nCrescendo — steady rise (best for investing)\nDominant — high and constant\nExplosion — unpredictable spike\nNoise — skip it\n\nFull analysis on our dashboard.\n\n#TradingPatterns",
    ]
    return random.choice(templates)


def generate_weekly_recap(data):
    """Generate a Friday recap tweet."""
    news = data['news']['en']
    top_news = random.sample(news[:4], min(2, len(news[:4])))
    bullets = '\n'.join(f"- {n['html'].split('</strong>')[0].replace('<strong>', '')}" for n in top_news)

    return f"Weekly Gaming Stocks Recap:\n\n{bullets}\n\nFull dashboard with {data['kpis']['games_watchlist']} games tracked, updated daily.\n\n#WeeklyRecap #GamingStocks"


def generate_gaming_casual(data):
    """Weekend casual gaming tweet."""
    templates = [
        "Weekend gaming plans?\n\nWhile you play, we track how game launches affect stock prices.\n\n19 titles. 7 companies. Updated daily.\n\nHappy gaming!\n\n#WeekendGaming #GamesAndStock",
        "Sunday check-in:\n\nMost anticipated game this year?\n\nOur top signal: GTA VI (Score: 79/100)\nOur top watch: Pragmata (Capcom test case)\n\nWhat are you watching?\n\n#GamingCommunity",
    ]
    return random.choice(templates)


def generate_game_comparison(data):
    """Compare two games/stocks."""
    tier1 = data['games']['tier1']
    if len(tier1) >= 2:
        a, b = random.sample(tier1, 2)
        return (
            f"{a['name']} vs {b['name']}\n\n"
            f"${a['ticker']} — Signal: {a['signal']['en']} ({a.get('score', '?')}/100)\n"
            f"${b['ticker']} — Signal: {b['signal']['en']} ({b.get('score', '?')}/100)\n\n"
            f"Which one has more stock potential? Full data on our dashboard.\n\n"
            f"#GamingStocks #Comparison"
        )
    return generate_market_data(data)


def generate_gaming_fact(data):
    """Interesting gaming/stock fact."""
    historical = data.get('historical', [])
    if historical:
        pick = random.choice(historical)
        return (
            f"Historical data point:\n\n"
            f"{pick['game']} (${pick['ticker']})\n"
            f"PRE-60d: {pick['pre60']}\n"
            f"PRE-30d: {pick['pre30']}\n"
            f"POST-30d: {pick['post30']}\n"
            f"POST-90d: {pick['post90']}\n\n"
            f"The pre-launch window is where it happens.\n\n"
            f"#GamingHistory #StockData"
        )
    return generate_sector_context(data)


GENERATORS = {
    'market_data': generate_market_data,
    'investment_signal': generate_investment_signal,
    'game_analysis': generate_game_analysis,
    'sector_context': generate_sector_context,
    'engagement': generate_engagement,
    'dashboard_highlight': generate_dashboard_highlight,
    'weekly_recap': generate_weekly_recap,
    'gaming_casual': generate_gaming_casual,
    'game_comparison': generate_game_comparison,
    'gaming_fact': generate_gaming_fact,
    'poll': generate_engagement,
    'weekend_question': generate_engagement,
    'week_preview': generate_dashboard_highlight,
}


def generate_tweet(slot):
    """Generate a tweet based on the current slot."""
    data = load_data()
    now = datetime.now(timezone.utc)
    weekday = now.weekday()  # 0=Monday

    tweet_type = get_tweet_type(slot, weekday)
    generator = GENERATORS.get(tweet_type, generate_market_data)
    text = generator(data)

    # Ensure under 280 chars
    if len(text) > 280:
        text = text[:277] + '...'

    return text, tweet_type


# ─── Logging ─────────────────────────────────────────────────────────────

def log_tweet(text, tweet_type, slot, tweet_id=None, status='published'):
    """Log tweet to CSV."""
    file_exists = os.path.exists(LOG_PATH)

    with open(LOG_PATH, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'datetime', 'slot', 'type', 'text', 'tweet_id', 'status', 'chars'
        ])
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            'datetime': datetime.now(timezone.utc).isoformat(),
            'slot': slot,
            'type': tweet_type,
            'text': text.replace('\n', ' | '),
            'tweet_id': tweet_id or '',
            'status': status,
            'chars': len(text),
        })


# ─── Main ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Generate and post tweets for @Games_and_Stock')
    parser.add_argument('--slot', choices=['morning', 'midday', 'evening', 'weekend'], default='morning')
    parser.add_argument('--test', action='store_true', help='Generate tweet but do not publish')
    args = parser.parse_args()

    text, tweet_type = generate_tweet(args.slot)
    print(f"[{args.slot}] Type: {tweet_type}")
    print(f"[{len(text)} chars]")
    print(f"\n{text}\n")

    if args.test:
        print("(TEST MODE - not published)")
        log_tweet(text, tweet_type, args.slot, status='test')
        return

    try:
        result = post_tweet(text)
        tweet_id = result.get('data', {}).get('id', 'unknown')
        print(f"Published! Tweet ID: {tweet_id}")
        log_tweet(text, tweet_type, args.slot, tweet_id=tweet_id)
    except Exception as e:
        print(f"Error publishing: {e}")
        log_tweet(text, tweet_type, args.slot, status=f'error: {e}')
        raise


if __name__ == '__main__':
    main()
