import sqlite3

# Создание баз данных
def create_databases():
    # Создание первой базы данных
    conn = sqlite3.connect('../database/users.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        wallet_address TEXT,
        payment_status TEXT,
        ton_amount REAL,
        address TEXT,
        size TEXT
    )
    ''')
    conn.commit()
    conn.close()

    # Создание второй базы данных
    conn = sqlite3.connect('../database/transactions.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS transactions (
        hash TEXT PRIMARY KEY,
        comment TEXT,
        flag INTEGER
    )
    ''')
    conn.commit()
    conn.close()

    # Создание третьей базы данных
    conn = sqlite3.connect('../database/inventory.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS inventory (
        size TEXT PRIMARY KEY,
        quantity INTEGER
    )
    ''')
    cursor.execute('''
    INSERT OR IGNORE INTO inventory (size, quantity) VALUES ('M', 300), ('L', 300)
    ''')
    conn.commit()
    conn.close()

    # Создание базы данных заказов
    conn = sqlite3.connect('../database/orders.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS orders (
        telegram_id INTEGER,
        username TEXT,
        address TEXT,
        size TEXT
    )
    ''')
    conn.commit()
    conn.close()

def add_user(telegram_id, username):
    conn = sqlite3.connect('../database/users.db')
    cursor = conn.cursor()
    cursor.execute('''
    INSERT OR IGNORE INTO users (telegram_id, username) VALUES (?, ?)
    ''', (telegram_id, username))
    conn.commit()
    conn.close()

def update_wallet_address(telegram_id, wallet_address):
    conn = sqlite3.connect('../database/users.db')
    cursor = conn.cursor()
    cursor.execute('''
    UPDATE users SET wallet_address = ? WHERE telegram_id = ?
    ''', (wallet_address, telegram_id))
    conn.commit()
    conn.close()

def update_order_address(telegram_id, new_address):
    conn = sqlite3.connect('../database/orders.db')
    cursor = conn.cursor()
    cursor.execute('''
    UPDATE orders SET address = ? WHERE telegram_id = ?
    ''', (new_address, telegram_id))
    conn.commit()
    conn.close()


def add_transaction(hash, comment):
    conn = sqlite3.connect('../database/transactions.db')
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO transactions (hash, comment, flag) VALUES (?, ?, 0)
    ''', (hash, comment))
    conn.commit()
    conn.close()

def update_transaction_flag(hash):
    conn = sqlite3.connect('../database/transactions.db')
    cursor = conn.cursor()
    cursor.execute('''
    UPDATE transactions SET flag = 1 WHERE hash = ?
    ''', (hash,))
    conn.commit()
    conn.close()

def update_user_address(telegram_id, address):
    conn = sqlite3.connect('../database/users.db')
    cursor = conn.cursor()
    cursor.execute('''
    UPDATE users SET address = ? WHERE telegram_id = ?
    ''', (address, telegram_id))
    conn.commit()
    conn.close()

def update_user_payment_status(telegram_id, status, ton_amount):
    conn = sqlite3.connect('../database/users.db')
    cursor = conn.cursor()
    cursor.execute('''
    UPDATE users SET payment_status = ?, ton_amount = ? WHERE telegram_id = ?
    ''', (status, ton_amount, telegram_id))
    conn.commit()
    conn.close()

def update_inventory(size, quantity):
    conn = sqlite3.connect('../database/inventory.db')
    cursor = conn.cursor()
    cursor.execute('''
    UPDATE inventory SET quantity = ? WHERE size = ?
    ''', (quantity, size))
    conn.commit()
    conn.close()

def update_user_size(telegram_id, size):
    conn = sqlite3.connect('../database/users.db')
    cursor = conn.cursor()
    cursor.execute('''
    UPDATE users SET size = ? WHERE telegram_id = ?
    ''', (size, telegram_id))
    conn.commit()
    conn.close()

def add_order(telegram_id, username, address, size):
    conn = sqlite3.connect('../database/orders.db')
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO orders (telegram_id, username, address, size) VALUES (?, ?, ?, ?)
    ''', (telegram_id, username, address, size))
    conn.commit()
    conn.close()
