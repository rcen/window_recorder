"""
Stock price checker module using yfinance
Fetches current prices and daily changes for configured stock tickers
"""
import yfinance as yf
import configparser
import logging
from typing import Dict, List, Optional
from datetime import datetime

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
            hist = stock.history(period='2d')
            
            if hist.empty or len(hist) < 1:
                logging.warning(f"No historical data for {ticker}")
                continue
            
            current_price = hist['Close'].iloc[-1]
            
            # Get previous close
            if len(hist) >= 2:
                previous_close = hist['Close'].iloc[-2]
            else:
                previous_close = info.get('previousClose', current_price)
            
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
    
    Returns:
        HTML string ready to be inserted into webpage
    """
    try:
        tickers = get_stock_tickers()
        if not tickers:
            return ""
        
        stock_data = fetch_stock_data(tickers)
        if not stock_data:
            return ""
        
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
