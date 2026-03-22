#!/bin/bash
cd "$(dirname "$0")"
mkdir -p uploads

echo ""
echo "  GoE Pharmacy OS — Document Intelligence Demo"
echo "  ─────────────────────────────────────────────"
echo "  Starting backend on http://localhost:5002"
echo "  Open http://localhost:5002 in your browser"
echo ""

if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
else
  echo "  WARNING: .env file not found. Create one with ANTHROPIC_API_KEY=your_key"
  echo ""
fi


cd backend && python3 app.py
