#!/usr/bin/env python3
"""
Daily Stock Briefing - Cloud Runner
Fetches live market data, generates an AI briefing via Claude API,
and sends it to your Gmail inbox every weekday at 8 AM EST.
"""

import os
import smtplib
import datetime
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import yfinance as yf
import anthropic


# ── Configuration ────────────────────────────────────────────────────────────
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "jogi.viral801@gmail.com")

INDICES = {
    "S&P 500":     "^GSPC",
    "Nasdaq":      "^IXIC",
    "Dow Jones":   "^DJI",
    "Russell 2000":"^RUT",
    "VIX":         "^VIX",
}

ASSETS = {
    "BTC":  "BTC-USD",
    "ETH":  "ETH-USD",
    "Gold": "GC=F",
    "Oil":  "CL=F",
}

STOCKS = [
    "NVDA", "AAPL", "MSFT", "META", "AMZN", "GOOGL", "TSLA",
    "AMD", "SMCI", "DELL", "JPM", "BAC", "GS", "MRK", "XLE",
    "SPY", "QQQ", "SOXL", "GLD", "USO",
]
# ─────────────────────────────────────────────────────────────────────────────


def fetch_ticker(symbol: str) -> dict:
    """Return price + 1-day % change for a single ticker."""
    try:
        hist = yf.Ticker(symbol).history(period="5d")
        if len(hist) < 2:
            return {}
        prev  = float(hist["Close"].iloc[-2])
        curr  = float(hist["Close"].iloc[-1])
        vol   = float(hist["Volume"].iloc[-1])
        chg   = (curr - prev) / prev * 100
        return {"price": curr, "prev": prev, "change_pct": chg, "volume": vol}
    except Exception as e:
        print(f"  ⚠ Could not fetch {symbol}: {e}")
        return {}


def get_all_market_data() -> tuple[dict, dict, dict]:
    """Fetch indices, crypto/commodities, and individual stocks."""
    print("  Fetching indices …")
    indices = {name: fetch_ticker(sym) for name, sym in INDICES.items()}

    print("  Fetching assets …")
    assets  = {name: fetch_ticker(sym) for name, sym in ASSETS.items()}

    print("  Fetching stocks …")
    stocks  = {}
    for sym in STOCKS:
        d = fetch_ticker(sym)
        if d:
            try:
                info = yf.Ticker(sym).info
                d["name"] = info.get("longName", sym)
            except Exception:
                d["name"] = sym
            stocks[sym] = d

    return indices, assets, stocks


def fmt(data: dict) -> str:
    """Format a ticker dict as a compact string for the Claude prompt."""
    if not data:
        return "N/A"
    arrow = "▲" if data["change_pct"] >= 0 else "▼"
    return f"${data['price']:.2f}  {arrow} {data['change_pct']:+.2f}%"


def build_prompt(indices: dict, assets: dict, stocks: dict, date_str: str) -> str:
    idx_lines   = "\n".join(f"  {n}: {fmt(v)}" for n, v in indices.items() if v)
    asset_lines = "\n".join(f"  {n}: {fmt(v)}" for n, v in assets.items()  if v)

    # Sort stocks by absolute % change so biggest movers appear first
    sorted_stocks = sorted(
        [(s, d) for s, d in stocks.items() if d],
        key=lambda x: abs(x[1]["change_pct"]),
        reverse=True,
    )
    stock_lines = "\n".join(
        f"  {sym} ({d.get('name', sym)}): {fmt(d)}"
        for sym, d in sorted_stocks[:20]
    )

    return f"""You are generating a daily pre-market stock briefing email for {date_str}.

=== LIVE MARKET DATA (fetched seconds ago via Yahoo Finance) ===

INDICES:
{idx_lines}

CRYPTO & COMMODITIES:
{asset_lines}

STOCKS (sorted by biggest movers first):
{stock_lines}

=== YOUR TASK ===
Write a complete, styled HTML email briefing using ONLY the live numbers above for prices and % changes.
Do NOT invent numbers. Use your knowledge of recent news/trends to explain WHY a stock is moving.

Structure:
1. Header: date, session label (Pre-Market / Market Open / Post-Market)
2. Market Overview table (all indices + BTC + ETH with live numbers)
3. Overall market tone: Bullish / Bearish / Mixed — one sentence why
4. Top 8-10 Stocks to Watch — for each:
   - Ticker + company name + live price + % change
   - Signal badge: BUY SIGNAL | SELL SIGNAL | HOLD SIGNAL | WATCH CLOSELY
   - Confidence: X/10
   - Reason: 1-2 sentences (use live % change + your knowledge of the company/sector)
   - Trend to watch
   - Main risk
   - Plain English: one sentence for a total beginner
5. Crypto section: BTC + ETH with live prices, signal, brief reason
6. ETF section: XLE, GLD, SPY, QQQ with live prices, signal, brief reason
7. Final Summary:
   - 🟢 Strongest buy signal: TICKER — reason
   - 🔴 Strongest sell signal: TICKER — reason
   - ❓ Most uncertain: TICKER — reason
   - 📊 Biggest market trend today: 1-2 sentences
8. Footer disclaimer (research only, not financial advice)

=== STYLING RULES ===
- Full self-contained HTML with <style> in <head>
- Dark gradient header (#0f2027 → #2c5364)
- Signal badge colors: green=#16a34a (buy), red=#dc2626 (sell), amber=#f59e0b (hold), purple=#7c3aed (watch)
- Each stock in a card with colored left border matching its signal
- Readable on a phone screen (max-width 680px, font-size ≥ 14px)
- Numbers: green text for positive %, red text for negative %
- No external fonts or images — inline only

Output ONLY the raw HTML. No markdown, no explanation, no code fences.
"""


def generate_briefing(indices: dict, assets: dict, stocks: dict, date_str: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = build_prompt(indices, assets, stocks, date_str)

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def extract_tone(html: str) -> str:
    lower = html.lower()
    bullish = lower.count("bullish")
    bearish = lower.count("bearish")
    if bullish > bearish + 1:
        return "Bullish"
    if bearish > bullish + 1:
        return "Bearish"
    return "Mixed"


def send_email(html: str, date_str: str, tone: str) -> None:
    sender   = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    subject  = f"📈 Daily Stock Briefing — {date_str} | {tone}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, RECIPIENT_EMAIL, msg.as_string())

    print(f"  ✅ Email sent to {RECIPIENT_EMAIL}")


def main():
    date_str = datetime.datetime.now().strftime("%B %d, %Y")
    print(f"\n🚀 Daily Stock Briefing — {date_str}")
    print("=" * 50)

    print("\n📊 Fetching live market data …")
    indices, assets, stocks = get_all_market_data()
    print(f"  Got data for {len(stocks)} stocks, {len(indices)} indices, {len(assets)} assets")

    print("\n🤖 Generating briefing with Claude AI …")
    html = generate_briefing(indices, assets, stocks, date_str)
    tone = extract_tone(html)
    print(f"  Tone detected: {tone}")

    print("\n📧 Sending email …")
    send_email(html, date_str, tone)

    print("\n✅ Done!\n")


if __name__ == "__main__":
    main()
