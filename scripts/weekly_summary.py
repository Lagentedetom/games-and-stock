#!/usr/bin/env python3
"""
Generates a weekly summary of published tweets and posts it as a tweet thread.
Also saves the summary to data/weekly_summaries/.
Runs every Friday at 20:00 CET via GitHub Actions.
"""

import csv
import json
import os
from datetime import datetime, timezone, timedelta
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(SCRIPT_DIR, '..')
LOG_PATH = os.path.join(ROOT_DIR, 'data', 'tweets_log.csv')
SUMMARY_DIR = os.path.join(ROOT_DIR, 'data', 'weekly_summaries')


def get_week_tweets():
    """Get tweets from the last 7 days."""
    if not os.path.exists(LOG_PATH):
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    tweets = []

    with open(LOG_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                dt = datetime.fromisoformat(row['datetime'])
                if dt >= cutoff and row.get('status') == 'published':
                    tweets.append(row)
            except (ValueError, KeyError):
                continue

    return tweets


def generate_summary(tweets):
    """Generate a text summary of the week's tweets."""
    if not tweets:
        return "No tweets published this week.", {}

    total = len(tweets)
    types = Counter(t.get('type', 'unknown') for t in tweets)
    slots = Counter(t.get('slot', 'unknown') for t in tweets)

    # Find mentioned tickers
    tickers = Counter()
    for t in tweets:
        text = t.get('text', '')
        for ticker in ['TTWO', 'CCOEY', 'KNAMF', 'NTDOY', 'CDR.WA', 'SQNXF', 'UBSFY', 'SONY', 'MSFT']:
            if ticker in text:
                tickers[ticker] += 1

    top_types = ', '.join(f"{k} ({v})" for k, v in types.most_common(3))
    top_tickers = ', '.join(f"${k} ({v})" for k, v in tickers.most_common(3)) or 'N/A'

    summary_text = (
        f"Games & Stock — Weekly Report\n\n"
        f"Tweets published: {total}\n"
        f"By slot: {', '.join(f'{k} ({v})' for k, v in slots.most_common())}\n"
        f"Top content types: {top_types}\n"
        f"Most mentioned tickers: {top_tickers}\n\n"
        f"All automated. All free. Dashboard updated daily.\n"
        f"#WeeklyReport #GamingStocks"
    )

    stats = {
        'week_ending': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'total_tweets': total,
        'by_type': dict(types),
        'by_slot': dict(slots),
        'top_tickers': dict(tickers.most_common(5)),
    }

    return summary_text, stats


def save_summary(stats):
    """Save summary stats to a JSON file."""
    os.makedirs(SUMMARY_DIR, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    path = os.path.join(SUMMARY_DIR, f'summary_{date_str}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2)
    print(f"Summary saved to {path}")


def main():
    tweets = get_week_tweets()
    summary_text, stats = generate_summary(tweets)

    print(f"[{len(summary_text)} chars]")
    print(f"\n{summary_text}\n")

    if stats:
        save_summary(stats)

    # Post summary as a tweet if we have the env vars
    try:
        from tweet import post_tweet, log_tweet
        if len(summary_text) <= 280:
            result = post_tweet(summary_text)
            tweet_id = result.get('data', {}).get('id', 'unknown')
            print(f"Summary published! Tweet ID: {tweet_id}")
            log_tweet(summary_text, 'weekly_summary', 'evening', tweet_id=tweet_id)
        else:
            # Truncate for tweet
            short = summary_text[:277] + '...'
            result = post_tweet(short)
            tweet_id = result.get('data', {}).get('id', 'unknown')
            print(f"Summary published (truncated)! Tweet ID: {tweet_id}")
            log_tweet(short, 'weekly_summary', 'evening', tweet_id=tweet_id)
    except Exception as e:
        print(f"Could not publish summary tweet: {e}")
        print("Summary saved locally only.")


if __name__ == '__main__':
    main()
