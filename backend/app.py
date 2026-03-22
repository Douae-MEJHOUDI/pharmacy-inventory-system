from flask import Flask, request, jsonify, session, send_from_directory
from flask_cors import CORS
import pytesseract
from PIL import Image
import os
import re
from datetime import datetime
from pathlib import Path
import database as db

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production'
ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]
CORS(app, supports_credentials=True, origins=ALLOWED_ORIGINS)

@app.after_request
def add_cors_headers(response):
    origin = request.headers.get('Origin', '')
    if origin in ALLOWED_ORIGINS:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    return response

UPLOAD_FOLDER = Path(__file__).parent.parent / 'uploads'
UPLOAD_FOLDER.mkdir(exist_ok=True)

FRONTEND_FOLDER = Path(__file__).parent.parent / 'frontend'

# Initialize database
db.init_db()

def extract_text_from_image(image_path):
    """Extract text using OCR"""
    image = Image.open(image_path)
    text = pytesseract.image_to_string(image)
    return text

def parse_receipt_data(text):
    """Parse receipt to extract medicine items"""
    lines = text.split('\n')
    items = []

    for line in lines:
        line = line.strip()
        if not line or len(line) < 5:
            continue

        if any(word in line.lower() for word in ['pharmacy', 'pharmacie', 'total', 'thank', 'merci', 'receipt', 'reçu', 'date:', 'tel:', 'tél:', 'contact:', 'avenue', 'boulevard', 'rue', 'conservez']):
            continue

        if any(char.isdigit() for char in line) and any(char.isalpha() for char in line):
            item = {
                'raw_text': line,
                'medicine_name': '',
                'quantity': '',
                'batch_number': '',
                'expiry_date': '',
                'unit_price': '',
                'price': ''
            }

            words = line.split()
            name_parts = []
            for word in words:
                if word.replace('.', '').replace(',', '').isalpha() or 'mg' in word.lower() or word.endswith('mg'):
                    name_parts.append(word)
                else:
                    break
            item['medicine_name'] = ' '.join(name_parts)

            qty_match = re.search(r'\b(\d{1,4})\b', line)
            if qty_match:
                item['quantity'] = qty_match.group(1)

            date_patterns = [
                r'\b(\d{2}[/-]\d{4})\b',
                r'\b(\d{2}[/-]\d{2}[/-]\d{4})\b',
                r'\b(\d{4}[/-]\d{2}[/-]\d{2})\b',
            ]
            for pattern in date_patterns:
                date_match = re.search(pattern, line)
                if date_match:
                    date_str = date_match.group(1)
                    if '/' in date_str and len(date_str.split('/')) == 2:
                        mm, yyyy = date_str.split('/')
                        item['expiry_date'] = f"{yyyy}-{mm}-01"
                    else:
                        item['expiry_date'] = date_str
                    break

            price_match = re.search(r'(\d+[.,]\d{2})\s*(?:MAD|DH|Dh|dh)?\s*$', line)
            if price_match:
                unit_price = price_match.group(1).replace(',', '.')
                item['unit_price'] = unit_price
                item['price'] = unit_price

            batch_match = re.search(r'\b([A-Z]{2}\d{3,}|[A-Z]\d{4,})\b', line)
            if batch_match:
                item['batch_number'] = batch_match.group(1)

            if item['medicine_name']:
                items.append(item)

    return items

def parse_prescription_data(text):
    """Parse prescription to extract medicine items and patient info"""
    lines = text.split('\n')
    items = []
    prescription_info = {
        'patient_name': '',
        'doctor_name': '',
        'date': '',
        'doctor_stamp': False
    }

    # Look for patient and doctor info
    for i, line in enumerate(lines):
        line_lower = line.lower().strip()

        # Extract patient name
        if any(keyword in line_lower for keyword in ['patient:', 'nom:', 'name:', 'mr.', 'mrs.', 'mme', 'm.']):
            # Extract name from the line
            name_match = re.search(r'(?:patient:|nom:|name:)?\s*([A-Z][a-zA-Z\s]+)', line, re.IGNORECASE)
            if name_match:
                prescription_info['patient_name'] = name_match.group(1).strip()

        # Extract doctor name
        if any(keyword in line_lower for keyword in ['dr.', 'doctor', 'médecin', 'docteur']):
            name_match = re.search(r'(?:dr\.?|doctor|docteur)\s+([A-Z][a-zA-Z\s]+)', line, re.IGNORECASE)
            if name_match:
                prescription_info['doctor_name'] = name_match.group(1).strip()

        # Extract date
        date_match = re.search(r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', line)
        if date_match and not prescription_info['date']:
            prescription_info['date'] = date_match.group(1)

        # Check for stamp/signature indication
        if any(keyword in line_lower for keyword in ['stamp', 'cachet', 'signature', 'seal']):
            prescription_info['doctor_stamp'] = True

    # Extract prescribed medicines
    for line in lines:
        line = line.strip()
        if not line or len(line) < 3:
            continue

        # Skip header/footer/info lines
        if any(word in line.lower() for word in ['prescription', 'ordonnance', 'patient:', 'doctor:', 'date:', 'signature', 'stamp', 'address', 'tel:', 'clinic', 'hospital', 'hôpital']):
            continue

        # Look for medicine patterns: name + dosage + frequency/duration
        # Example: "Amoxicillin 500mg" or "Paracetamol 1g x 3/day"
        medicine_pattern = r'([A-Z][a-zA-Z]+(?:\s+[A-Z]?[a-z]+)*)\s*(\d+\s*(?:mg|g|ml|mcg))'
        match = re.search(medicine_pattern, line)

        if match or (any(char.isalpha() for char in line) and any(char.isdigit() for char in line)):
            item = {
                'raw_text': line,
                'medicine_name': '',
                'dosage': '',
                'quantity': '30',  # Default quantity
                'frequency': '',
                'duration': '',
                'instructions': ''
            }

            if match:
                item['medicine_name'] = match.group(1).strip()
                item['dosage'] = match.group(2).strip()
            else:
                # Extract medicine name (first capitalized word(s))
                words = line.split()
                name_parts = []
                for word in words[:3]:  # Take first 3 words max
                    if word[0].isupper() or any(x in word.lower() for x in ['mg', 'ml', 'mcg']):
                        name_parts.append(word)
                    else:
                        break
                item['medicine_name'] = ' '.join(name_parts)

            # Extract frequency (x2, x3, 3 times, etc.)
            freq_match = re.search(r'[xX×]\s*(\d+)|(\d+)\s*(?:times?|fois|per day|/day|/jour)', line)
            if freq_match:
                item['frequency'] = freq_match.group(1) or freq_match.group(2)

            # Extract duration (days, weeks)
            duration_match = re.search(r'(\d+)\s*(?:days?|jours?|weeks?|semaines?)', line)
            if duration_match:
                item['duration'] = duration_match.group(0)

            # Extract quantity if specified
            qty_match = re.search(r'(?:qty|quantité|quantity)[\s:]*(\d+)', line, re.IGNORECASE)
            if qty_match:
                item['quantity'] = qty_match.group(1)

            # Store full line as instructions
            item['instructions'] = line

            if item['medicine_name']:
                items.append(item)

    return {
        'prescription_info': prescription_info,
        'medicines': items
    }

@app.route('/api/auth/login', methods=['POST'])
def login():
    """User login"""
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    user = db.verify_user(username, password)
    
    if user:
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['role'] = user['role']
        return jsonify({'success': True, 'user': user})
    
    return jsonify({'success': False, 'error': 'Invalid credentials'}), 401

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """User logout"""
    session.clear()
    return jsonify({'success': True})

@app.route('/api/auth/me', methods=['GET'])
def get_current_user():
    """Get current logged-in user"""
    if 'user_id' in session:
        return jsonify({
            'success': True,
            'user': {
                'id': session['user_id'],
                'username': session['username'],
                'role': session['role']
            }
        })
    return jsonify({'success': False}), 401

@app.route('/api/users/create', methods=['POST'])
def create_user():
    """Create new user (admin only)"""
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    data = request.json
    result = db.create_user(
        username=data['username'],
        password=data['password'],
        full_name=data['full_name'],
        role=data.get('role', 'pharmacist')
    )
    
    return jsonify(result)

@app.route('/api/receipt/upload', methods=['POST'])
def upload_receipt():
    """Upload and process receipt"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400
    
    # Save file
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"receipt_{timestamp}_{file.filename}"
    filepath = UPLOAD_FOLDER / filename
    file.save(filepath)

    raw_text = extract_text_from_image(filepath)
    items = parse_receipt_data(raw_text)

    return jsonify({
        'success': True,
        'raw_text': raw_text,
        'items': items,
        'filename': filename
    })

@app.route('/api/prescription/upload', methods=['POST'])
def upload_prescription():
    """Upload and process prescription"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided'}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    # Save file
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"prescription_{timestamp}_{file.filename}"
    filepath = UPLOAD_FOLDER / filename
    file.save(filepath)

    raw_text = extract_text_from_image(filepath)
    parsed_data = parse_prescription_data(raw_text)

    return jsonify({
        'success': True,
        'prescription_info': parsed_data['prescription_info'],
        'medicines': parsed_data['medicines'],
        'filename': filename
    })

@app.route('/api/inventory/add-batch', methods=['POST'])
def add_batch():
    """Add inventory batch from parsed receipt"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    data = request.json
    
    try:
        # Add or get medicine
        medicine_id = db.add_medicine(
            name=data['medicine_name'],
            generic_name=data.get('generic_name', ''),
            dosage=data.get('dosage', ''),
            form=data.get('form', ''),
            manufacturer=data.get('manufacturer', '')
        )
        
        # Add batch
        unit_price = float(data.get('unit_price', data.get('price', 0)))
        batch_id = db.add_inventory_batch(
            medicine_id=medicine_id,
            batch_number=data['batch_number'],
            expiry_date=data['expiry_date'],
            quantity=int(data['quantity']),
            unit_price=unit_price,
            price=float(data.get('price', 0)),
            supplier=data.get('supplier', ''),
            receipt_date=data.get('receipt_date')
        )
        
        return jsonify({
            'success': True,
            'medicine_id': medicine_id,
            'batch_id': batch_id
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/inventory/batches', methods=['POST'])
def add_multiple_batches():
    """Add multiple batches at once"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    data = request.json
    items = data.get('items', [])
    
    added = 0
    errors = []
    
    for item in items:
        try:
            medicine_id = db.add_medicine(name=item['medicine_name'])

            unit_price = float(item.get('unit_price', item.get('price', 0)))
            db.add_inventory_batch(
                medicine_id=medicine_id,
                batch_number=item.get('batch_number', 'UNKNOWN'),
                expiry_date=item['expiry_date'],
                quantity=int(item['quantity']),
                unit_price=unit_price,
                price=float(item.get('price', 0)),
                supplier=item.get('supplier', '')
            )
            added += 1
        except Exception as e:
            errors.append(f"{item.get('medicine_name', 'Unknown')}: {str(e)}")
    
    return jsonify({
        'success': True,
        'added': added,
        'errors': errors
    })

@app.route('/api/inventory/all', methods=['GET'])
def get_inventory():
    """Get all inventory"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    inventory = db.get_inventory_with_expiry()
    return jsonify({'success': True, 'inventory': inventory})

@app.route('/api/inventory/expiring/<int:days>', methods=['GET'])
def get_expiring(days):
    """Get medicines expiring within days"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    items = db.get_expiring_soon(days)
    return jsonify({'success': True, 'items': items})

@app.route('/api/medicine/search', methods=['GET'])
def search_medicines():
    """Search medicines"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    query = request.args.get('q', '')
    medicines = db.search_medicines(query)
    return jsonify({'success': True, 'medicines': medicines})

@app.route('/api/medicine/<int:medicine_id>/batches', methods=['GET'])
def get_medicine_batches(medicine_id):
    """Get batches for a medicine"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    batches = db.get_medicine_batches(medicine_id)
    return jsonify({'success': True, 'batches': batches})

@app.route('/api/sale/record', methods=['POST'])
def record_sale():
    """Record a sale"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    data = request.json
    
    result = db.record_sale(
        batch_id=data['batch_id'],
        quantity=int(data['quantity']),
        pharmacist_id=session['user_id'],
        sale_price=float(data.get('sale_price', 0))
    )
    
    return jsonify(result)

@app.route('/api/dashboard/stats', methods=['GET'])
def get_dashboard():
    """Get dashboard statistics"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    stats = db.get_dashboard_stats()
    return jsonify({'success': True, 'stats': stats})

@app.route('/api/sales/history', methods=['GET'])
def get_sales():
    """Get sales history"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    limit = request.args.get('limit', 50, type=int)
    sales = db.get_sales_history(limit)
    return jsonify({'success': True, 'sales': sales})

@app.route('/api/health', methods=['GET'])
def health():
    """Health check"""
    return jsonify({'status': 'healthy'})

# Serve frontend files
@app.route('/')
def index():
    """Serve main index.html"""
    return send_from_directory(FRONTEND_FOLDER, 'index.html')

@app.route('/mobile.html')
def mobile():
    """Serve mobile.html"""
    return send_from_directory(FRONTEND_FOLDER, 'mobile.html')

@app.route('/manifest.json')
def manifest():
    """Serve manifest.json"""
    return send_from_directory(FRONTEND_FOLDER, 'manifest.json')

@app.route('/service-worker.js')
def service_worker():
    """Serve service-worker.js"""
    return send_from_directory(FRONTEND_FOLDER, 'service-worker.js')

@app.route('/<path:filename>')
def serve_static(filename):
    """Serve static files from frontend folder"""
    try:
        return send_from_directory(FRONTEND_FOLDER, filename)
    except:
        # If file not found in frontend, return 404
        return jsonify({'error': 'File not found'}), 404

if __name__ == '__main__':
    print("Starting Pharmacy Inventory System API...")
    app.run(host='0.0.0.0', port=5001, debug=True)
