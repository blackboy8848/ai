# setup_structure.ps1
# Run this from inside the backend/ folder on Windows
# PowerShell: .\setup_structure.ps1

Write-Host "Creating folder structure..." -ForegroundColor Cyan

# Create directories
$dirs = @(
    "config",
    "database",
    "auth",
    "angel_one",
    "api",
    "api\routes",
    "api\schemas",
    "websocket",
    "indicators",
    "strategies",
    "ai_engine",
    "news_engine",
    "paper_trading",
    "live_trading",
    "risk_management",
    "backtesting",
    "alerts",
    "logs",
    "utils",
    "services"
)

foreach ($dir in $dirs) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    New-Item -ItemType File -Path "$dir\__init__.py" -Force | Out-Null
    Write-Host "  Created $dir\__init__.py" -ForegroundColor Green
}

Write-Host ""
Write-Host "Done! Now run:" -ForegroundColor Cyan
Write-Host "  python -m venv venv" -ForegroundColor Yellow
Write-Host "  venv\Scripts\activate" -ForegroundColor Yellow
Write-Host "  pip install -r requirements.txt" -ForegroundColor Yellow
Write-Host "  uvicorn main:app --reload" -ForegroundColor Yellow
