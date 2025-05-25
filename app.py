from flask import Flask, render_template, request, redirect, url_for
import yfinance as yf
import sqlite3
from datetime import datetime
import pandas as pd

app = Flask(__name__)

# Initialize SQLite database
def init_db():
    conn = sqlite3.connect('portfolio.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS holdings
                 (ticker TEXT, shares REAL, purchase_price REAL, purchase_date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions
                 (ticker TEXT, action TEXT, shares REAL, price REAL, date TEXT, notes TEXT)''')
    conn.commit()
    conn.close()

# Call init_db() when the app starts
init_db()  # <--- Added to ensure database is initialized in production

def get_sector(ticker):
    try:
        stock = yf.Ticker(ticker)
        return stock.info.get('sector', 'Unknown')
    except:
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
        except:
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
        ticker = request.form['ticker'].upper()
        shares = float(request.form['shares'])
        purchase_price = float(request.form['purchase_price'])
        notes = request.form['notes']
        date = datetime.now().strftime('%Y-%m-%d')

        conn = sqlite3.connect('portfolio.db')
        c = conn.cursor()
        c.execute('INSERT INTO holdings (ticker, shares, purchase_price, purchase_date) VALUES (?, ?, ?, ?)',
                  (ticker, shares, purchase_price, date))
        c.execute('INSERT INTO transactions (ticker, action, shares, price, date, notes) VALUES (?, ?, ?, ?, ?, ?)',
                  (ticker, 'BUY', shares, purchase_price, date, notes))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))
    return render_template('add_stock.html')

@app.route('/remove_stock', methods=['POST'])
def remove_stock():
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
    conn.close()
    return redirect(url_for('index'))

@app.route('/update_shares', methods=['POST'])
def update_shares():
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
    conn.close()
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
    app.run(debug=True)
