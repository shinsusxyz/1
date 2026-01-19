# Polymarket Nitter Monitor Bot

A Telegram bot that monitors Nitter.net for Polymarket discussions, tracking trending topics, engagement metrics, and alerting users to viral posts.

## Features

- **Real-time Monitoring**: Continuously scrapes Nitter for Polymarket-related posts
- **Trending Detection**: Identifies hot topics based on engagement metrics
- **Engagement Tracking**: Monitors likes, retweets, replies over time
- **Smart Alerts**: Notifications for milestone achievements and engagement spikes
- **Daily Digest**: Automated daily summary of top topics and posts
- **Data Export**: Export collected data in CSV or JSON format
- **Multiple Nitter Instances**: Automatic fallback to alternative instances
- **Rate Limiting**: Intelligent handling of rate limits with exponential backoff

## Quick Start

### 1. Prerequisites

- Python 3.10 or higher
- Linux server (Ubuntu/Debian recommended)
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))

### 2. Installation

```bash
# Clone or download the bot files
cd /opt
sudo mkdir polymarket-bot
sudo chown $USER:$USER polymarket-bot
cd polymarket-bot

# Copy all bot files here (bot.py, config.py, etc.)

# Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration

Edit `config.py` and set your Telegram bot token:

```python
TELEGRAM_BOT_TOKEN = "your_bot_token_here"
```

Or set it as an environment variable:

```bash
export TELEGRAM_BOT_TOKEN="your_bot_token_here"
```

### 4. Test Run

```bash
# Activate virtual environment
source venv/bin/activate

# Run the bot
python bot.py
```

### 5. Production Deployment (systemd)

```bash
# Create system user
sudo useradd -r -s /bin/false polybot

# Set permissions
sudo chown -R polybot:polybot /opt/polymarket-bot

# Copy systemd service file
sudo cp systemd/polymarket-bot.service /etc/systemd/system/

# Edit the service file to match your paths
sudo nano /etc/systemd/system/polymarket-bot.service

# Reload systemd and enable the service
sudo systemctl daemon-reload
sudo systemctl enable polymarket-bot
sudo systemctl start polymarket-bot
```

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and register for notifications |
| `/trending` | Current hot topics with engagement stats |
| `/topic <name>` | Detailed analysis of a specific topic |
| `/stats [1h\|6h\|24h\|7d]` | Statistics for time period |
| `/threshold <number>` | Set minimum engagement for notifications |
| `/filter <keywords>` | Add keyword filters (comma-separated) |
| `/export [csv\|json]` | Export collected data |
| `/status` | Bot health and last scan info |
| `/settings` | Configure notification preferences |
| `/search <query>` | Search posts by text |
| `/scan` | Trigger immediate scan (manual) |
| `/help` | Full command list |

## Configuration Options

All configuration is in `config.py`:

```python
# Telegram Settings
TELEGRAM_BOT_TOKEN = "your_token"

# Nitter Instances (with fallback)
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.poast.org",
    # Add more instances...
]

# Search Parameters
SEARCH_PARAMS = {
    "f": "tweets",
    "q": "polymarket",
    "min_faves": "100",
}

# Timing
SCAN_INTERVAL_MINUTES = 5
DELAY_BETWEEN_REQUESTS = 3.0
RATE_LIMIT_PAUSE = 60

# Notifications
DEFAULT_ENGAGEMENT_THRESHOLD = 1000
ENGAGEMENT_MILESTONES = [1000, 5000, 10000, 50000, 100000]
SPIKE_THRESHOLD_PERCENT = 200
DAILY_DIGEST_HOUR = 9
```

## File Structure

```
polymarket_bot/
├── bot.py                  # Main Telegram bot entry point
├── nitter_parser.py        # Core Nitter scraping logic
├── database.py             # SQLite operations and schema
├── analytics.py            # Trending detection and statistics
├── scheduler.py            # Background monitoring tasks
├── notifications.py        # Notification logic and formatting
├── config.py               # Configuration and constants
├── requirements.txt        # Dependencies
├── README.md               # This file
├── systemd/
│   └── polymarket-bot.service  # Systemd service file
└── logs/                   # Log files directory
```

## Managing the Service

```bash
# Start the bot
sudo systemctl start polymarket-bot

# Stop the bot
sudo systemctl stop polymarket-bot

# Restart the bot
sudo systemctl restart polymarket-bot

# Check status
sudo systemctl status polymarket-bot

# View logs
sudo journalctl -u polymarket-bot -f

# View application logs
tail -f /opt/polymarket-bot/logs/bot.log
```

## Database

The bot uses SQLite for storage. The database file is created automatically at `polymarket_bot.db`.

### Tables

- `posts` - Scraped posts with all metadata
- `engagement_history` - Historical engagement tracking
- `topics` - Polymarket topics mentioned
- `topic_mentions` - Links between posts and topics
- `user_settings` - Per-user notification preferences
- `notifications_log` - Sent notifications (for rate limiting)
- `scan_history` - Scraping operation logs

### Backup

```bash
# Simple backup
cp /opt/polymarket-bot/polymarket_bot.db /backup/polymarket_bot_$(date +%Y%m%d).db
```

## Troubleshooting

### Bot not starting

1. Check token is set correctly
2. Verify Python version: `python3 --version`
3. Check logs: `journalctl -u polymarket-bot -e`

### No posts being scraped

1. Check if Nitter instances are accessible
2. Verify network connectivity
3. Check for rate limiting in logs

### Notifications not working

1. Verify user has used `/start` command
2. Check user settings with `/settings`
3. Ensure engagement threshold is appropriate

### High memory usage

1. Reduce scan frequency in config
2. Clean old engagement history periodically
3. Export and archive old data

## Development

### Running Tests

```bash
# Test parser
python -c "from nitter_parser import NitterParser; p = NitterParser(); print(p.fetch_search_posts(max_pages=1))"

# Test database
python -c "from database import get_database; db = get_database(); print(db.get_posts_count())"
```

### Adding New Nitter Instances

Add instances to `NITTER_INSTANCES` in `config.py`. The bot will automatically try them in order.

### Modifying Search Parameters

Edit `SEARCH_PARAMS` in `config.py`:

```python
SEARCH_PARAMS = {
    "f": "tweets",
    "q": "polymarket OR prediction market",
    "min_faves": "50",
    "since": "2024-01-01",
}
```

## Security Notes

- Never commit your bot token to version control
- Use environment variables for sensitive data
- The systemd service runs with restricted permissions
- SQLite database should be backed up regularly

## License

MIT License - See LICENSE file for details.

## Support

For issues and feature requests, please open a GitHub issue.
