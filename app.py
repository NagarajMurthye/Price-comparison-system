from flask import Flask, render_template, request, redirect, url_for, session, flash
from bs4 import BeautifulSoup
import requests
import re
import random
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import os
from urllib.parse import quote
import time
from datetime import datetime

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = 'your_secure_secret_key_here_123!'

# Database setup with absolute path
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database.db')

def get_db_connection():
    # Create database directory if it doesn't exist
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                search_query TEXT NOT NULL,
                search_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        conn.commit()
    finally:
        conn.close()

# Initialize database on startup
init_db()

# User Agents
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15'
]

# Routes
@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if not user:
            flash('User not found. Please register first.', 'error')
            return redirect(url_for('register'))
        
        if check_password_hash(user['password'], password):
            session['username'] = username
            session['user_id'] = user['id']
            flash('Login successful!', 'success')
            return redirect(url_for('welcome'))
        else:
            flash('Incorrect password. Please try again.', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if len(username) < 4:
            flash('Username must be at least 4 characters', 'error')
            return redirect(url_for('register'))
        
        if len(password) < 6:
            flash('Password must be at least 6 characters', 'error')
            return redirect(url_for('register'))
        
        conn = get_db_connection()
        try:
            conn.execute(
                'INSERT INTO users (username, password) VALUES (?, ?)',
                (username, generate_password_hash(password, method='pbkdf2:sha256'))
            )
            conn.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username already exists. Please choose another.', 'error')
        finally:
            conn.close()
    
    return render_template('register.html')

@app.route('/welcome')
def welcome():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('welcome.html', username=session['username'])

@app.route('/search', methods=['GET', 'POST'])
def search():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        product = request.form.get('product', '').strip()
        if product:
            return redirect(url_for('results', product=product))
    
    return render_template('search.html')

@app.route('/results')
def results():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    product = request.args.get('product', '').strip()
    if not product:
        return redirect(url_for('search'))
    
    # Save search to history
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO search_history (user_id, search_query) VALUES (?, ?)',
        (session['user_id'], product))
    conn.commit()
    conn.close()
    
    return render_template('results.html',
        product=product,
        amazon_data=scrape_amazon(product),
        snapdeal_data=scrape_snapdeal(product),
        username=session['username']
    )

@app.route('/profile')
def profile():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE username = ?', (session['username'],)).fetchone()
    conn.close()
    
    return render_template('profile.html', username=session['username'])

@app.route('/search-history')
def search_history():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    history = conn.execute(
        'SELECT search_query, search_time FROM search_history WHERE user_id = ? ORDER BY search_time DESC',
        (session['user_id'],)
    ).fetchall()
    conn.close()
    
    return render_template('search_history.html', history=history, username=session['username'])

@app.route('/user-details')
def user_details():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE username = ?', (session['username'],)).fetchone()
    conn.close()
    
    # Ensure we have a join date
    join_date = "Unknown"
    if user and 'created_at' in user:
        try:
            # Handle both string and datetime objects
            if isinstance(user['created_at'], str):
                join_date = datetime.strptime(user['created_at'], '%Y-%m-%d %H:%M:%S').strftime('%B %d, %Y')
            else:
                join_date = user['created_at'].strftime('%B %d, %Y')
        except:
            join_date = "Unknown"
    
    return render_template('user_details.html', 
                         username=session['username'], 
                         join_date=join_date)

@app.route('/clear-history', methods=['POST'])
def clear_history():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    conn.execute('DELETE FROM search_history WHERE user_id = ?', (session['user_id'],))
    conn.commit()
    conn.close()
    
    flash('Search history cleared successfully!', 'success')
    return redirect(url_for('search_history'))

@app.route('/logout')
def logout():
    session.pop('username', None)
    session.pop('user_id', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# Scraping Functions
def get_headers():
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Referer': 'https://www.google.com/',
        'DNT': '1'
    }

def scrape_amazon(query, max_retries=3):
    for attempt in range(max_retries):
        try:
            url = f"https://www.amazon.in/s?k={quote(query)}"
            
            session = requests.Session()
            session.headers.update(get_headers())
            
            # Add delay to avoid blocking
            time.sleep(random.uniform(1, 3))
            
            response = session.get(url, timeout=15)
            response.raise_for_status()
            
            if "api-services-support@amazon.com" in response.text:
                if attempt < max_retries - 1:
                    time.sleep(5)  # Longer delay before retry
                    continue
                return [{'error': 'Amazon requested CAPTCHA. Try again later.'}]
            
            soup = BeautifulSoup(response.text, 'html.parser')
            products = []
            
            # Multiple selector options with fallbacks
            items = soup.find_all('div', {'data-component-type': 's-search-result'})
            if not items:
                items = soup.find_all('div', class_='s-result-item')
            if not items:
                items = soup.find_all('div', class_='sg-col-inner')
            
            for item in items[:3]:  # Limit to 3 results
                try:
                    # Title extraction with multiple fallbacks
                    title = (item.find('h2') or 
                            item.find('span', class_='a-text-normal') or
                            item.find('span', class_='a-size-medium'))
                    title = title.get_text().strip() if title else 'No title'
                    
                    # Price extraction with multiple fallbacks
                    price = (item.find('span', class_='a-price-whole') or 
                            item.find('span', class_='a-offscreen') or
                            item.find('span', class_='a-price'))
                    price = price.get_text().strip() if price else 'Price not available'
                    
                    # Image extraction
                    image = (item.find('img', class_='s-image') or
                            item.find('img', {'src': True}))
                    image_url = image['src'] if image else ''
                    
                    # Link extraction
                    link = (item.find('a', class_='a-link-normal') or
                            item.find('a', href=True))
                    link = 'https://www.amazon.in' + link['href'] if link and link.get('href') else ''
                    
                    # Clean price
                    price = re.sub(r'[^\d.]', '', price)
                    price = f'₹{price}' if price.replace('.', '').isdigit() else price
                    
                    products.append({
                        'title': title[:100] + '...' if len(title) > 100 else title,
                        'price': price,
                        'image_url': image_url,
                        'link': link
                    })
                except Exception as e:
                    print(f"Error processing Amazon product: {e}")
                    continue
            
            return products if products else [{'error': 'No products found on Amazon'}]
        
        except requests.exceptions.RequestException as e:
            print(f"Amazon request error (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return [{'error': 'Failed to fetch Amazon results. Try again.'}]
        except Exception as e:
            print(f"Amazon scrape error (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return [{'error': 'Failed to fetch Amazon results. Try again.'}]

def scrape_snapdeal(query, max_retries=3):
    for attempt in range(max_retries):
        try:
            url = f"https://www.snapdeal.com/search?keyword={quote(query)}&sort=rlvncy"
            
            session = requests.Session()
            session.headers.update(get_headers())
            
            # Add delay to avoid blocking
            time.sleep(random.uniform(1, 2))
            
            response = session.get(url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            products = []
            
            # Multiple selector options with fallbacks
            items = soup.find_all('div', class_='product-tuple-listing')
            if not items:
                items = soup.find_all('div', class_='product-desc-rating')
            if not items:
                items = soup.find_all('div', class_='product-tuple-description')
            
            for item in items[:3]:
                try:
                    # Title extraction with fallbacks
                    title = (item.find('p', class_='product-title') or
                            item.find('div', class_='product-title') or
                            item.find('span', class_='product-title'))
                    title = title.get_text().strip() if title else 'No title'
                    
                    # Price extraction with fallbacks
                    price = (item.find('span', class_='product-price') or
                            item.find('span', class_='lfloat product-price') or
                            item.find('span', class_='lfloat'))
                    price = price.get_text().strip() if price else 'Price not available'
                    
                    # Image extraction
                    image = (item.find('img', class_='product-image') or
                            item.find('img', {'src': True}))
                    image_url = image['src'] if image else ''
                    
                    # Link extraction
                    link = (item.find('a', class_='dp-widget-link') or
                            item.find('a', href=True))
                    link = link['href'] if link and link.get('href') else ''
                    
                    # Clean price
                    price = re.sub(r'[^\d.]', '', price)
                    price = f'₹{price}' if price.replace('.', '').isdigit() else price
                    
                    products.append({
                        'title': title[:100] + '...' if len(title) > 100 else title,
                        'price': price,
                        'image_url': image_url,
                        'link': link
                    })
                except Exception as e:
                    print(f"Error processing Snapdeal product: {e}")
                    continue
            
            return products if products else [{'error': 'No products found on Snapdeal'}]
        
        except requests.exceptions.RequestException as e:
            print(f"Snapdeal request error (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return [{'error': 'Failed to fetch Snapdeal results. Try again.'}]
        except Exception as e:
            print(f"Snapdeal scrape error (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return [{'error': 'Failed to fetch Snapdeal results. Try again.'}]

if __name__ == '__main__':
    # Create necessary folders
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    
    # Run the app
    app.run(debug=True, port=5000)