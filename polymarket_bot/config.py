"""
Configuration settings for Polymarket Nitter Monitor Bot.
All configurable options in one place.
"""
import os
from pathlib import Path

# ============ TELEGRAM SETTINGS ============
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# ============ NITTER INSTANCES ============
# List of Nitter instances to try (with fallback)
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.woodland.cafe",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
    "https://nitter.unixfox.eu",
    "https://nitter.domain.glass",
]

# ============ SEARCH PARAMETERS ============
SEARCH_PARAMS = {
    "f": "tweets",          # Search type: tweets, users, etc.
    "q": "polymarket",      # Search query
    "e-replies": "on",      # Include replies
    "since": "",            # Start date (YYYY-MM-DD)
    "until": "",            # End date (YYYY-MM-DD)
    "min_faves": "100",     # Minimum likes
}

# Default search query
SEARCH_QUERY = "polymarket"
MIN_FAVES = 100

# ============ TIMING AND LIMITS ============
SCAN_INTERVAL_MINUTES = 5           # How often to scan (minutes)
DELAY_BETWEEN_REQUESTS = 3.0        # Seconds between requests
MAX_RETRIES = 3                     # Max retries per request
RATE_LIMIT_PAUSE = 60               # Pause on 429 error (seconds)
LOAD_MORE_DELAY = 2.0               # Delay after pagination
MAX_LOAD_MORE_ATTEMPTS = 100        # Max pagination attempts
REQUEST_TIMEOUT = 30                # Request timeout (seconds)

# ============ ENGAGEMENT THRESHOLDS ============
DEFAULT_ENGAGEMENT_THRESHOLD = 1000  # Default min engagement for notifications
ENGAGEMENT_MILESTONES = [1000, 5000, 10000, 50000, 100000]

# Spike detection: percentage increase that triggers alert
SPIKE_THRESHOLD_PERCENT = 200       # +200% in 1 hour
SPIKE_WINDOW_HOURS = 1              # Time window for spike detection

# ============ DATABASE ============
BASE_DIR = Path(__file__).parent
DATABASE_PATH = BASE_DIR / "polymarket_bot.db"

# ============ LOGGING ============
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "bot.log"
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_MAX_BYTES = 10 * 1024 * 1024    # 10 MB
LOG_BACKUP_COUNT = 5

# ============ NOTIFICATION SETTINGS ============
DAILY_DIGEST_HOUR = 9               # Hour for daily digest (24h format)
DAILY_DIGEST_MINUTE = 0
TOP_TOPICS_COUNT = 5                # Number of top topics in digest
NOTIFICATION_COOLDOWN = 300         # Min seconds between similar notifications
MAX_NOTIFICATIONS_PER_HOUR = 20     # Rate limit notifications

# ============ TIME PERIODS FOR STATS ============
TIME_PERIODS = {
    "1h": 3600,
    "6h": 21600,
    "24h": 86400,
    "7d": 604800,
}

# ============ USER AGENT ============
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ============ POLYMARKET URL PATTERN ============
POLYMARKET_URL_PATTERN = r"polymarket\.com/event/([a-zA-Z0-9-]+)"

# ============ EXPORT SETTINGS ============
EXPORT_DIR = BASE_DIR / "exports"
