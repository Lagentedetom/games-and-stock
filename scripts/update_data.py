#!/usr/bin/env python3
"""
Updates games_data.json with fresh stock prices from Yahoo Finance.
Run daily via GitHub Actions or manually.
"""

import json
import os
from datetime import datetime, timezone

try:
    import yfinance as yf
except ImportError:
    print("yfinance not installed. Run: pip install yfinance")
    raise

DATA_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'games_data.json')

# Tickers we track
TICKERS = {
    'TTWO': 'Take-Two Interactive',
    'CCOEY': 'Capcom',
    'KNAMF': 'Konami',
    'NTDOY': 'Nintendo',
    'SQNXF': 'Square Enix',
    'UBSFY': 'Ubisoft',
    'SONY': 'Sony',
    'MSFT': 'Microsoft',
}

# CDR.WA is on Warsaw Stock Exchange - handled separately
WARSAW_TICKERS = {
    'CDR.WA': 'CD Projekt',
}


def fetch_prices():
    """Fetch current prices for all tracked tickers."""
    prices = {}
    all_tickers = list(TICKERS.keys()) + list(WARSAW_TICKERS.keys())

    for ticker_symbol in all_tickers:
        try:
            ticker = yf.Ticker(ticker_symbol)
            info = ticker.fast_info
            current_price = info.get('lastPrice') or info.get('regularMarketPrice')
            if current_price:
                prices[ticker_symbol] = round(current_price, 2)
                print(f"  {ticker_symbol}: ${current_price:.2f}")
            else:
                print(f"  {ticker_symbol}: no price data available")
        except Exception as e:
            print(f"  {ticker_symbol}: error fetching - {e}")

    return prices


def update_data(prices):
    """Update the JSON data file with fresh prices."""
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    data['last_updated'] = today

    # Update analyst table prices
    for analyst in data.get('analysts', []):
        ticker = analyst.get('ticker')
        if ticker in prices:
            if ticker == 'CDR.WA':
                analyst['price'] = f"~{prices[ticker]} PLN"
            else:
                analyst['price'] = f"~${prices[ticker]}"

    print(f"\nData updated for {today}")

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return today


def main():
    print("Fetching stock prices...")
    prices = fetch_prices()

    if not prices:
        print("No prices fetched. Skipping update.")
        return

    date = update_data(prices)
    print(f"games_data.json updated successfully ({date})")


if __name__ == '__main__':
    main()
