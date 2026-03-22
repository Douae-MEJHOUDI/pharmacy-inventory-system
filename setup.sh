#!/bin/bash

echo "========================================"
echo "Pharmacy Inventory System - Setup"
echo "========================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    exit 1
fi

echo "✓ Python 3 found: $(python3 --version)"

# Check Tesseract
if ! command -v tesseract &> /dev/null; then
    echo "⚠ Tesseract OCR not found. Installing..."
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        sudo apt-get update && sudo apt-get install -y tesseract-ocr
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        brew install tesseract
    fi
fi

echo "✓ Tesseract found: $(tesseract --version | head -n 1)"

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
cd backend
pip install -r requirements.txt --break-system-packages
cd ..

# Initialize database
echo ""
echo "Initializing database..."
cd backend
python3 database.py
cd ..

echo ""
echo "========================================"
echo "Setup Complete!"
echo "========================================"
echo ""
echo "To start the application:"
echo ""
echo "Terminal 1 - Backend:"
echo "  cd pharmacy-inventory-system/backend"
echo "  python3 app.py"
echo ""
echo "Terminal 2 - Frontend:"
echo "  cd pharmacy-inventory-system/frontend"
echo "  python3 -m http.server 8000"
echo ""
echo "Then open: http://localhost:8000"
echo ""
echo "Default login: admin / admin123"
echo ""
