#!/bin/bash
# setup_structure.sh
# Run from inside the backend/ folder: bash setup_structure.sh

echo "Creating folder structure..."

dirs=(
    "config"
    "database"
    "auth"
    "angel_one"
    "api"
    "api/routes"
    "api/schemas"
    "websocket"
    "indicators"
    "strategies"
    "ai_engine"
    "news_engine"
    "paper_trading"
    "live_trading"
    "risk_management"
    "backtesting"
    "alerts"
    "logs"
    "utils"
    "services"
)

for dir in "${dirs[@]}"; do
    mkdir -p "$dir"
    touch "$dir/__init__.py"
    echo "  Created $dir/__init__.py"
done

echo ""
echo "Done! Now run:"
echo "  python3 -m venv venv"
echo "  source venv/bin/activate"
echo "  pip install -r requirements.txt"
echo "  uvicorn main:app --reload"
