# Stock Market Integration for Window Recorder

## Overview
Added real-time stock price tracking and display to the activity monitoring webpage using Yahoo Finance data.

## What Was Added

### 1. Configuration File (`config.dat`)
Added a new `[STOCKS]` section at the top:
```ini
[STOCKS]
tickers = VOO, SOXL
```

You can add or remove stock tickers by editing this line. Separate multiple tickers with commas.

### 2. Stock Price Module (`stock_prices.py`)
Created a new Python module that:
- Reads stock tickers from `config.dat`
- Fetches current prices and daily changes using `yfinance` library
- Calculates price changes and percentages
- Formats data as HTML with color-coded indicators:
  - 🟢 Green (▲) for gains
  - 🔴 Red (▼) for losses
  - ⚪ Gray (=) for no change

### 3. Analytics Integration (`analytics.py`)
Modified to automatically include stock prices at the top of the activity webpage when generating HTML reports.

## Features

The stock display shows:
- **Ticker Symbol** (e.g., VOO, SOXL)
- **Full Name** (e.g., "Vanguard S&P 500 ETF")
- **Current Price** (e.g., $610.05)
- **Daily Change** (e.g., ▲ $9.35 +1.56%)
- **Previous Close** (e.g., Prev: $600.51)
- **Last Updated** timestamp

## Installation

The required `yfinance` package has been automatically installed to your virtual environment.

## Usage

### Adding/Removing Stocks
Edit `config.dat` and modify the tickers line:
```ini
[STOCKS]
tickers = VOO, SOXL, QQQ, SPY, AAPL, TSLA
```

### Testing Stock Prices
Run the module directly to see current data:
```bash
python stock_prices.py
```

### Generating HTML with Stock Prices
Stock prices are automatically included when you run:
```bash
python analytics.py
```

The HTML report (`html/index.html`) will show stock prices at the top, refreshed each time you generate the report.

## Example Output

```
📈 Stock Market Watch

VOO - Vanguard S&P 500 ETF
$610.05
▲ $9.35 (+1.56%)
Prev: $600.51

SOXL - Direxion Daily Semiconductor Bull 3X Shares
$34.21
= $0.00 (-0.00%)
Prev: $34.21
```

## Data Source

- **Provider**: Yahoo Finance (via `yfinance` library)
- **Cost**: Free, no API key required
- **Update Frequency**: Real-time during market hours, delayed 15-20 minutes outside market hours
- **Historical Data**: Previous day's closing price for comparison

## Limitations

1. **Market Hours**: Prices update only during market hours (9:30 AM - 4:00 PM ET, weekdays)
2. **Delays**: May have 15-20 minute delays outside of live trading hours
3. **Network Required**: Requires internet connection to fetch data
4. **Rate Limits**: Yahoo Finance may throttle excessive requests

## Troubleshooting

### No Stock Data Shown
- Check internet connection
- Verify ticker symbols are correct in `config.dat`
- Check console for error messages when running `python analytics.py`

### Old Prices Displayed
- Stock prices refresh each time you run `python analytics.py`
- The webpage auto-refreshes every 100 seconds (see meta refresh tag)

### Adding More Tickers
You can track any ticker available on Yahoo Finance:
- ETFs: VOO, SPY, QQQ, IWM, etc.
- Stocks: AAPL, MSFT, GOOGL, TSLA, etc.
- Indices: ^GSPC (S&P 500), ^DJI (Dow), ^IXIC (NASDAQ)
- Cryptocurrencies: BTC-USD, ETH-USD, etc.

## Files Modified

1. `config.dat` - Added [STOCKS] section
2. `analytics.py` - Added import and integration
3. `stock_prices.py` - New file (created)

## Future Enhancements

Possible improvements:
- Add 52-week high/low indicators
- Show volume traded
- Display market cap
- Add historical charts (7-day, 30-day trends)
- Separate section for gainers/losers
- Alert notifications when stocks hit certain thresholds
- Integration with portfolio tracking (show your holdings value)

---
**Created**: October 13, 2025  
**Dependencies**: yfinance, pandas, configparser
