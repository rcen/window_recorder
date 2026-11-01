"""
Stock price checker module using yfinance
Fetches current prices and daily changes for configured stock tickers

Caching: Stock data is cached and only refreshed once per hour during market hours
(6 AM - 8 PM local time) to reduce API calls.
"""
import yfinance as yf
import configparser
import logging
import json
import os
from typing import Dict, List, Optional
from datetime import datetime, timedelta

# Cache settings
CACHE_FILE = 'data/stock_cache.json'
CACHE_DURATION_MINUTES = 60  # Refresh every hour
MARKET_HOURS_START = 6       # 6 AM local time (covers pre-market)
MARKET_HOURS_END = 20        # 8 PM local time (covers after-hours)


def _is_market_hours() -> bool:
    """Check if current time is within extended market hours (6 AM - 8 PM)"""
    current_hour = datetime.now().hour
    return MARKET_HOURS_START <= current_hour < MARKET_HOURS_END


def _is_weekday() -> bool:
    """Check if today is a weekday (Mon-Fri)"""
    return datetime.now().weekday() < 5


def _load_cache() -> Optional[Dict]:
    """Load cached stock data from file"""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logging.warning(f"Failed to load stock cache: {e}")
    return None


def _save_cache(data: Dict) -> None:
    """Save stock data to cache file"""
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.warning(f"Failed to save stock cache: {e}")


def _is_cache_valid(cache: Dict) -> bool:
    """Check if cache is still valid (less than CACHE_DURATION_MINUTES old)"""
    if not cache or 'cached_at' not in cache:
        return False
    
    try:
        cached_at = datetime.fromisoformat(cache['cached_at'])
        age = datetime.now() - cached_at
        
        # During market hours on weekdays, refresh hourly
        if _is_weekday() and _is_market_hours():
            return age < timedelta(minutes=CACHE_DURATION_MINUTES)
        
        # Outside market hours or on weekends, cache is valid for longer (4 hours)
        return age < timedelta(hours=4)
    except Exception:
        return False

def get_stock_tickers() -> List[str]:
    """Read stock tickers from config.dat [STOCKS] section"""
    config = configparser.ConfigParser()
    config.read('config.dat', encoding='utf-8')
    
    try:
        tickers_str = config.get('STOCKS', 'tickers')
        # Split by comma and strip whitespace
        tickers = [t.strip().upper() for t in tickers_str.split(',') if t.strip()]
        return tickers
    except (configparser.NoSectionError, configparser.NoOptionError):
        logging.warning("No [STOCKS] section or tickers found in config.dat")
        return []

def fetch_stock_data(tickers: List[str]) -> Dict[str, Dict]:
    """
    Fetch current stock data for given tickers
    
    Returns:
        Dict with ticker as key and dict containing:
        - current_price: Current price
        - previous_close: Previous day's closing price
        - change: Price change in dollars
        - change_percent: Price change percentage
        - currency: Currency symbol
        - name: Stock name
    """
    if not tickers:
        return {}
    
    results = {}
    
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            
            # Try to get 5 days of history to ensure we have enough data
            # This helps when there are weekends, holidays, or delayed data
            hist = stock.history(period='5d')
            
            if hist.empty or len(hist) < 1:
                logging.warning(f"No historical data for {ticker}")
                continue
            
            current_price = hist['Close'].iloc[-1]
            
            # Get previous close - prioritize info dict which is more reliable
            # for the official previous close price
            previous_close = info.get('previousClose') or info.get('regularMarketPreviousClose')
            
            # Fallback to history data if info doesn't have previousClose
            if previous_close is None:
                if len(hist) >= 2:
                    previous_close = hist['Close'].iloc[-2]
                else:
                    logging.warning(f"No previous close data available for {ticker}")
                    previous_close = current_price
            
            change = current_price - previous_close
            change_percent = (change / previous_close * 100) if previous_close else 0
            
            results[ticker] = {
                'current_price': round(current_price, 2),
                'previous_close': round(previous_close, 2),
                'change': round(change, 2),
                'change_percent': round(change_percent, 2),
                'currency': info.get('currency', 'USD'),
                'name': info.get('shortName', ticker),
                'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
        except Exception as e:
            logging.error(f"Error fetching data for {ticker}: {e}")
            continue
    
    return results

def format_stock_html(stock_data: Dict[str, Dict]) -> str:
    """
    Format stock data as HTML for display on activity webpage
    
    Returns:
        HTML string with stock prices and changes
    """
    if not stock_data:
        return ""
    
    html = """
    <div style="background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 8px; padding: 15px; margin-bottom: 20px;">
        <h3 style="margin-top: 0; color: #333; font-size: 18px;">📈 Stock Market Watch</h3>
        <div style="display: flex; gap: 20px; flex-wrap: wrap;">
    """
    
    for ticker, data in stock_data.items():
        change = data['change']
        change_percent = data['change_percent']
        
        # Determine color based on change
        if change > 0:
            color = '#28a745'  # Green
            arrow = '▲'
        elif change < 0:
            color = '#dc3545'  # Red
            arrow = '▼'
        else:
            color = '#6c757d'  # Gray
            arrow = '='
        
        html += f"""
            <div style="flex: 1; min-width: 200px; background: white; padding: 12px; border-radius: 6px; border: 1px solid #e0e0e0;">
                <div style="font-weight: bold; font-size: 16px; color: #333; margin-bottom: 5px;">
                    {ticker}
                </div>
                <div style="font-size: 14px; color: #666; margin-bottom: 8px;">
                    {data['name']}
                </div>
                <div style="font-size: 20px; font-weight: bold; color: #000; margin-bottom: 5px;">
                    ${data['current_price']:,.2f}
                </div>
                <div style="font-size: 14px; color: {color}; font-weight: 600;">
                    {arrow} ${abs(change):.2f} ({change_percent:+.2f}%)
                </div>
                <div style="font-size: 11px; color: #999; margin-top: 5px;">
                    Prev: ${data['previous_close']:,.2f}
                </div>
            </div>
        """
    
    html += """
        </div>
        <div style="font-size: 11px; color: #888; margin-top: 10px; text-align: right;">
            Last updated: """ + list(stock_data.values())[0]['last_updated'] + """
        </div>
    </div>
    """
    
    return html

def get_stock_html() -> str:
    """
    Main function to get stock data and return formatted HTML
    
    Uses caching to only fetch from API once per hour during market hours.
    
    Returns:
        HTML string ready to be inserted into webpage
    """
    try:
        tickers = get_stock_tickers()
        if not tickers:
            return ""
        
        # Try to use cached data first
        cache = _load_cache()
        if cache and _is_cache_valid(cache):
            stock_data = cache.get('stock_data', {})
            if stock_data:
                logging.debug(f"Using cached stock data from {cache.get('cached_at')}")
                return format_stock_html(stock_data)
        
        # Fetch fresh data
        stock_data = fetch_stock_data(tickers)
        if not stock_data:
            # If fetch failed but we have stale cache, use it anyway
            if cache and cache.get('stock_data'):
                logging.info("Using stale stock cache due to fetch failure")
                return format_stock_html(cache['stock_data'])
            return ""
        
        # Save to cache
        _save_cache({
            'cached_at': datetime.now().isoformat(),
            'stock_data': stock_data
        })
        
        return format_stock_html(stock_data)
    except Exception as e:
        logging.error(f"Error generating stock HTML: {e}")
        return ""

if __name__ == '__main__':
    # Test the module
    logging.basicConfig(level=logging.INFO)
    
    print("Testing stock price fetcher...")
    tickers = get_stock_tickers()
    print(f"Configured tickers: {tickers}")
    
    if tickers:
        stock_data = fetch_stock_data(tickers)
        print("\nStock Data:")
        for ticker, data in stock_data.items():
            print(f"\n{ticker} - {data['name']}")
            print(f"  Current: ${data['current_price']}")
            print(f"  Change: ${data['change']} ({data['change_percent']:+.2f}%)")
        
        print("\n" + "="*60)
        print("HTML Preview:")
        print("="*60)
        print(get_stock_html())
