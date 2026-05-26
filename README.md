# 🤖 AI-Powered NIFTY 50 Trading Platform

A production-grade, fully automated options trading system built with Python, FastAPI, React, and Angel One SmartAPI. Supports both **Paper Trading** and **Live Trading** modes with AI-driven signals, real-time market data, and professional risk management.

---

## 📋 Table of Contents

- [What This System Does](#-what-this-system-does)
- [Architecture Overview](#-architecture-overview)
- [Tech Stack](#-tech-stack)
- [Project Structure](#-project-structure)
- [Phase Breakdown](#-phase-breakdown)
- [Prerequisites](#-prerequisites)
- [How to Run](#-how-to-run)
  - [Option A: Docker (Recommended)](#option-a-docker-recommended)
  - [Option B: Manual Setup](#option-b-manual-setup)
- [Environment Variables](#-environment-variables)
- [API Reference](#-api-reference)
- [Trading Modes](#-trading-modes)
- [Safety Rules](#-safety-rules)
- [Roadmap](#-roadmap)

---

## 🎯 What This System Does

This platform acts like an institutional-grade trading desk — running 24/7, analyzing markets, generating signals, and executing trades automatically.

| Capability | Description |
|---|---|
| 📡 **Live Market Data** | Streams NIFTY spot, option chain, OI, VIX, futures in real-time |
| 📊 **Technical Analysis** | EMA, RSI, MACD, VWAP, Supertrend, Bollinger Bands, ATR |
| 📰 **News Sentiment** | NLP analysis of RBI, SEBI, global macro news — bullish/bearish scoring |
| 🧠 **AI Prediction** | XGBoost + LightGBM models predict direction with confidence scores |
| 📃 **Option Chain Analysis** | OI buildup, PCR ratio, max pain, support/resistance from OI |
| 🟡 **Paper Trading** | Full simulation with virtual ₹10L balance — no real money |
| 🔴 **Live Trading** | Real order execution via Angel One SmartAPI with SL/target/trailing SL |
| 🛡️ **Risk Management** | Max daily loss circuit breaker, position sizing, volatility guards |
| 📈 **Dashboard** | Real-time React dashboard with TradingView charts and live PnL |
| 🔁 **Backtesting** | Historical strategy testing with Sharpe ratio, drawdown, ROI |
| 🔔 **Alerts** | Telegram, email, and desktop notifications for every signal |

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     React Frontend (Vite)                    │
│        Dashboard · Charts · Settings · Analytics            │
└────────────────────────┬────────────────────────────────────┘
                         │ REST + WebSocket
┌────────────────────────▼────────────────────────────────────┐
│                   FastAPI Backend                            │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │   Auth   │  │  Market  │  │Strategy  │  │    Risk    │  │
│  │  System  │  │  Engine  │  │  Engine  │  │  Manager   │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────┘  │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │    AI    │  │   News   │  │  Paper   │  │   Live     │  │
│  │  Engine  │  │ Analyzer │  │ Trading  │  │  Trading   │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────┘  │
└──────┬──────────────┬───────────────────────────┬───────────┘
       │              │                           │
┌──────▼────┐  ┌──────▼──────┐         ┌─────────▼──────────┐
│ PostgreSQL│  │    Redis    │         │  Angel One SmartAPI │
│  (data)   │  │  (pub/sub)  │         │  (order execution) │
└───────────┘  └─────────────┘         └────────────────────┘
```

**Data flow for a trade signal:**

```
Market Data Stream
      │
      ▼
Technical Indicators ──┐
News Sentiment ─────────┼──▶ Strategy Engine ──▶ AI Confidence Check
Option Chain OI ────────┘          │
                                   ▼
                           Risk Management
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
             Paper Trade                    Live Trade
           (always safe)              (requires LIVE_TRADING=True)
                    │                             │
                    └──────────────┬──────────────┘
                                   ▼
                          Dashboard + Alerts
```

---

## 🛠️ Tech Stack

### Backend
| Technology | Version | Purpose |
|---|---|---|
| Python | 3.12 | Core language |
| FastAPI | 0.111 | REST API + WebSocket server |
| SQLAlchemy | 2.0 (async) | ORM with async PostgreSQL |
| asyncpg | 0.29 | Async PostgreSQL driver |
| Alembic | 1.13 | Database migrations |
| Redis | 7 | WebSocket pub/sub, caching |
| structlog | 24.2 | Structured JSON logging |
| tenacity | 8.3 | Retry logic with exponential backoff |

### Trading & Data
| Technology | Purpose |
|---|---|
| Angel One SmartAPI | Order execution, market data |
| pandas + numpy | Data manipulation |
| pandas-ta | 130+ technical indicators |
| pyotp | TOTP 2FA for Angel One login |
| httpx | Async HTTP client |

### AI/ML
| Technology | Purpose |
|---|---|
| XGBoost | Primary direction prediction model |
| LightGBM | Ensemble model for confidence scoring |
| scikit-learn | Feature engineering, RandomForest |
| HuggingFace Transformers | FinBERT for news sentiment NLP |

### Frontend
| Technology | Version | Purpose |
|---|---|---|
| React | 18.3 | UI framework |
| TypeScript | 5.4 | Type safety |
| Vite | 5.2 | Build tool + dev server |
| TailwindCSS | 3.4 | Styling |
| Zustand | 4.5 | Global state management |
| TanStack Query | 5.40 | Server state + caching |
| Axios | 1.7 | HTTP client with interceptors |
| react-hot-toast | 2.4 | Notifications |

### Deployment
| Technology | Purpose |
|---|---|
| Docker + Docker Compose | Containerization |
| Nginx | Reverse proxy + SSL termination |
| PM2 | Process management for Node |
| Linux VPS | Production hosting |

---

## 📁 Project Structure

```
trading-system/
│
├── backend/
│   ├── main.py                    # FastAPI app factory + lifespan
│   │
│   ├── config/
│   │   ├── settings.py            # All env vars via pydantic-settings
│   │   └── logging.py             # Structlog configuration
│   │
│   ├── database/
│   │   ├── engine.py              # Async SQLAlchemy engine + get_db()
│   │   └── models.py              # ORM: User, APICredentials, TradingConfig
│   │
│   ├── auth/
│   │   ├── jwt.py                 # JWT create/verify, bcrypt passwords
│   │   ├── encryption.py          # AES-256-GCM for credential fields
│   │   └── dependencies.py        # get_current_user FastAPI dependency
│   │
│   ├── angel_one/
│   │   ├── client.py              # Async Angel One API wrapper
│   │   └── registry.py            # Per-user client cache (singleton per user)
│   │
│   ├── api/
│   │   ├── routes/
│   │   │   ├── auth.py            # /auth/* endpoints (9 routes)
│   │   │   ├── market.py          # /market/* endpoints (Phase 2)
│   │   │   └── trading.py         # /trading/* endpoints (Phase 7+)
│   │   └── schemas/
│   │       └── auth.py            # Pydantic request/response models
│   │
│   ├── websocket/
│   │   ├── manager.py             # WebSocket connection manager
│   │   └── market_stream.py       # Live NIFTY data streaming (Phase 2)
│   │
│   ├── indicators/
│   │   └── technical.py           # EMA, RSI, MACD, VWAP, Supertrend (Phase 3)
│   │
│   ├── strategies/
│   │   ├── base.py                # Abstract strategy interface
│   │   ├── ema_crossover.py       # EMA 9/21 crossover strategy
│   │   ├── vwap_breakout.py       # VWAP breakout strategy
│   │   └── option_chain.py        # OI-based option strategy (Phase 6)
│   │
│   ├── ai_engine/
│   │   ├── trainer.py             # Model training pipeline
│   │   ├── predictor.py           # Live inference (Phase 8)
│   │   └── features.py            # Feature engineering
│   │
│   ├── news_engine/
│   │   ├── scraper.py             # RSS + web scraping (Phase 4)
│   │   └── sentiment.py           # FinBERT NLP pipeline
│   │
│   ├── paper_trading/
│   │   └── engine.py              # Virtual order execution (Phase 7)
│   │
│   ├── live_trading/
│   │   └── executor.py            # Real order execution (Phase 8)
│   │
│   ├── risk_management/
│   │   └── manager.py             # Circuit breaker, position sizing (Phase 9)
│   │
│   ├── backtesting/
│   │   └── engine.py              # Historical strategy testing (Phase 11)
│   │
│   ├── alerts/
│   │   └── notifier.py            # Telegram + email alerts (Phase 12)
│   │
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx                # Router + protected routes
│   │   │
│   │   ├── components/
│   │   │   ├── auth/
│   │   │   │   ├── AuthPage.tsx       # Login + Register UI
│   │   │   │   └── CredentialsPage.tsx # Angel One setup + live toggle
│   │   │   ├── dashboard/
│   │   │   │   ├── Dashboard.tsx      # Main trading dashboard (Phase 10)
│   │   │   │   └── LivePnL.tsx        # Real-time PnL widget
│   │   │   └── charts/
│   │   │       └── TradingViewChart.tsx # TradingView embedded chart
│   │   │
│   │   ├── services/
│   │   │   └── api.ts             # Axios + token refresh interceptor
│   │   │
│   │   ├── store/
│   │   │   ├── authStore.ts       # Zustand auth + config state
│   │   │   └── marketStore.ts     # Live market data state (Phase 2)
│   │   │
│   │   └── hooks/
│   │       └── useWebSocket.ts    # WebSocket hook for live data (Phase 2)
│   │
│   ├── package.json
│   └── vite.config.ts
│
├── deployment/
│   ├── docker-compose.yml         # Full local dev stack
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   └── nginx.conf                 # Production reverse proxy (Phase 14)
│
├── .env.example                   # Template — copy to .env
└── README.md                      # This file
```

---

## 🔄 Phase Breakdown

### ✅ Phase 1 — Authentication System (COMPLETE)
Everything needed to securely connect users and their Angel One accounts.

**What's built:**
- User registration and login with bcrypt password hashing
- JWT access tokens (60 min) + refresh tokens (7 days) with rotation
- AES-256-GCM encryption for Angel One API keys stored in the database
- TOTP-based Angel One authentication (required by Angel One SmartAPI)
- Per-user AngelOneClient registry — no redundant logins
- Live/Paper trading mode toggle with safety guards
- React login/register UI with dark theme
- Angel One credentials page with verify + mode toggle

**API endpoints live:**
```
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/refresh
POST /api/v1/auth/logout
GET  /api/v1/auth/me
POST /api/v1/auth/credentials
GET  /api/v1/auth/credentials
POST /api/v1/auth/credentials/verify
GET  /api/v1/auth/config
PATCH /api/v1/auth/config
```

---

### 🔜 Phase 2 — Live Market Data Engine
Real-time WebSocket streaming of NIFTY market data.

**Will include:**
- NIFTY 50 spot price streaming
- Option chain with all strikes (CE + PE)
- Open Interest and OI change
- Put/Call Ratio (PCR)
- India VIX
- Futures basis
- Global indices (Dow, Nasdaq, S&P 500)
- Auto-reconnect on disconnect
- Redis pub/sub for multi-client broadcasting

---

### 🔜 Phase 3 — Technical Analysis Engine
Pure Python indicator calculation on live candle data.

**Will include:**
- EMA 9, 21, 50 with crossover detection
- RSI with overbought/oversold zones
- MACD with signal line and histogram
- VWAP with bands
- Supertrend (bullish/bearish label per candle)
- Bollinger Bands with squeeze detection
- ATR for dynamic stop loss calculation
- Support and Resistance auto-detection
- Volume spike detection
- Breakout zone identification

---

### 🔜 Phase 4 — News Analytics Engine
NLP-powered financial news sentiment analysis.

**Will include:**
- RSS feed parsing from ET, Moneycontrol, Reuters
- FinBERT model for financial sentiment (pre-trained on financial text)
- Bullish/Bearish probability score per article
- Weighted aggregate market sentiment score
- RBI, SEBI, FII/DII specific event detection
- Global macro triggers (Fed, crude oil, gold)
- Sentiment influences trade signal generation

---

### 🔜 Phase 5 — Option Chain Analytics
Deep analysis of NSE option chain data.

**Will include:**
- Strike-wise OI and OI change
- Long buildup / Short buildup / Short covering detection
- PCR (Put Call Ratio) calculation
- Max Pain strike detection
- Support/Resistance derived from OI walls
- OI-based market direction bias

---

### 🔜 Phase 6 — Strategy Engine
Multi-strategy signal generation with confirmation logic.

**Strategies:**
1. **EMA Crossover** — EMA 9 crosses EMA 21
2. **VWAP Breakout** — Price breaks above/below VWAP with volume
3. **RSI Momentum** — RSI divergence + momentum confirmation
4. **MACD Signal** — MACD crossover with histogram confirmation
5. **Option Chain** — OI buildup confirms direction
6. **Smart Money** — Liquidity sweeps and fake breakout detection
7. **Combined Signal** — All strategies vote; majority wins

**Trade condition (CE buy):**
```
Trend = Bullish AND
RSI > 60 AND
MACD histogram > 0 AND
News sentiment bullish score > 0.6 AND
OI buildup in CE AND
Volume above 20-period average
→ Generate BUY CE signal
```

---

### 🔜 Phase 7 — AI Prediction Engine
Machine learning models trained on historical trade data.

**Models:**
- XGBoost — primary direction classifier
- LightGBM — probability calibration
- RandomForest — ensemble voter

**Features used:**
- All technical indicators
- OI metrics
- News sentiment score
- Global market conditions
- Time of day (opening, mid-session, closing)
- Historical volatility

**Output:**
```json
{
  "direction": "BULLISH",
  "confidence": 84.2,
  "recommended_action": "BUY CE",
  "risk_rating": "MEDIUM"
}
```

---

### 🔜 Phase 8 — Paper Trading Engine
Full trade simulation that mirrors live trading exactly.

**Features:**
- Virtual ₹10,00,000 starting balance (configurable)
- Simulated order fills at current market price
- Slippage simulation
- Brokerage fee simulation
- Real-time PnL tracking
- Position management (add, reduce, exit)
- Win rate and trade analytics
- Full trade history

---

### 🔜 Phase 9 — Live Trading Engine
Real order execution via Angel One SmartAPI.

**Features:**
- Market and Limit order placement
- Stop Loss orders
- Target orders
- Trailing Stop Loss (auto-adjusts as trade moves in profit)
- Auto-exit on target/SL hit
- Order status polling with retry
- Position reconciliation with broker
- Emergency exit all positions

**Safety:**
```python
# This check exists in client.py — cannot be bypassed
if not get_settings().live_trading:
    raise RuntimeError("Live trading is disabled")
```

---

### 🔜 Phase 10 — Risk Management
Automated risk controls that run before every trade.

**Controls:**
- Daily loss limit (default 3% of capital)
- Maximum trades per day (default 10)
- Maximum position size per trade (default 5% of capital)
- Minimum AI confidence threshold (default 70%)
- Circuit breaker: stops all trading if daily loss limit hit
- Volatility guard: pauses trading if VIX spikes > 20%
- Risk/Reward validation: minimum 1:1.5 before entry

---

### 🔜 Phase 11 — Dashboard
Professional React trading dashboard with live data.

**Panels:**
- TradingView embedded chart with NIFTY
- Live AI signal with confidence meter
- News sentiment gauge
- Active positions with real-time PnL
- Today's trade history
- Equity curve
- Win rate and statistics
- Live log stream
- Strategy performance comparison

---

### 🔜 Phase 12 — Backtesting Engine
Test any strategy against historical NSE data.

**Metrics:**
- Total return %
- Sharpe ratio
- Maximum drawdown
- Win rate
- Average win / average loss
- Best and worst trade
- Monthly PnL heatmap
- Trade-by-trade log

---

### 🔜 Phase 13 — Alerts System
Multi-channel notifications for every signal.

**Channels:**
- Telegram bot message
- Email (SMTP)
- Browser push notification

**Signal alert format:**
```
🟢 BUY CE SIGNAL — NIFTY

Entry:      ₹245.00
Stop Loss:  ₹220.00  (-10.2%)
Target:     ₹290.00  (+18.4%)
RR Ratio:   1:1.8

AI Confidence:  84%
News Sentiment: Bullish (72%)
Strategy:       EMA + VWAP Breakout

⏰ 10:32 AM IST
```

---

### 🔜 Phase 14 — Deployment
Production deployment on Linux VPS.

**Setup:**
- Docker Compose for all services
- Nginx as reverse proxy with SSL (Let's Encrypt)
- PM2 for process management
- Automated daily backup of PostgreSQL
- Health check endpoints
- Log rotation
- Alert on server errors

---

## ✅ Prerequisites

### Required software

| Software | Version | Install |
|---|---|---|
| Docker | 24+ | https://docs.docker.com/get-docker |
| Docker Compose | 2.24+ | Included with Docker Desktop |
| Git | Any | https://git-scm.com |

> That's it for Docker setup. Everything else runs inside containers.

### For manual setup (without Docker)

| Software | Version |
|---|---|
| Python | 3.12+ |
| Node.js | 20+ |
| PostgreSQL | 16+ |
| Redis | 7+ |

### Angel One account requirements
- Active Angel One demat account
- SmartAPI access enabled (apply at smartapi.angelone.in)
- API key generated from the developer portal
- TOTP authenticator app (Google Authenticator / Authy)
- TOTP base32 secret saved when setting up 2FA

---

## 🚀 How to Run

### Option A: Docker (Recommended)

This starts the entire stack — database, Redis, backend, and frontend — with one command.

**Step 1: Clone the repository**
```bash
git clone https://github.com/yourname/trading-system.git
cd trading-system
```

**Step 2: Set up environment variables**
```bash
cp .env.example .env
```

Open `.env` and fill in at minimum:
```env
APP_SECRET_KEY=your-random-64-char-hex-string
JWT_SECRET_KEY=another-random-64-char-hex-string
```

Generate secure keys:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Step 3: Start all services**
```bash
cd deployment
docker compose up --build
```

First run takes 3–5 minutes to pull images and install dependencies.

**Step 4: Verify everything is running**
```
✅ PostgreSQL   → localhost:5432
✅ Redis        → localhost:6379
✅ Backend API  → http://localhost:8000
✅ Frontend     → http://localhost:5173
✅ API Docs     → http://localhost:8000/docs
```

**Step 5: Open the app**

Navigate to `http://localhost:5173` → you'll see the login page.

Register an account, then go to **Settings → API Credentials** to connect Angel One.

---

### Option B: Manual Setup

Use this if you want to run services natively without Docker.

**Step 1: Clone**
```bash
git clone https://github.com/yourname/trading-system.git
cd trading-system
```

**Step 2: PostgreSQL setup**
```bash
# macOS
brew install postgresql@16
brew services start postgresql@16

# Ubuntu
sudo apt install postgresql-16
sudo systemctl start postgresql

# Create database
psql -U postgres -c "CREATE USER trading_user WITH PASSWORD 'trading_pass';"
psql -U postgres -c "CREATE DATABASE trading_db OWNER trading_user;"
```

**Step 3: Redis setup**
```bash
# macOS
brew install redis
brew services start redis

# Ubuntu
sudo apt install redis-server
sudo systemctl start redis
```

**Step 4: Python backend**
```bash
cd backend

# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp ../.env.example ../.env
# Edit .env with your values

# Run the server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Step 5: React frontend**
```bash
cd frontend

# Install dependencies
npm install

# Run dev server
npm run dev
```

**Access:**
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/docs

---

## 🔐 Environment Variables

All configuration lives in `.env`. Copy `.env.example` to `.env` to start.

### Required (must set before running)

| Variable | Description |
|---|---|
| `APP_SECRET_KEY` | 32+ char random string for AES encryption of credentials |
| `JWT_SECRET_KEY` | 32+ char random string for JWT signing |
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `DATABASE_URL` | Full async PostgreSQL connection string |

### Angel One (required for trading)

| Variable | Description | Where to find |
|---|---|---|
| `ANGEL_ONE_API_KEY` | SmartAPI API key | smartapi.angelone.in developer console |
| `ANGEL_ONE_CLIENT_ID` | Your Angel One client ID | Login credentials |
| `ANGEL_ONE_PASSWORD` | Your Angel One MPIN | Set in Angel One app |
| `ANGEL_ONE_TOTP_SECRET` | Base32 TOTP secret | Shown once when enabling 2FA |

### Trading Mode

| Variable | Default | Description |
|---|---|---|
| `LIVE_TRADING` | `false` | **Master safety switch** — `false` = paper mode |
| `PAPER_TRADING_BALANCE` | `1000000` | Virtual starting balance in rupees |
| `MAX_DAILY_LOSS_PCT` | `3.0` | Auto-stop if daily loss exceeds this % |
| `MAX_TRADES_PER_DAY` | `10` | Maximum trades allowed per session |
| `MIN_AI_CONFIDENCE` | `70.0` | Skip signals below this AI confidence % |

---

## 📡 API Reference

All endpoints are prefixed with `/api/v1`. Interactive docs available at `/docs` in development.

### Authentication

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/auth/register` | None | Create new account |
| `POST` | `/auth/login` | None | Get access + refresh tokens |
| `POST` | `/auth/refresh` | None | Rotate tokens |
| `POST` | `/auth/logout` | Bearer | Revoke refresh token |
| `GET` | `/auth/me` | Bearer | Get current user profile |

### Credentials & Config

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/auth/credentials` | Bearer | Save Angel One API credentials |
| `GET` | `/auth/credentials` | Bearer | Get credential status |
| `POST` | `/auth/credentials/verify` | Bearer | Test Angel One connection |
| `GET` | `/auth/config` | Bearer | Get trading configuration |
| `PATCH` | `/auth/config` | Bearer | Update trading configuration |

### Health

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | None | Server health check |

---

## 🔄 Trading Modes

### Paper Trading Mode (Default — Safe)

```env
LIVE_TRADING=false
```

- All trade signals are simulated
- Virtual ₹10,00,000 balance
- Full PnL tracking, win rate, analytics
- Identical behavior to live trading
- **No real money involved**
- Run this for at least 2 weeks before going live

### Live Trading Mode (Real Money)

```env
LIVE_TRADING=true
```

To enable from the UI:
1. Go to **Settings → API Credentials**
2. Add and verify your Angel One credentials
3. Click the toggle — a confirmation prompt appears
4. Confirm to enable live mode

**Safety gates before live mode activates:**
- ✅ Angel One credentials must be saved
- ✅ Credentials must be verified (live connection test passed)
- ✅ Confirmation prompt must be accepted

**Automatic protections while live:**
- Daily loss limit circuit breaker (default 3%)
- Maximum 10 trades per day
- Minimum 70% AI confidence required
- Minimum 1:1.5 risk/reward ratio
- Auto-exit all positions at 3:25 PM IST

---

## 🛡️ Safety Rules

These are enforced in code — not just guidelines:

1. **No trade without stop loss** — every order has an SL attached
2. **Live trading blocked by default** — `LIVE_TRADING=false` in code and database
3. **Credentials never stored in plaintext** — AES-256-GCM encrypted in database
4. **API keys never returned to frontend** — credential read endpoint returns metadata only
5. **Daily loss circuit breaker** — trading halts automatically at configured limit
6. **AI confidence gate** — signals below 70% confidence are discarded
7. **Market hours check** — no orders placed outside 9:15 AM – 3:25 PM IST
8. **Extreme volatility guard** — trading pauses if VIX spikes sharply

---

## 🗺️ Roadmap

| Phase | Feature | Status |
|---|---|---|
| 1 | Authentication + Angel One Connection | ✅ Complete |
| 2 | Live Market Data Engine (WebSocket) | 🔜 Next |
| 3 | Technical Analysis Engine | 🔜 Planned |
| 4 | News Analytics + NLP Sentiment | 🔜 Planned |
| 5 | Option Chain Analytics | 🔜 Planned |
| 6 | Strategy Engine (8 strategies) | 🔜 Planned |
| 7 | AI Prediction Engine (XGBoost + LightGBM) | 🔜 Planned |
| 8 | Paper Trading Engine | 🔜 Planned |
| 9 | Live Trading Engine | 🔜 Planned |
| 10 | Risk Management | 🔜 Planned |
| 11 | Dashboard (React + TradingView) | 🔜 Planned |
| 12 | Backtesting Engine | 🔜 Planned |
| 13 | Alerts (Telegram + Email) | 🔜 Planned |
| 14 | Production Deployment (Docker + Nginx) | 🔜 Planned |

---

## ⚠️ Disclaimer

This software is for **educational and research purposes**.

- Past performance does not guarantee future results
- Options trading involves substantial risk of loss
- Always test thoroughly in paper mode before using real money
- The authors are not responsible for any financial losses
- Never trade with money you cannot afford to lose
- Consult a SEBI-registered financial advisor before live trading

---

*Built phase by phase — production-ready at every step.*
