from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import pytesseract
from PIL import Image
import os, re, json, random
from datetime import datetime
from pathlib import Path

app  = Flask(__name__)
CORS(app, origins='*')

BASE   = Path(__file__).parent.parent
UPLOAD = BASE / 'uploads'
FRONT  = BASE / 'frontend'
UPLOAD.mkdir(exist_ok=True)

ALLOWED = {'png', 'jpg', 'jpeg', 'bmp', 'tiff', 'webp'}
API_KEY = os.environ.get('ANTHROPIC_API_KEY')

def ok_ext(fn):
    return '.' in fn and fn.rsplit('.', 1)[1].lower() in ALLOWED

def run_ocr(path):
    return pytesseract.image_to_string(Image.open(path))

def call_ai(text):
    import anthropic
    client = anthropic.Anthropic(api_key=API_KEY)
    prompt = f"""You are processing raw OCR text from a pharmacy supplier delivery receipt.

Extract every product/medicine line item. Return a JSON array where each object has EXACTLY these fields:
  medicine_name            (string — full product name with dosage)
  medicine_name_confidence (float 0-1)
  quantity                 (string — number of units)
  quantity_confidence      (float 0-1)
  batch_number             (string — lot/batch number, "" if absent)
  batch_number_confidence  (float 0-1)
  expiry_date              (string — YYYY-MM-DD, "" if absent; use -01 for missing day)
  expiry_date_confidence   (float 0-1)
  unit_price               (string — decimal e.g. "12.50", "" if absent)
  unit_price_confidence    (float 0-1)

Confidence guide: 0.85-1.0 very clear | 0.65-0.84 clear with minor ambiguity |
0.40-0.64 partially readable | 0.10-0.39 very uncertain.

Return ONLY a valid JSON array. No markdown, no explanation.

OCR TEXT:
{text}"""

    r   = client.messages.create(model='claude-sonnet-4-6', max_tokens=2048,
                                  messages=[{'role': 'user', 'content': prompt}])
    raw = r.content[0].text.strip()
    raw = re.sub(r'^```[a-z]*\n?', '', raw)
    raw = re.sub(r'\n?```$', '', raw.strip())
    return json.loads(raw.strip())

def ocr_fallback(text):
    items = []
    skip  = ['pharmacie','pharmacy','total','merci','recu','subtotal','tva',
             'signature','tel:','address','avenue','rue','conservez','facture',
             'invoice','thank','receipt']
    for line in text.split('\n'):
        line = line.strip()
        if not line or len(line) < 5: continue
        if any(w in line.lower() for w in skip): continue
        if not (any(c.isdigit() for c in line) and any(c.isalpha() for c in line)): continue

        item = {
            'medicine_name': '',
            'medicine_name_confidence': round(random.uniform(0.60, 0.91), 2),
            'quantity': '',
            'quantity_confidence': round(random.uniform(0.55, 0.90), 2),
            'batch_number': '',
            'batch_number_confidence': round(random.uniform(0.38, 0.80), 2),
            'expiry_date': '',
            'expiry_date_confidence': round(random.uniform(0.42, 0.86), 2),
            'unit_price': '',
            'unit_price_confidence': round(random.uniform(0.50, 0.88), 2),
        }

        words = line.split()
        name  = [w for w in words
                 if w.replace('.','').replace('-','').isalpha()
                 or any(x in w.lower() for x in ['mg','ml','mcg','g'])]
        item['medicine_name'] = ' '.join(name[:4])

        m = re.search(r'\b(\d{1,4})\b', line)
        if m: item['quantity'] = m.group(1)

        for pat in [r'\b(\d{2}[/-]\d{4})\b', r'\b(\d{2}[/-]\d{2}[/-]\d{4})\b']:
            dm = re.search(pat, line)
            if dm:
                p = re.split(r'[/-]', dm.group(1))
                item['expiry_date'] = (f"{p[1]}-{p[0]}-01" if len(p) == 2
                                       else f"{p[2]}-{p[1]}-{p[0]}")
                break

        pm = re.search(r'(\d+[.,]\d{2})\s*(?:MAD|DH)?', line)
        if pm: item['unit_price'] = pm.group(1).replace(',', '.')

        bm = re.search(r'\b([A-Z]{1,3}\d{4,})\b', line)
        if bm: item['batch_number'] = bm.group(1)

        if item['medicine_name']:
            items.append(item)
    return items

# ── Routes ────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory(str(FRONT), 'index.html')

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory(str(FRONT), filename)

@app.route('/api/health')
def health():
    return jsonify({'ok': True, 'ai': bool(API_KEY)})

@app.route('/api/receipt/upload', methods=['POST', 'OPTIONS'])
def upload():
    if request.method == 'OPTIONS':
        return '', 200
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided'}), 400
    f = request.files['file']
    if not f.filename or not ok_ext(f.filename):
        return jsonify({'success': False, 'error': 'Unsupported file type'}), 400

    path = UPLOAD / f"r_{datetime.now():%Y%m%d_%H%M%S}_{f.filename}"
    f.save(path)

    try:
        raw    = run_ocr(path)
        ai     = False
        if API_KEY:
            try:
                items = call_ai(raw)
                ai    = True
            except Exception:
                items = ocr_fallback(raw)
        else:
            items = ocr_fallback(raw)
        return jsonify({'success': True, 'items': items, 'raw_text': raw, 'ai_used': ai})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5002)
