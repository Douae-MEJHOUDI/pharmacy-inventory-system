import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
import hashlib

DB_PATH = Path(__file__).parent.parent / 'database' / 'pharmacy.db'

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database with tables"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT DEFAULT 'pharmacist',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Medicines table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS medicines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            generic_name TEXT,
            dosage TEXT,
            form TEXT,
            manufacturer TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Inventory batches table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventory_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medicine_id INTEGER NOT NULL,
            batch_number TEXT NOT NULL,
            expiry_date DATE NOT NULL,
            quantity INTEGER NOT NULL,
            original_quantity INTEGER NOT NULL,
            unit_price REAL DEFAULT 0,
            price REAL,
            supplier TEXT,
            receipt_date DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (medicine_id) REFERENCES medicines(id)
        )
    ''')
    
    # Sales table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            medicine_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            sale_price REAL,
            pharmacist_id INTEGER NOT NULL,
            sale_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (batch_id) REFERENCES inventory_batches(id),
            FOREIGN KEY (medicine_id) REFERENCES medicines(id),
            FOREIGN KEY (pharmacist_id) REFERENCES users(id)
        )
    ''')
    
    # Create default admin user
    password_hash = hashlib.sha256('admin123'.encode()).hexdigest()
    cursor.execute('''
        INSERT OR IGNORE INTO users (username, password_hash, full_name, role)
        VALUES (?, ?, ?, ?)
    ''', ('admin', password_hash, 'Administrator', 'admin'))
    
    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH}")

def hash_password(password):
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_user(username, password):
    """Verify user credentials"""
    conn = get_db()
    cursor = conn.cursor()
    
    password_hash = hash_password(password)
    cursor.execute('''
        SELECT id, username, full_name, role 
        FROM users 
        WHERE username = ? AND password_hash = ?
    ''', (username, password_hash))
    
    user = cursor.fetchone()
    conn.close()
    
    if user:
        return dict(user)
    return None

def add_medicine(name, generic_name='', dosage='', form='', manufacturer=''):
    """Add a new medicine or return existing one"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Check if medicine exists
    cursor.execute('SELECT id FROM medicines WHERE name = ?', (name,))
    existing = cursor.fetchone()
    
    if existing:
        conn.close()
        return existing['id']
    
    # Add new medicine
    cursor.execute('''
        INSERT INTO medicines (name, generic_name, dosage, form, manufacturer)
        VALUES (?, ?, ?, ?, ?)
    ''', (name, generic_name, dosage, form, manufacturer))
    
    medicine_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return medicine_id

def add_inventory_batch(medicine_id, batch_number, expiry_date, quantity, price=0, unit_price=0, supplier='', receipt_date=None):
    """Add inventory batch"""
    conn = get_db()
    cursor = conn.cursor()

    if not receipt_date:
        receipt_date = datetime.now().strftime('%Y-%m-%d')

    # If unit_price is not provided, use price; otherwise use unit_price
    if unit_price == 0 and price > 0:
        unit_price = price

    cursor.execute('''
        INSERT INTO inventory_batches
        (medicine_id, batch_number, expiry_date, quantity, original_quantity, unit_price, price, supplier, receipt_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (medicine_id, batch_number, expiry_date, quantity, quantity, unit_price, price, supplier, receipt_date))

    batch_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return batch_id

def get_inventory_with_expiry():
    """Get all inventory grouped by medicine with expiry information"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT
            m.id as medicine_id,
            m.name,
            m.generic_name,
            m.dosage,
            m.form,
            ib.id as batch_id,
            ib.batch_number,
            ib.expiry_date,
            ib.quantity,
            ib.original_quantity,
            ib.unit_price,
            ib.price,
            ib.supplier,
            ib.receipt_date,
            CAST((julianday(ib.expiry_date) - julianday('now')) AS INTEGER) as days_until_expiry
        FROM medicines m
        LEFT JOIN inventory_batches ib ON m.id = ib.medicine_id
        WHERE ib.quantity > 0
        ORDER BY m.name, ib.expiry_date
    ''')
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

def get_expiring_soon(days=30):
    """Get medicines expiring within specified days (including already expired items)"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT
            m.id as medicine_id,
            m.name,
            m.dosage,
            ib.id as batch_id,
            ib.batch_number,
            ib.expiry_date,
            ib.quantity,
            ib.unit_price,
            CAST((julianday(ib.expiry_date) - julianday('now')) AS INTEGER) as days_until_expiry
        FROM medicines m
        JOIN inventory_batches ib ON m.id = ib.medicine_id
        WHERE ib.quantity > 0
        AND julianday(ib.expiry_date) - julianday('now') <= ?
        ORDER BY days_until_expiry ASC
    ''', (days,))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]

def record_sale(batch_id, quantity, pharmacist_id, sale_price=0):
    """Record a sale and update inventory"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Get batch info
    cursor.execute('SELECT medicine_id, quantity FROM inventory_batches WHERE id = ?', (batch_id,))
    batch = cursor.fetchone()
    
    if not batch:
        conn.close()
        return {'success': False, 'error': 'Batch not found'}
    
    if batch['quantity'] < quantity:
        conn.close()
        return {'success': False, 'error': f'Insufficient stock. Available: {batch["quantity"]}'}
    
    # Record sale
    cursor.execute('''
        INSERT INTO sales (batch_id, medicine_id, quantity, sale_price, pharmacist_id)
        VALUES (?, ?, ?, ?, ?)
    ''', (batch_id, batch['medicine_id'], quantity, sale_price, pharmacist_id))
    
    # Update inventory
    cursor.execute('''
        UPDATE inventory_batches 
        SET quantity = quantity - ?
        WHERE id = ?
    ''', (quantity, batch_id))
    
    conn.commit()
    conn.close()
    
    return {'success': True, 'message': 'Sale recorded successfully'}

def get_medicine_batches(medicine_id):
    """Get all batches for a medicine (FIFO order)"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT
            id as batch_id,
            batch_number,
            expiry_date,
            quantity,
            unit_price,
            price,
            CAST((julianday(expiry_date) - julianday('now')) AS INTEGER) as days_until_expiry
        FROM inventory_batches
        WHERE medicine_id = ? AND quantity > 0
        ORDER BY expiry_date ASC
    ''', (medicine_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

def search_medicines(query):
    """Search medicines by name"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            m.id,
            m.name,
            m.generic_name,
            m.dosage,
            m.form,
            SUM(ib.quantity) as total_quantity
        FROM medicines m
        LEFT JOIN inventory_batches ib ON m.id = ib.medicine_id
        WHERE m.name LIKE ? OR m.generic_name LIKE ?
        GROUP BY m.id
        HAVING total_quantity > 0
    ''', (f'%{query}%', f'%{query}%'))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

def get_dashboard_stats():
    """Get dashboard statistics"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Total medicines
    cursor.execute('SELECT COUNT(DISTINCT medicine_id) as count FROM inventory_batches WHERE quantity > 0')
    total_medicines = cursor.fetchone()['count']
    
    # Total stock value (use unit_price if available, otherwise price)
    cursor.execute('SELECT SUM(quantity * COALESCE(unit_price, price, 0)) as value FROM inventory_batches WHERE quantity > 0')
    total_value = cursor.fetchone()['value'] or 0
    
    # Expiring in 30 days (excluding already expired)
    cursor.execute('''
        SELECT COUNT(*) as count
        FROM inventory_batches
        WHERE quantity > 0
        AND julianday(expiry_date) - julianday('now') <= 30
        AND julianday(expiry_date) - julianday('now') > 0
    ''')
    expiring_30 = cursor.fetchone()['count']

    # Expiring in 7 days (critical)
    cursor.execute('''
        SELECT COUNT(*) as count
        FROM inventory_batches
        WHERE quantity > 0
        AND julianday(expiry_date) - julianday('now') <= 7
        AND julianday(expiry_date) - julianday('now') > 0
    ''')
    expiring_7 = cursor.fetchone()['count']

    # Already expired
    cursor.execute('''
        SELECT COUNT(*) as count
        FROM inventory_batches
        WHERE quantity > 0
        AND julianday(expiry_date) - julianday('now') <= 0
    ''')
    expired = cursor.fetchone()['count']
    
    # Sales today
    cursor.execute('''
        SELECT COUNT(*) as count, SUM(quantity) as total_qty
        FROM sales 
        WHERE DATE(sale_date) = DATE('now')
    ''')
    sales_today = cursor.fetchone()
    
    conn.close()
    
    return {
        'total_medicines': total_medicines,
        'total_value': round(total_value, 2),
        'expiring_30_days': expiring_30,
        'expiring_7_days': expiring_7,
        'expired': expired,
        'sales_today': sales_today['count'] or 0,
        'units_sold_today': sales_today['total_qty'] or 0
    }

def get_sales_history(limit=50):
    """Get recent sales history"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            s.id,
            m.name as medicine_name,
            s.quantity,
            s.sale_price,
            s.sale_date,
            u.full_name as pharmacist_name,
            ib.batch_number
        FROM sales s
        JOIN medicines m ON s.medicine_id = m.id
        JOIN users u ON s.pharmacist_id = u.id
        JOIN inventory_batches ib ON s.batch_id = ib.id
        ORDER BY s.sale_date DESC
        LIMIT ?
    ''', (limit,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

def create_user(username, password, full_name, role='pharmacist'):
    """Create a new user"""
    conn = get_db()
    cursor = conn.cursor()
    
    password_hash = hash_password(password)
    
    try:
        cursor.execute('''
            INSERT INTO users (username, password_hash, full_name, role)
            VALUES (?, ?, ?, ?)
        ''', (username, password_hash, full_name, role))
        
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return {'success': True, 'user_id': user_id}
    except sqlite3.IntegrityError:
        conn.close()
        return {'success': False, 'error': 'Username already exists'}

if __name__ == '__main__':
    init_db()
    print("Database initialized successfully!")
