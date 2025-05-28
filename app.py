from flask import Flask, render_template, request, redirect, url_for, flash
import yfinance as yf
import sqlite3
from datetime import datetime
import pandas as pd
import logging

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Replace with a secure key for production

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
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database initialization failed: {e}")
        raise
    finally:
        conn.close()

def get_sector(ticker):
    try:
        stock = yf.Ticker(ticker)
        return stock.info.get('sector', 'Unknown')
    except Exception as e:
        logger.warning(f"Failed to get sector for {ticker}: {e}")
        return 'Unknown'

def get_current_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        price = stock.info.get('regularMarketPrice', None)
        if price is None:
            raise ValueError(f"No regularMarketPrice for {ticker}")
        return price
    except Exception as e:
        logger.warning(f"Failed to get price for {ticker}: {e}")
        return None

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

        sector_percentages = {k: (v / total_value * 100) if total_value > 0 else 0 for k, v in sector_values.items()}
        return total_value, sector_percentages, gains_losses, holdings, current_prices
    except sqlite3.Error as e:
        logger.error(f"Database error in get_portfolio_stats: {e}")
        return 0, {}, {}, [], {}

@app.route('/')
def index():
    total_value, sector_percentages, gains_losses, holdings, current_prices = get_portfolio_stats()
    return render_template('index.html', total_value=total_value, sectors=sector_percentages,
                           gains_losses=gains_losses, holdings=holdings, current_prices=current_prices)

@app.route('/add_stock', methods=['GET', 'POST'])
def add_stock():
    if request.method == 'POST':
        try:
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
            except sqlite3.Error as e:
                logger.error(f"Database error adding {ticker}: {e}")
                flash("Database error occurred. Please try again.", 'danger')
                return redirect(url_for('add_stock'))
            finally:
                conn.close()

            flash(f"Successfully added {ticker} at ${purchase_price:.2f}!", 'success')
            return redirect(url_for('index'))
        except Exception as e:
            logger.error(f"Unexpected error adding stock {ticker}: {e}")
            flash(f"Error adding stock: {str(e)}", 'danger')
            return redirect(url_for('add_stock'))
    return render_template('add_stock.html')

@app.route('/remove_stock', methods=['POST'])
def remove_stock():
    try:
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

if __name__ == '__main__':
    init_db()
    app.run(debug=True)