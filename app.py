from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import yfinance as yf
import sqlite3
from datetime import datetime, time
import pandas as pd
import logging
import hashlib

app = Flask(__name__)
app.secret_key = 'your_secure_random_string'  # Replace with: python -c "import secrets; print(secrets.token_hex(16))"
EDIT_PASSWORD_HASH = hashlib.sha256('hedge2025'.encode()).hexdigest()  # Single password for stock edits

# Set up logging
logging.basicConfig(level=logging.INFO, filename='app.log', filemode='a',
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def init_db():
    try:
        conn = sqlite3.connect('portfolio.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS holdings
                     (ticker TEXT PRIMARY KEY, shares REAL, purchase_price REAL, purchase_date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS transactions
                     (ticker TEXT, action TEXT, shares REAL, price REAL, date TEXT, notes TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS messages
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT, posted_by TEXT, posted_at TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS recaps
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, content TEXT, posted_by TEXT, posted_at TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS notices
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT, posted_by TEXT, posted_at TEXT)''')
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database initialization failed: {e}")
        raise
    finally:
        conn.close()

def get_daytime_greeting():
    current_hour = datetime.now().hour
    if 5 <= current_hour < 12:
        return "Good Morning", "morning"
    elif 12 <= current_hour < 17:
        return "Good Afternoon", "afternoon"
    elif 17 <= current_hour < 22:
        return "Good Evening", "evening"
    else:
        return "Good Night", "night"

def get_sector(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        sector = info.get('sector', 'Unknown')
        if not isinstance(sector, str):
            logger.warning(f"Invalid sector type for {ticker}: {type(sector)}")
            return 'Unknown'
        return sector
    except Exception as e:
        logger.warning(f"Failed to get sector for {ticker}: {e}")
        return 'Unknown'

def get_current_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        price = info.get('regularMarketPrice', info.get('currentPrice', None))
        if price is None:
            raise ValueError(f"No price data for {ticker}")
        if not isinstance(price, (int, float)):
            logger.warning(f"Invalid price type for {ticker}: {type(price)}")
            return None
        return float(price)
    except Exception as e:
        logger.warning(f"Failed to get price for {ticker}: {e}")
        return None

def get_intraday_prices(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1d", interval="5m")
        if hist.empty:
            return [], []
        prices = hist['Close'].tolist()
        timestamps = [str(t)[-8:-3] for t in hist.index]  # HH:MM format
        if not all(isinstance(p, (int, float)) for p in prices):
            logger.warning(f"Invalid price data types in intraday prices for {ticker}")
            return [], []
        return prices, timestamps
    except Exception as e:
        logger.warning(f"Failed to get intraday prices for {ticker}: {e}")
        return [], []

def get_portfolio_stats():
    try:
        conn = sqlite3.connect('portfolio.db')
        c = conn.cursor()
        c.execute('SELECT ticker, shares, purchase_price FROM holdings')
        holdings = c.fetchall()
        conn.close()

        total_value = 0
        sector_values = {}
        gains_losses = {}
        current_prices = {}
        chart_data = {'labels': [], 'values': [], 'colors': []}
        colors = ['#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', '#FF9F40', '#C9CBCF', '#7BC225']

        for ticker, shares, purchase_price in holdings:
            try:
                current_price = get_current_price(ticker)
                if current_price is None:
                    continue
                current_prices[ticker] = current_price
                value = shares * current_price
                total_value += value
                sector = get_sector(ticker)
                sector_values[sector] = sector_values.get(sector, 0) + value
                gain_loss = (current_price - purchase_price) * shares
                gains_losses[ticker] = gain_loss
            except Exception as e:
                logger.warning(f"Error processing {ticker}: {e}")
                continue

        for sector, value in sector_values.items():
            if not isinstance(value, (int, float)):
                logger.error(f"Non-serializable sector value for {sector}: {value} (type: {type(value)})")
                continue
            chart_data['labels'].append(sector)
            chart_data['values'].append(float(value))  # Ensure float
            chart_data['colors'].append(colors[len(chart_data['labels']) % len(colors)])

        sector_percentages = {k: (v / total_value * 100) if total_value > 0 else 0 for k, v in sector_values.items()}
        logger.info(f"Chart data: {chart_data}")
        return total_value, sector_percentages, gains_losses, holdings, current_prices, chart_data
    except sqlite3.Error as e:
        logger.error(f"Database error in get_portfolio_stats: {e}")
        return 0, {}, {}, [], {}, {'labels': [], 'values': [], 'colors': []}

def get_popular_stocks():
    popular_tickers = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA', 'META', 'JPM', 'WMT', 'V']
    stock_data = []
    for ticker in popular_tickers:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            price = info.get('regularMarketPrice', info.get('currentPrice', 'N/A'))
            change = info.get('regularMarketChangePercent', 'N/A')
            if change != 'N/A':
                change = float(change)
            if price != 'N/A':
                price = float(price)
            stock_data.append({
                'ticker': ticker,
                'name': info.get('shortName', 'Unknown'),
                'price': price,
                'change': change,
                'volume': info.get('regularMarketVolume', 'N/A')
            })
        except Exception as e:
            logger.warning(f"Error fetching data for {ticker}: {e}")
            stock_data.append({
                'ticker': ticker,
                'name': 'Unknown',
                'price': 'N/A',
                'change': 'N/A',
                'volume': 'N/A'
            })
    return stock_data

@app.route('/')
def index():
    try:
        greeting, time_of_day = get_daytime_greeting()
        try:
            conn = sqlite3.connect('portfolio.db')
            c = conn.cursor()
            c.execute('SELECT content, posted_by, posted_at FROM messages ORDER BY posted_at DESC LIMIT 5')
            messages = c.fetchall()
            conn.close()
        except sqlite3.Error as e:
            logger.error(f"Error fetching messages: {e}")
            messages = []
            flash("Error loading messages.", 'danger')
        total_value, sector_percentages, gains_losses, holdings, current_prices, chart_data = get_portfolio_stats()
        return render_template('index.html', greeting=greeting, time_of_day=time_of_day, messages=messages,
                               total_value=total_value, sectors=sector_percentages, gains_losses=gains_losses,
                               holdings=holdings, current_prices=current_prices, chart_data=chart_data)
    except Exception as e:
        logger.error(f"Error in index route: {e}")
        flash("Error loading home page.", 'danger')
        return redirect(url_for('index'))

@app.route('/api/prices')
def api_prices():
    try:
        conn = sqlite3.connect('portfolio.db')
        c = conn.cursor()
        c.execute('SELECT ticker FROM holdings')
        holdings = [row[0] for row in c.fetchall()]
        conn.close()

        popular_tickers = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA', 'META', 'JPM', 'WMT', 'V']
        prices = {}
        for ticker in set(holdings + popular_tickers):
            price = get_current_price(ticker)
            prices[ticker] = price if price is not None else 'N/A'
        return jsonify(prices)
    except Exception as e:
        logger.error(f"Error in /api/prices: {e}")
        return jsonify({'error': 'Failed to fetch prices'}), 500

@app.route('/api/intraday/<ticker>')
def api_intraday(ticker):
    try:
        prices, timestamps = get_intraday_prices(ticker.upper())
        if not prices:
            return jsonify({'error': 'No intraday data available'}), 500
        return jsonify({'labels': timestamps, 'values': prices})
    except Exception as e:
        logger.error(f"Error in /api/intraday/{ticker}: {e}")
        return jsonify({'error': 'Failed to fetch intraday data'}), 500

@app.route('/add_stock', methods=['GET', 'POST'])
def add_stock():
    if request.method == 'POST':
        try:
            password = request.form.get('password', '')
            if hashlib.sha256(password.encode()).hexdigest() != EDIT_PASSWORD_HASH:
                flash("Incorrect password.", 'danger')
                return redirect(url_for('add_stock'))

            ticker = request.form.get('ticker', '').upper().strip()
            shares = request.form.get('shares', '')
            notes = request.form.get('notes', '')

            if not ticker or not shares:
                flash("Ticker and shares are required.", 'danger')
                return redirect(url_for('add_stock'))

            try:
                shares = float(shares)
                if shares <= 0:
                    flash("Shares must be positive.", 'danger')
                    return redirect(url_for('add_stock'))
            except ValueError:
                flash("Invalid number of shares.", 'danger')
                return redirect(url_for('add_stock'))

            purchase_price = get_current_price(ticker)
            if purchase_price is None:
                flash(f"Invalid ticker '{ticker}' or no market price available.", 'danger')
                return redirect(url_for('add_stock'))

            date = datetime.now().strftime('%Y-%m-%d')
            try:
                conn = sqlite3.connect('portfolio.db')
                c = conn.cursor()
                c.execute('INSERT OR REPLACE INTO holdings (ticker, shares, purchase_price, purchase_date) VALUES (?, ?, ?, ?)',
                          (ticker, shares, purchase_price, date))
                c.execute('INSERT INTO transactions (ticker, action, shares, price, date, notes) VALUES (?, ?, ?, ?, ?, ?)',
                          (ticker, 'BUY', shares, purchase_price, date, notes))
                conn.commit()
                flash(f"Successfully added {ticker} at ${purchase_price:.2f}!", 'success')
            except sqlite3.Error as e:
                logger.error(f"Database error adding {ticker}: {e}")
                flash("Database error occurred. Please try again.", 'danger')
                return redirect(url_for('add_stock'))
            finally:
                conn.close()
            return redirect(url_for('index'))
        except Exception as e:
            logger.error(f"Unexpected error adding stock {ticker}: {e}")
            flash(f"Error adding stock: {str(e)}", 'danger')
            return redirect(url_for('add_stock'))
    return render_template('add_stock.html')

@app.route('/remove_stock', methods=['POST'])
def remove_stock():
    try:
        password = request.form.get('password', '')
        if hashlib.sha256(password.encode()).hexdigest() != EDIT_PASSWORD_HASH:
            flash("Incorrect password.", 'danger')
            return redirect(url_for('add_stock'))

        ticker = request.form.get('ticker', '').upper().strip()
        notes = request.form.get('notes', '')

        if not ticker:
            flash("Ticker is required.", 'danger')
            return redirect(url_for('index'))

        try:
            conn = sqlite3.connect('portfolio.db')
            c = conn.cursor()
            c.execute('SELECT shares, purchase_price FROM holdings WHERE ticker = ?', (ticker,))
            result = c.fetchone()
            if not result:
                flash(f"Ticker '{ticker}' not found in portfolio.", 'danger')
                return redirect(url_for('index'))

            shares, purchase_price = result
            c.execute('INSERT INTO transactions (ticker, action, shares, price, date, notes) VALUES (?, ?, ?, ?, ?, ?)',
                      (ticker, 'SELL', shares, purchase_price, datetime.now().strftime('%Y-%m-%d'), notes))
            c.execute('DELETE FROM holdings WHERE ticker = ?', (ticker,))
            conn.commit()
            flash(f"Successfully removed {ticker} from portfolio!", 'success')
        except sqlite3.Error as e:
            logger.error(f"Database error removing {ticker}: {e}")
            flash("Database error occurred. Please try again.", 'danger')
        finally:
            conn.close()
        return redirect(url_for('index'))
    except Exception as e:
        logger.error(f"Unexpected error removing stock {ticker}: {e}")
        flash(f"Error removing stock: {str(e)}", 'danger')
        return redirect(url_for('index'))

@app.route('/update_shares', methods=['POST'])
def update_shares():
    try:
        password = request.form.get('password', '')
        if hashlib.sha256(password.encode()).hexdigest() != EDIT_PASSWORD_HASH:
            flash("Incorrect password.", 'danger')
            return redirect(url_for('add_stock'))

        ticker = request.form.get('ticker', '').upper().strip()
        shares_change = request.form.get('shares_change', '')
        notes = request.form.get('notes', '')

        if not ticker or not shares_change:
            flash("Ticker and shares change are required.", 'danger')
            return redirect(url_for('index'))

        try:
            shares_change = float(shares_change)
        except ValueError:
            flash("Invalid shares change value.", 'danger')
            return redirect(url_for('index'))

        try:
            conn = sqlite3.connect('portfolio.db')
            c = conn.cursor()
            c.execute('SELECT shares FROM holdings WHERE ticker = ?', (ticker,))
            result = c.fetchone()
            if not result:
                flash(f"Ticker '{ticker}' not found in portfolio.", 'danger')
                return redirect(url_for('index'))

            current_shares = result[0]
            new_shares = current_shares + shares_change
            action = 'BUY' if shares_change > 0 else 'SELL'
            current_price = get_current_price(ticker) or 0

            if new_shares < 0:
                flash("Cannot reduce shares below zero.", 'danger')
                return redirect(url_for('index'))
            elif new_shares == 0:
                c.execute('DELETE FROM holdings WHERE ticker = ?', (ticker,))
            else:
                c.execute('UPDATE holdings SET shares = ? WHERE ticker = ?', (new_shares, ticker))
            c.execute('INSERT INTO transactions (ticker, action, shares, price, date, notes) VALUES (?, ?, ?, ?, ?, ?)',
                      (ticker, action, abs(shares_change), current_price, datetime.now().strftime('%Y-%m-%d'), notes))
            conn.commit()
            flash(f"Successfully updated shares for {ticker}!", 'success')
        except sqlite3.Error as e:
            logger.error(f"Database error updating {ticker}: {e}")
            flash("Database error occurred. Please try again.", 'danger')
        finally:
            conn.close()
        return redirect(url_for('index'))
    except Exception as e:
        logger.error(f"Unexpected error updating shares for {ticker}: {e}")
        flash(f"Error updating shares: {str(e)}", 'danger')
        return redirect(url_for('index'))

@app.route('/transactions')
def transactions():
    try:
        conn = sqlite3.connect('portfolio.db')
        c = conn.cursor()
        c.execute('SELECT ticker, action, shares, price, date, notes FROM transactions ORDER BY date DESC')
        transactions = c.fetchall()
        conn.close()
        return render_template('transactions.html', transactions=transactions)
    except sqlite3.Error as e:
        logger.error(f"Database error fetching transactions: {e}")
        flash("Error loading transactions.", 'danger')
        return redirect(url_for('index'))

@app.route('/recaps', methods=['GET', 'POST'])
def recaps():
    if request.method == 'POST':
        try:
            password = request.form.get('password', '')
            if hashlib.sha256(password.encode()).hexdigest() != EDIT_PASSWORD_HASH:
                flash("Incorrect password.", 'danger')
                return redirect(url_for('recaps'))

            title = request.form.get('title', '').strip()
            content = request.form.get('content', '').strip()
            if not title or not content:
                flash("Title and content are required.", 'danger')
                return redirect(url_for('recaps'))
            posted_by = 'Club Head'
            posted_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            try:
                conn = sqlite3.connect('portfolio.db')
                c = conn.cursor()
                c.execute('INSERT INTO recaps (title, content, posted_by, posted_at) VALUES (?, ?, ?, ?)',
                          (title, content, posted_by, posted_at))
                conn.commit()
                flash("Recap added successfully!", 'success')
            except sqlite3.Error as e:
                logger.error(f"Database error adding recap: {e}")
                flash("Database error occurred. Please try again.", 'danger')
            finally:
                conn.close()
            return redirect(url_for('recaps'))
        except Exception as e:
            logger.error(f"Unexpected error adding recap: {e}")
            flash(f"Error adding recap: {str(e)}", 'danger')
            return redirect(url_for('recaps'))
    try:
        conn = sqlite3.connect('portfolio.db')
        c = conn.cursor()
        c.execute('SELECT title, content, posted_by, posted_at FROM recaps ORDER BY posted_at DESC')
        recaps = c.fetchall()
        conn.close()
        return render_template('recaps.html', recaps=recaps)
    except sqlite3.Error as e:
        logger.error(f"Error fetching recaps: {e}")
        flash("Error loading recaps.", 'danger')
        return redirect(url_for('index'))

@app.route('/notices', methods=['GET', 'POST'])
def notices():
    if request.method == 'POST':
        try:
            password = request.form.get('password', '')
            if hashlib.sha256(password.encode()).hexdigest() != EDIT_PASSWORD_HASH:
                flash("Incorrect password.", 'danger')
                return redirect(url_for('notices'))

            content = request.form.get('content', '').strip()
            if not content:
                flash("Notice content is required.", 'danger')
                return redirect(url_for('notices'))
            posted_by = 'Club Head'
            posted_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            try:
                conn = sqlite3.connect('portfolio.db')
                c = conn.cursor()
                c.execute('INSERT INTO notices (content, posted_by, posted_at) VALUES (?, ?, ?)',
                          (content, posted_by, posted_at))
                conn.commit()
                flash("Notice posted successfully!", 'success')
            except sqlite3.Error as e:
                logger.error(f"Database error adding notice: {e}")
                flash("Database error occurred. Please try again.", 'danger')
            finally:
                conn.close()
            return redirect(url_for('notices'))
        except Exception as e:
            logger.error(f"Unexpected error adding notice: {e}")
            flash(f"Error adding notice: {str(e)}", 'danger')
            return redirect(url_for('notices'))
    try:
        conn = sqlite3.connect('portfolio.db')
        c = conn.cursor()
        c.execute('SELECT content, posted_by, posted_at FROM notices ORDER BY posted_at DESC')
        notices = c.fetchall()
        conn.close()
        return render_template('notices.html', notices=notices)
    except sqlite3.Error as e:
        logger.error(f"Error fetching notices: {e}")
        flash("Error loading notices.", 'danger')
        return redirect(url_for('index'))

@app.route('/stocks')
def stocks():
    try:
        stock_data = get_popular_stocks()
        default_ticker = 'AAPL'
        prices, timestamps = get_intraday_prices(default_ticker)
        chart_data = {
            'labels': timestamps,
            'values': prices,
            'ticker': default_ticker
        }
        return render_template('stocks.html', stocks=stock_data, chart_data=chart_data)
    except Exception as e:
        logger.error(f"Error loading stocks page: {e}")
        flash("Error loading stock monitor.", 'danger')
        return redirect(url_for('index'))

@app.route('/about')
def about():
    try:
        club_heads = [
            {'name': 'Gabe Ciminiello', 'role': 'President', 'bio': 'Leading The Hopkins Hedge with a passion for investing.'},
            {'name': 'Arjun Agarwal', 'role': 'Co-President', 'bio': 'Co-leading the club with a focus on strategic portfolio management.'}
        ]
        return render_template('about.html', club_heads=club_heads)
    except Exception as e:
        logger.error(f"Error loading about page: {e}")
        flash("Error loading about page.", 'danger')
        return redirect(url_for('index'))

@app.route('/post_message', methods=['POST'])
def post_message():
    try:
        password = request.form.get('password', '')
        if hashlib.sha256(password.encode()).hexdigest() != EDIT_PASSWORD_HASH:
            flash("Incorrect password.", 'danger')
            return redirect(url_for('index'))

        content = request.form.get('content', '').strip()
        if not content:
            flash("Message content is required.", 'danger')
            return redirect(url_for('index'))
        posted_by = 'Club Head'
        posted_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            conn = sqlite3.connect('portfolio.db')
            c = conn.cursor()
            c.execute('INSERT INTO messages (content, posted_by, posted_at) VALUES (?, ?, ?)',
                      (content, posted_by, posted_at))
            conn.commit()
            flash("Message posted successfully!", 'success')
        except sqlite3.Error as e:
            logger.error(f"Database error posting message: {e}")
            flash("Database error occurred. Please try again.", 'danger')
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Unexpected error posting message: {e}")
        flash(f"Error posting message: {str(e)}", 'danger')
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)