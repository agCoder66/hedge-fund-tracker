from flask import Flask, render_template, request, redirect, url_for, flash
import yfinance as yf
import sqlite3
from datetime import datetime
import pandas as pd
import logging

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Needed for flash messages

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    try:
        conn = sqlite3.connect('portfolio.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS holdings
                     (ticker TEXT, shares REAL, purchase_price REAL, purchase_date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS transactions
                     (ticker TEXT, action TEXT, shares REAL, price REAL, date TEXT, notes TEXT)''')
        conn.commit()
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
    finally:
        conn.close()

def get_sector(ticker):
    try:
        stock = yf.Ticker(ticker)
        return stock.info.get('sector', 'Unknown')
    except Exception as e:
        logger.error(f"Failed to get sector for {ticker}: {e}")
        return 'Unknown'

def get_portfolio_stats():
    conn = sqlite3.connect('portfolio.db')
    c = conn.cursor()
    c.execute('SELECT ticker, shares, purchase_price FROM holdings')
    holdings = c.fetchall()
    conn.close()

    total_value = 0
    sector_values = {}
    gains_losses = {}

    for ticker, shares, purchase_price in holdings:
        try:
            stock = yf.Ticker(ticker)
            current_price = stock.info['regularMarketPrice']
            value = shares * current_price
            total_value += value
            sector = get_sector(ticker)
            sector_values[sector] = sector_values.get(sector, 0) + value
            gain_loss = (current_price - purchase_price) * shares
            gains_losses[ticker] = gain_loss
        except Exception as e:
            logger.error(f"Error processing {ticker}: {e}")
            continue

    sector_percentages = {k: (v / total_value * 100) if total_value > 0 else 0 for k, v in sector_values.items()}
    return total_value, sector_percentages, gains_losses, holdings

@app.route('/')
def index():
    total_value, sector_percentages, gains_losses, holdings = get_portfolio_stats()
    return render_template('index.html', total_value=total_value, sectors=sector_percentages,
                           gains_losses=gains_losses, holdings=holdings)

@app.route('/add_stock', methods=['GET', 'POST'])
def add_stock():
    if request.method == 'POST':
        try:
            ticker = request.form['ticker'].upper()
            shares = float(request.form['shares'])
            notes = request.form['notes']
            date = datetime.now().strftime('%Y-%m-%d')

            # Fetch current market price
            stock = yf.Ticker(ticker)
            if 'regularMarketPrice' not in stock.info:
                flash(f"Error: Invalid ticker '{ticker}' or no market price available.", 'danger')
                return redirect(url_for('add_stock'))
            purchase_price = stock.info['regularMarketPrice']

            conn = sqlite3.connect('portfolio.db')
            c = conn.cursor()
            c.execute('INSERT INTO holdings (ticker, shares, purchase_price, purchase_date) VALUES (?, ?, ?, ?)',
                      (ticker, shares, purchase_price, date))
            c.execute('INSERT INTO transactions (ticker, action, shares, price, date, notes) VALUES (?, ?, ?, ?, ?, ?)',
                      (ticker, 'BUY', shares, purchase_price, date, notes))
            conn.commit()
            conn.close()
            flash(f"Successfully added {ticker} to portfolio!", 'success')
            return redirect(url_for('index'))
        except Exception as e:
            logger.error(f"Error adding stock {ticker}: {e}")
            flash(f"Error adding stock: {str(e)}", 'danger')
            return redirect(url_for('add_stock'))
    return render_template('add_stock.html')

@app.route('/remove_stock', methods=['POST'])
def remove_stock():
    try:
        ticker = request.form['ticker'].upper()
        notes = request.form['notes']
        date = datetime.now().strftime('%Y-%m-%d')

        conn = sqlite3.connect('portfolio.db')
        c = conn.cursor()
        c.execute('SELECT shares, purchase_price FROM holdings WHERE ticker = ?', (ticker,))
        result = c.fetchone()
        if result:
            shares, purchase_price = result
            c.execute('INSERT INTO transactions (ticker, action, shares, price, date, notes) VALUES (?, ?, ?, ?, ?, ?)',
                      (ticker, 'SELL', shares, purchase_price, date, notes))
            c.execute('DELETE FROM holdings WHERE ticker = ?', (ticker,))
            conn.commit()
            flash(f"Successfully removed {ticker} from portfolio!", 'success')
        else:
            flash(f"Error: Ticker '{ticker}' not found in portfolio.", 'danger')
        conn.close()
        return redirect(url_for('index'))
    except Exception as e:
        logger.error(f"Error removing stock {ticker}: {e}")
        flash(f"Error removing stock: {str(e)}", 'danger')
        return redirect(url_for('index'))

@app.route('/update_shares', methods=['POST'])
def update_shares():
    try:
        ticker = request.form['ticker'].upper()
        shares_change = float(request.form['shares_change'])
        notes = request.form['notes']
        date = datetime.now().strftime('%Y-%m-%d')

        conn = sqlite3.connect('portfolio.db')
        c = conn.cursor()
        c.execute('SELECT shares FROM holdings WHERE ticker = ?', (ticker,))
        result = c.fetchone()
        if result:
            current_shares = result[0]
            new_shares = current_shares + shares_change
            action = 'BUY' if shares_change > 0 else 'SELL'
            try:
                current_price = yf.Ticker(ticker).info['regularMarketPrice']
            except:
                current_price = 0
            if new_shares <= 0:
                c.execute('DELETE FROM holdings WHERE ticker = ?', (ticker,))
            else:
                c.execute('UPDATE holdings SET shares = ? WHERE ticker = ?', (new_shares, ticker))
            c.execute('INSERT INTO transactions (ticker, action, shares, price, date, notes) VALUES (?, ?, ?, ?, ?, ?)',
                      (ticker, action, abs(shares_change), current_price, date, notes))
            conn.commit()
            flash(f"Successfully updated shares for {ticker}!", 'success')
        else:
            flash(f"Error: Ticker '{ticker}' not found in portfolio.", 'danger')
        conn.close()
        return redirect(url_for('index'))
    except Exception as e:
        logger.error(f"Error updating shares for {ticker}: {e}")
        flash(f"Error updating shares: {str(e)}", 'danger')
        return redirect(url_for('index'))

@app.route('/transactions')
def transactions():
    conn = sqlite3.connect('portfolio.db')
    c = conn.cursor()
    c.execute('SELECT ticker, action, shares, price, date, notes FROM transactions ORDER BY date DESC')
    transactions = c.fetchall()
    conn.close()
    return render_template('transactions.html', transactions=transactions)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)



## Hopkins Hedge Portfolio

# Key Features:

# Yahoo Finance API for real time monitoring of stock prices

# Ability to buy/sell stocks and shares

# Allow viewers to see key stats like portfolio value, percent invested in sectors, stocks, what we’ve lost/gained money on, what the vote results were

# Updated based on club’s decisions during meetings

# Future possibilities:

# Stock of the day to buy/sell?

# Monitor market and email club members daily updates