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
from urllib.parse import quote, urlencode
from urllib.error import HTTPError
import hmac
import base64
import time
import uuid
import re
import tempfile

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

    try:
        response = urlopen(req)
        result = json.loads(response.read().decode('utf-8'))
        return result
    except Exception as e:
        # Try to read the error body for more details
        if hasattr(e, 'read'):
            error_body = e.read().decode('utf-8', errors='replace')
            print(f"API error body: {error_body}")
        raise


# ─── Candlestick Chart Generation ──────────────────────────────────────

def generate_chart(ticker, period='6mo'):
    """Generate a candlestick chart for a ticker. Returns path to PNG or None."""
    try:
        import yfinance as yf
        import mplfinance as mpf
        import matplotlib
        matplotlib.use('Agg')  # headless
    except ImportError as e:
        print(f"Chart libs not available ({e}), skipping chart.")
        return None

    try:
        data = yf.download(ticker, period=period, auto_adjust=True, progress=False)
        if data is None or len(data) < 10:
            print(f"Not enough data for {ticker}, skipping chart.")
            return None

        # Drop multi-level columns if present (yfinance sometimes returns them)
        if hasattr(data.columns, 'levels') and data.columns.nlevels > 1:
            data.columns = data.columns.get_level_values(0)

        # Custom dark style for the trading look
        mc = mpf.make_marketcolors(
            up='#00c896', down='#e54545',
            edge={'up': '#00c896', 'down': '#e54545'},
            wick={'up': '#00c896', 'down': '#e54545'},
            volume={'up': '#1a4a3a', 'down': '#4a1a1a'},
        )
        style = mpf.make_mpf_style(
            base_mpf_style='nightclouds',
            marketcolors=mc,
            facecolor='#0f0f1a',
            edgecolor='#2a2a3a',
            figcolor='#0f0f1a',
            gridcolor='#1a1a2e',
            gridstyle='--',
            gridaxis='both',
            rc={
                'font.size': 10,
                'axes.labelcolor': '#8888a0',
                'xtick.color': '#8888a0',
                'ytick.color': '#8888a0',
            },
        )

        # Create chart
        chart_path = os.path.join(tempfile.gettempdir(), f'chart_{ticker.replace(".", "_")}.png')

        fig, axes = mpf.plot(
            data,
            type='candle',
            style=style,
            volume=True,
            title='',
            figsize=(10, 5.5),
            returnfig=True,
            tight_layout=True,
        )

        # Add branding text
        fig.text(0.02, 0.97, f'${ticker}', fontsize=22, fontweight='bold',
                 color='#e8e8f0', va='top', fontfamily='sans-serif')
        fig.text(0.02, 0.92, f'{period} · Candlestick', fontsize=11,
                 color='#8888a0', va='top', fontfamily='sans-serif')
        fig.text(0.98, 0.02, 'Games & Stock · lagentedetom.github.io/games-and-stock',
                 fontsize=9, color='#6c5ce7', ha='right', va='bottom',
                 fontfamily='sans-serif')

        fig.savefig(chart_path, dpi=150, bbox_inches='tight',
                    facecolor='#0f0f1a', edgecolor='none')
        import matplotlib.pyplot as plt
        plt.close(fig)

        print(f"Chart generated: {chart_path}")
        return chart_path

    except Exception as e:
        print(f"Error generating chart for {ticker}: {e}")
        return None


# ─── Media Upload ───────────────────────────────────────────────────────

def upload_media(image_path):
    """Upload an image to Twitter via v1.1 media/upload. Returns media_id string."""
    api_key = get_env('X_API_KEY')
    api_secret = get_env('X_API_SECRET')
    access_token = get_env('X_ACCESS_TOKEN')
    access_token_secret = get_env('X_ACCESS_TOKEN_SECRET')

    url = 'https://upload.twitter.com/1.1/media/upload.json'
    method = 'POST'

    with open(image_path, 'rb') as f:
        image_bytes = f.read()

    # OAuth params only (media NOT in signature for multipart)
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

    # Build multipart/form-data body manually
    boundary = uuid.uuid4().hex
    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="media_data"\r\n\r\n'
        f'{base64.b64encode(image_bytes).decode("utf-8")}\r\n'
        f'--{boundary}--\r\n'
    ).encode('utf-8')

    req = Request(url, data=body, method='POST')
    req.add_header('Authorization', auth_header)
    req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')

    try:
        response = urlopen(req)
        result = json.loads(response.read().decode('utf-8'))
        media_id = result.get('media_id_string')
        print(f"Media uploaded: {media_id}")
        return media_id
    except Exception as e:
        if hasattr(e, 'read'):
            error_body = e.read().decode('utf-8', errors='replace')
            print(f"Media upload error: {error_body}")
        print(f"Media upload failed: {e}")
        return None


def post_tweet_with_media(text, media_id=None):
    """Post a tweet, optionally with a media attachment."""
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

    payload = {'text': text}
    if media_id:
        payload['media'] = {'media_ids': [media_id]}

    body = json.dumps(payload).encode('utf-8')
    req = Request(url, data=body, method='POST')
    req.add_header('Authorization', auth_header)
    req.add_header('Content-Type', 'application/json')

    try:
        response = urlopen(req)
        result = json.loads(response.read().decode('utf-8'))
        return result
    except Exception as e:
        if hasattr(e, 'read'):
            error_body = e.read().decode('utf-8', errors='replace')
            print(f"API error body: {error_body}")
        raise


def extract_ticker_from_text(text):
    """Extract the first cashtag ticker from tweet text."""
    match = re.search(r'\$([A-Z][A-Z0-9_.]{1,10})', text)
    return match.group(1) if match else None


# ─── Tweet Generation ────────────────────────────────────────────────────

DASHBOARD_URL = "https://lagentedetom.github.io/games-and-stock/"

# Tweet types that should NOT get a chart (engagement, opinions without specific data)
NO_CHART_TYPES = {'engagement', 'gaming_casual', 'gaming_opinion', 'platform_story'}


def enforce_single_cashtag(text):
    """X free tier allows max 1 cashtag per tweet. Keep the first, remove $ from the rest."""
    matches = list(re.finditer(r'\$([A-Z][A-Z0-9_.]{1,10})', text))
    if len(matches) <= 1:
        return text
    # Keep the first cashtag, remove $ from subsequent ones
    for m in reversed(matches[1:]):
        text = text[:m.start()] + m.group(1) + text[m.end():]
    return text


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
        return random.choice([
            'gaming_opinion', 'game_hype_check', 'platform_story',
            'engagement', 'gaming_casual',
        ])

    schedule = {
        'morning': [
            'market_data', 'game_hype_check', 'market_opinion',
            'investment_signal', 'weekly_recap',
        ],
        'midday': [
            'game_analysis', 'game_disappointment', 'gaming_fact',
            'sector_context', 'platform_story',
        ],
        'evening': [
            'engagement', 'platform_highlight', 'gaming_opinion',
            'engagement', 'platform_highlight',
        ],
    }

    types = schedule.get(slot, ['market_data'])
    return types[weekday] if weekday < len(types) else types[0]


# ─── MARKET & DATA tweets ───────────────────────────────────────────────

def generate_market_data(data):
    """Market data tweet with a conversational touch."""
    analysts = data.get('analysts', [])
    pick = random.choice([a for a in analysts if a.get('upside_class') == 'green'] or analysts)
    ticker = pick['ticker']
    rating = pick['rating']
    price = pick['price']
    catalyst = pick['catalyst']['en']

    templates = [
        f"Quick update on ${ticker}:\n\nAnalysts say {rating} at {price}.\nThe catalyst? {catalyst}.\n\nWe track this daily on our dashboard.\n\n{DASHBOARD_URL}",
        f"${ticker} is rated {rating} right now ({price}).\n\n{catalyst} — that's the key driver according to analysts.\n\nAll data free on our dashboard.\n\n{DASHBOARD_URL}",
        f"Been watching ${ticker} closely.\n\nRating: {rating}\nPrice: {price}\n\nWhat's behind it: {catalyst}\n\nWe update this every single day.\n\n{DASHBOARD_URL}",
        f"Analysts are {rating.lower()} on ${ticker} ({price}).\n\nMain catalyst: {catalyst}\n\nIs this the right time to pay attention? We think so.\n\n{DASHBOARD_URL}",
    ]
    return random.choice(templates)


def generate_market_opinion(data):
    """Market data with personal opinion layer."""
    kpis = data['kpis']
    templates = [
        f"The best upside we're tracking right now: {kpis['best_upside']} on {kpis['best_upside_note']}.\n\nThat's not a small number. Whether it plays out depends on execution, but the analysts are clearly bullish.\n\n{DASHBOARD_URL}",
        f"Interesting to see how gaming stocks are moving this year.\n\nBest case historically: {kpis['historical_max']} ({kpis['historical_max_note']})\nWorst case: {kpis['worst_crash']} ({kpis['worst_crash_note']})\n\nTiming is everything.\n\n{DASHBOARD_URL}",
        f"People ask us: can a single game really move a stock?\n\nPokemon GO moved Nintendo {kpis['historical_max']} in 10 days. Cyberpunk crashed CDR {kpis['worst_crash']} in a month.\n\nSo yes. Yes it can.\n\n{DASHBOARD_URL}",
    ]
    return random.choice(templates)


def generate_investment_signal(data):
    """Investment signal with human commentary."""
    tier1 = data['games']['tier1']
    game = random.choice(tier1)
    name = game['name']
    ticker = game['ticker']
    signal = game['signal']['en']
    score = game.get('score', '?')
    desc = game['description']['en']
    short_desc = desc[:100] + '...' if len(desc) > 100 else desc

    templates = [
        f"Our signal on {name}: {signal} ({score}/100)\n\nTicker: ${ticker}\n\n{short_desc}\n\nWhat do you think — does this one have legs?\n\n{DASHBOARD_URL}",
        f"Signal Score update — {name}\n\nScore: {score}/100 ({signal})\n${ticker}\n\n{short_desc}\n\nAll scores updated daily, free.\n\n{DASHBOARD_URL}",
        f"We've been tracking {name} for a while now.\n\nOur score: {score}/100 — {signal}\n${ticker}\n\nThe data tells a clear story here.\n\n{DASHBOARD_URL}",
    ]
    return random.choice(templates)


# ─── GAME OPINION tweets ────────────────────────────────────────────────

def generate_game_hype_check(data):
    """Tweet about highly anticipated games and whether the hype is justified."""
    hype_takes = [
        "GTA VI is 7 months away and the hype hasn't slowed down one bit.\n\n$TTWO analysts have a +44% upside target. 15 out of 16 say Buy.\n\nThis might be the most predictable stock play in gaming history. Or the biggest trap.\n\nWhat's your read?",
        "Everyone's talking about GTA VI, but Pragmata launches THIS WEEK.\n\nCapcom's first new IP in years. If it hits, $CCOEY has room to run. If it flops, it tells us a lot about Capcom's pipeline risk.\n\nWe're watching closely.",
        f"Zelda OoT Remake — a complete rebuild from scratch for the 40th anniversary.\n\nNintendo rarely misses with Zelda. But $NTDOY is a mega-cap — how much can one game really move it?\n\nHistorically? More than you'd think.\n\n{DASHBOARD_URL}",
        "The Witcher IV has a 778M USD budget. That's not a game — that's a bet-the-company moment for CD Projekt.\n\nOur signal: Wait (32/100). Too early. But when the window opens, $CDR.WA could be one of the most interesting plays in gaming.\n\nPatience.",
        "Silent Hill: Townfall. Castlevania: Belmont's Curse. MGS Master Collection Vol. 2.\n\nKonami is reviving EVERYTHING. The question is: can nostalgia alone move $KNAMF?\n\nOur signal says Buy. History says... it depends.",
        f"Star Fox announcement reportedly imminent.\n\nA new Star Fox with online multiplayer? In 2026? If Nintendo plays this right, it could be a sleeper hit for $NTDOY.\n\nWe'll be tracking the Google Trends data as soon as it drops.\n\n{DASHBOARD_URL}",
    ]
    return random.choice(hype_takes)


def generate_game_disappointment(data):
    """Tweet about games/companies not generating expected hype."""
    disappointment_takes = [
        "Ubisoft cancelled 6 games this year. Closing studios. Expected operating loss of ~1B EUR.\n\n$UBSFY is at $0.89. Not a typo.\n\nSometimes the signal isn't about what's launching — it's about what's NOT launching.",
        "Square Enix is in a tough spot.\n\nFF VII Rebirth ports. Kingdom Hearts IV in 2027. Nothing with real momentum right now.\n\n$SQNXF rated Risk on our dashboard. Sometimes the best signal is 'stay away'.\n\nNot every gaming stock is a buy.",
        "Fable is coming this fall. Looks great. But here's the thing:\n\nMicrosoft is so big that one game barely moves the needle on $MSFT. Our signal: Diluted (18/100).\n\nNot every great game is a great stock play.",
        "Hot take: Marvel's Wolverine will be a great game but a terrible stock catalyst.\n\nSony is a mega-cap. One PS5 exclusive, even a big one, gets diluted.\n\nOur score: 22/100. Play the game, skip the stock.\n\nNot investment advice, obviously.",
        "Remember Cyberpunk 2077?\n\nMassive hype. Broken launch. $CDR.WA crashed -33.7% in 30 days.\n\nThat's why we built the 'Cyberpunk Factor' into our model. Extreme hype + expectations gap = danger zone.\n\nLesson learned.",
        f"Nintendo cut Switch 2 production by 33%. Demand cooling in the US and Europe.\n\n$NTDOY has been recovering, but this is worth watching. Hardware cycles matter as much as game launches.\n\n{DASHBOARD_URL}",
    ]
    return random.choice(disappointment_takes)


def generate_gaming_opinion(data):
    """General gaming + stock opinion with personality."""
    opinions = [
        "Unpopular opinion: Google Trends is a better predictor of gaming stock moves than analyst reports.\n\nOur data shows r = 0.749 correlation between sustained Trends interest and pre-launch stock gains.\n\nAnalysts are smart. The crowd is smarter.",
        "The gaming industry generated more revenue than movies and music COMBINED last year.\n\nBut most investors still treat gaming stocks as 'entertainment bets' rather than serious positions.\n\nWe think that's a mistake.",
        f"We've been building Games & Stock because we noticed something: nobody was connecting game launch data with stock performance in a systematic way.\n\n19 games. 7 companies. Correlations. Signals. All free, updated daily.\n\n{DASHBOARD_URL}",
        "The pre-launch window is where the money is.\n\n60-90 days before launch, if Google Trends shows sustained interest, stocks tend to move.\n\nAfter launch? It's already priced in.\n\nTiming > hype.",
        "Three things we've learned tracking gaming stocks:\n\n1. Mid-caps move more than mega-caps\n2. Consistent hype beats peak hype\n3. Post-launch is usually too late\n\nSimple rules. Hard to follow.",
        f"Trump tariffs hit gaming stocks hard this quarter — the index dropped 300+ points in Q1.\n\nBut the best gaming companies adapt. The question is which ones.\n\nWe track 7 companies daily to find out.\n\n{DASHBOARD_URL}",
    ]
    return random.choice(opinions)


# ─── PLATFORM / PROJECT tweets ──────────────────────────────────────────

def generate_platform_story(data):
    """Tweets about what Games & Stock is and why it exists."""
    kpis = data['kpis']
    stories = [
        f"What is Games & Stock?\n\nA free dashboard that tracks how upcoming game launches affect stock prices.\n\n{kpis['games_watchlist']} games monitored, 7 companies, updated daily.\n\nNo paywalls. No subscriptions. Just data.\n\n{DASHBOARD_URL}",
        f"We built Games & Stock because we couldn't find this data anywhere else.\n\nGoogle Trends hype vs stock performance. Signal Scores. Historical patterns.\n\nAll in one place, all free.\n\n{DASHBOARD_URL}",
        f"How does our Signal Score work?\n\n40% — Google Trends level\n25% — Time window to launch\n20% — Trend acceleration\n15% — Consistency\n\n0 to 100. Updated daily. It's not magic, it's math.\n\n{DASHBOARD_URL}",
        f"We've identified 4 hype patterns that predict stock movement:\n\nCrescendo — best for investing (steady growth)\nDominant — high and constant (like GTA VI)\nExplosion — too late to catch\nNoise — ignore it\n\nFull breakdown on our dashboard.\n\n{DASHBOARD_URL}",
        f"Games & Stock is available in English and Spanish.\n\nSame data, same updates, two languages.\n\nBecause gaming stocks don't care what language you speak.\n\n{DASHBOARD_URL}",
        f"Why do we do this for free?\n\nBecause this data should be accessible to everyone, not locked behind expensive terminals.\n\n{kpis['games_watchlist']} games. 7 companies. Daily updates.\n\nBookmark it. Use it. Tell a friend.\n\n{DASHBOARD_URL}",
    ]
    return random.choice(stories)


def generate_platform_highlight(data):
    """Highlight a specific feature or data point from the dashboard."""
    kpis = data['kpis']
    highlights = [
        f"Dashboard update: {kpis['games_watchlist']} games tracked, prices refreshed today.\n\nBest current upside: {kpis['best_upside']} ({kpis['best_upside_note']})\nTop correlation: r = {kpis['top_correlation']}\n\nCheck it yourself.\n\n{DASHBOARD_URL}",
        f"Did you know we track trading rules on our dashboard?\n\nRule #1: Enter 60-90 days before launch if Trends > 30/100 for 4+ weeks.\nRule #4: Beware the Cyberpunk Factor — extreme hype can = crash.\n\nAll 4 rules explained here.\n\n{DASHBOARD_URL}",
        f"New to our dashboard? Here's what you'll find:\n\nSignal Scores for {kpis['games_watchlist']} upcoming games\nAnalyst consensus for 7 companies\nHistorical correlation data\n4 trading rules\n\nAll free. Bookmark it.\n\n{DASHBOARD_URL}",
        f"Our dashboard shows real analyst data:\n\n$TTWO — Strong Buy (target $284.80)\n$NTDOY — Overweight (+29%)\n$CCOEY — Outperform\n$KNAMF — Buy\n\nUpdated daily with live prices.\n\n{DASHBOARD_URL}",
    ]
    return random.choice(highlights)


# ─── ENGAGEMENT tweets ───────────────────────────────────────────────────

def generate_engagement(data):
    """Engagement tweets — questions, polls, conversation starters."""
    templates = [
        "Which game launch will impact stocks the most in 2026?\n\nA) GTA VI ($TTWO)\nB) Zelda OoT Remake ($NTDOY)\nC) Silent Hill Townfall ($KNAMF)\nD) Pragmata ($CCOEY)\n\nReply with your pick!",
        "Hot take: GTA VI will move $TTWO more than any single game has moved a stock in the last 10 years.\n\nAgree or disagree?",
        "What's your gaming stock strategy?\n\n1. Buy pre-launch, sell at release\n2. Buy post-launch dip\n3. Hold long term\n4. Avoid gaming stocks entirely\n\nLet us know!",
        "Do you check Google Trends before investing in gaming stocks?\n\nOur data shows a strong correlation between sustained hype and pre-launch stock gains.\n\nCurious if anyone else does this.",
        "Honest question: do you think gaming stocks are undervalued or overvalued right now?\n\nWe see opportunities in mid-caps like $KNAMF and $CCOEY. But mega-caps? Hard to move the needle.\n\nWhat's your take?",
        "If you could only invest in ONE gaming stock for the rest of 2026, which one?\n\n$TTWO — GTA VI play\n$KNAMF — Konami revival\n$CCOEY — Capcom pipeline\n$CDR.WA — Witcher IV (long)\n\nReply below.",
        "We're curious — how many of you follow gaming stocks?\n\nIs this a niche thing or are more people connecting the dots between game launches and stock performance?\n\nRetweet if you think this is underrated.",
        "Name a game that SHOULD move its company's stock but probably won't because the company is too big.\n\nWe'll start: Fable ($MSFT). Great game, invisible stock impact.",
    ]
    return random.choice(templates)


# ─── ANALYSIS & FACTS tweets ────────────────────────────────────────────

def generate_game_analysis(data):
    """Game analysis with conversational tone."""
    all_games = data['games']['tier1'] + data['games']['tier2']
    game = random.choice(all_games)
    name = game['name']
    ticker = game['ticker']
    company = game.get('company', '')
    signal = game['signal']['en']

    templates = [
        f"Let's talk about {name}.\n\nCompany: {company}\nTicker: ${ticker}\nOur signal: {signal}\n\nHow will this launch affect the stock? That's exactly what we track.\n\n{DASHBOARD_URL}",
        f"Keeping an eye on {name} ({company}).\n\nSignal: {signal} | ${ticker}\n\nThe correlation between game launches and stock movements is real — and we have the data to prove it.\n\n{DASHBOARD_URL}",
        f"{name} — is the market paying attention?\n\nOur signal for ${ticker}: {signal}\n\nSometimes the best opportunities are the ones nobody's talking about.\n\n{DASHBOARD_URL}",
    ]
    return random.choice(templates)


def generate_sector_context(data):
    """Sector context with storytelling."""
    kpis = data['kpis']
    corr = data['correlations'][0]

    templates = [
        f"Here's a stat that surprised us:\n\nThe correlation between Google Trends consistency and pre-launch stock movement is r = {corr['value']}.\n\nNot the PEAK of hype — the CONSISTENCY of it.\n\nSustained interest > viral moments.\n\n{DASHBOARD_URL}",
        f"Gaming stocks snapshot:\n\n{kpis['games_watchlist']} games on our watchlist\nBest upside: {kpis['best_upside']} ({kpis['best_upside_note']})\nTop correlation: r = {kpis['top_correlation']}\n\nUpdated daily.\n\n{DASHBOARD_URL}",
        f"The gaming-stock connection in one tweet:\n\nBest case: {kpis['historical_max']} ({kpis['historical_max_note']})\nWorst case: {kpis['worst_crash']} ({kpis['worst_crash_note']})\n\nThe opportunity is real. So is the risk.\n\n{DASHBOARD_URL}",
    ]
    return random.choice(templates)


def generate_weekly_recap(data):
    """Friday recap with human touch."""
    news = data['news']['en']
    top_news = random.sample(news[:4], min(2, len(news[:4])))
    bullets = '\n'.join(f"- {n['html'].split('</strong>')[0].replace('<strong>', '')}" for n in top_news)

    return f"Week in gaming stocks:\n\n{bullets}\n\nHave a good weekend. We'll be back Monday with fresh data.\n\n{DASHBOARD_URL}"


def generate_gaming_casual(data):
    """Weekend casual — relaxed, human tone."""
    templates = [
        "Weekend mode.\n\nWhile you're gaming, we're updating the dashboard for Monday.\n\n19 titles. 7 companies. Prices refreshed daily.\n\nEnjoy your weekend.\n\n" + DASHBOARD_URL,
        "What are you playing this weekend?\n\nWe're tracking 19 game launches and their stock impact. But sometimes you just need to disconnect and play.\n\nTell us what you're into right now.",
        "Sunday thought:\n\nThe best time to research gaming stocks is when the market is closed.\n\nOur dashboard is always open. Free. Updated daily.\n\nHappy Sunday.\n\n" + DASHBOARD_URL,
        "Quick Sunday check-in.\n\nMost anticipated game this year?\n\nOur top signal: GTA VI (79/100)\nBiggest question mark: Pragmata (Capcom's test)\n\nWhat's on your radar?",
    ]
    return random.choice(templates)


def generate_gaming_fact(data):
    """Historical fact with context and opinion."""
    historical = data.get('historical', [])
    if historical:
        pick = random.choice(historical)
        game = pick['game']
        ticker = pick['ticker']

        templates = [
            (
                f"History lesson: {game}\n\n"
                f"${ticker} moved:\n"
                f"PRE-60d: {pick['pre60']}\n"
                f"PRE-30d: {pick['pre30']}\n"
                f"POST-30d: {pick['post30']}\n"
                f"POST-90d: {pick['post90']}\n\n"
                f"The pattern is almost always the same: the pre-launch window is where it happens."
            ),
            (
                f"Did you know?\n\n"
                f"When {game} launched, ${ticker} did {pick['post30']} in the first month.\n\n"
                f"But the real move was BEFORE launch: {pick['pre30']} in the 30 days prior.\n\n"
                f"This is why we focus on pre-launch signals.\n\n{DASHBOARD_URL}"
            ),
        ]
        return random.choice(templates)
    return generate_sector_context(data)


GENERATORS = {
    'market_data': generate_market_data,
    'market_opinion': generate_market_opinion,
    'investment_signal': generate_investment_signal,
    'game_analysis': generate_game_analysis,
    'game_hype_check': generate_game_hype_check,
    'game_disappointment': generate_game_disappointment,
    'gaming_opinion': generate_gaming_opinion,
    'sector_context': generate_sector_context,
    'engagement': generate_engagement,
    'platform_story': generate_platform_story,
    'platform_highlight': generate_platform_highlight,
    'weekly_recap': generate_weekly_recap,
    'gaming_casual': generate_gaming_casual,
    'gaming_fact': generate_gaming_fact,
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
    parser.add_argument('--no-chart', action='store_true', help='Skip chart generation')
    args = parser.parse_args()

    MAX_RETRIES = 3
    for attempt in range(1, MAX_RETRIES + 1):
        text, tweet_type = generate_tweet(args.slot)
        text = enforce_single_cashtag(text)
        print(f"[{args.slot}] Type: {tweet_type} (attempt {attempt}/{MAX_RETRIES})")
        print(f"[{len(text)} chars]")
        print(f"\n{text}\n")

        # Generate chart if tweet mentions a ticker and type is chart-worthy
        chart_path = None
        media_id = None
        if not args.no_chart and tweet_type not in NO_CHART_TYPES:
            ticker = extract_ticker_from_text(text)
            if ticker:
                print(f"Generating candlestick chart for {ticker}...")
                chart_path = generate_chart(ticker)

        if args.test:
            print("(TEST MODE - not published)")
            if chart_path:
                print(f"Chart preview: {chart_path}")
            log_tweet(text, tweet_type, args.slot, status='test')
            return

        # Upload chart if generated
        if chart_path:
            media_id = upload_media(chart_path)
            if media_id:
                print(f"Chart attached (media_id: {media_id})")
            else:
                print("Chart upload failed, publishing without image.")

        try:
            result = post_tweet_with_media(text, media_id=media_id)
            tweet_id = result.get('data', {}).get('id', 'unknown')
            has_chart = ' +chart' if media_id else ''
            print(f"Published{has_chart}! Tweet ID: {tweet_id}")
            log_tweet(text, tweet_type, args.slot, tweet_id=tweet_id,
                      status=f'published{has_chart}')
            return  # Success — exit
        except HTTPError as e:
            error_body = ''
            if hasattr(e, 'read'):
                error_body = e.read().decode('utf-8', errors='replace')
                print(f"API error body: {error_body}")
            if e.code == 403 and 'duplicate' in error_body.lower():
                print(f"Duplicate content detected. {'Retrying...' if attempt < MAX_RETRIES else 'All retries exhausted.'}")
                if attempt == MAX_RETRIES:
                    log_tweet(text, tweet_type, args.slot, status='error: duplicate after retries')
                    raise
                continue  # Retry with a new tweet
            else:
                print(f"Error publishing: {e}")
                log_tweet(text, tweet_type, args.slot, status=f'error: {e}')
                raise
        except Exception as e:
            print(f"Error publishing: {e}")
            log_tweet(text, tweet_type, args.slot, status=f'error: {e}')
            raise


if __name__ == '__main__':
    main()
