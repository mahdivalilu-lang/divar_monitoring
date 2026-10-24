# Divar Automated Keyword Monitoring & Telegram Alert System

An autonomous, resilient, and production-ready Python application designed to perform high-frequency real-time listing scraping from Divar (Iran's leading classifieds platform) with instant Telegram notifications, strict geographic/keyword filtering, and robust anti-blocking network routing.

---

## 🌟 Overview & Problem Statement

Scraping and real-time monitoring of modern web platforms present significant challenges due to aggressive rate-limiting, dynamic frontend rendering, API schema migrations, and severe regional network restrictions (SNI filtering/ISP blocks). 

This project solves these engineering challenges by providing a headless, non-intrusive monitoring agent capable of:
* Circumventing network-level blocking via modern tunneling proxies (Xray/TUN) with custom HTTP client configurations.
* Continuous polling of non-public dynamic API endpoints with strict keyword deduplication.
* Parsing and normalizing Iranian Persian text streams (including RLM unicode stripping, pricing formatting, and dynamic layout extraction).
* Dispatching high-fidelity, rich-media Telegram alerts (photo groups with clean metadata) to end-users with near-zero latency.

Designed specifically for targeted market research, arbitrage opportunities, and immediate deal notifications.

---

## 🚀 Key Technical Highlights & Features

- **Resilient Network Architecture**: Bypasses regional SNI filtering and ISP-level blocks using an integrated Xray-core/TUN routing layer with asynchronous HTTP persistent connections.
- **Dynamic Schema Adaptability**: Fully adapted to Divar's updated `list_widgets` and `posts-v2` web API schemas, gracefully handling missing fields and layout variations.
- **Persian Text Processing Pipeline**: Features automated string sanitization, Right-to-Left Mark (`\u200f`) stripping, digit normalization, and clean description snippet generation.
- **Robust Deduplication & State Management**: Utilizes an embedded SQLite database backend to track processed listings (`seen_this_cycle`), preventing duplicate alerts across restarts and overlapping execution loops.
- **Smart Rate-Limiting & Exponential Backoff**: Built-in HTTP retry mechanisms (`HTTP 403 / 429` detection) with intelligent long backoffs to prevent IP throttling and maintain human-like request signatures.
- **Rich Media Messaging**: Uses Telegram's `sendMediaGroup` and `sendMessage` endpoints to deliver multi-photo listings with formatted markdown captions, direct post links, and location metadata.
- **First-Run Seed Mechanism**: Implements a initial run mode (`SEED_ON_FIRST_RUN`) that hydrates the local database without spamming historical alerts, ensuring only genuine *new* posts trigger notifications.

---

## 🛠️ Technology Stack & Libraries

* **Language**: Python 3.10+
* **HTTP Client**: `httpx` (Async-capable, HTTP/1.1 & HTTP/2 support, custom proxy routing)
* **Data Persistence**: SQLite 3 (Lightweight, atomic local state storage)
* **Data Validation & Parsing**: Built-in JSON parser, Regular Expressions (`re`), Custom String Sanitizers
* **Environment & Configuration**: `python-dotenv` (12-Factor App design pattern)
* **Alerting Pipeline**: Telegram Bot API (`httpx` integration)
* **Network Infrastructure**: Xray-Core / TUN mode / Happ Proxy Manager

---

## 📦 Installation & Quick Start

### Prerequisites
* Python 3.10 or higher
* A Telegram Bot Token (obtained from [@BotFather](https://t.me/BotFather)) and your target Telegram `CHAT_ID`
* Active network proxy (e.g., Happ/Xray) if operating under ISP-restricted environments

### 1. Clone the Repository
```bash
git clone https://github.com/your-username/divar-monitor.git
cd divar-monitor
```

### 2. Set Up Virtual Environment & Install Dependencies
```bash
python -m venv venv

# On Windows
.\venv\Scripts\activate

# On Linux/macOS
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Environment Configuration
Create a `.env` file in the root directory by copying the example template:
```bash
cp .env.example .env
```

Configure your `.env` file with your credentials and parameters:
```env
TELEGRAM_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
TELEGRAM_CHAT_ID=123456789
CITY_ID=10
KEYWORDS=گردو,پسته,بادام,کشمش,مویز,آجیل
POLL_INTERVAL_SECONDS=180
LOG_LEVEL=INFO
```

### 4. Run the Application
Execute the main entry point:
```bash
python main.py
```

---

## 🧪 Testing & Verification

The project includes unit, integration, and live parser test suites to verify API compatibility:

```bash
# Run test suite
pytest
```

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.