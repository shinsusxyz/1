#!/usr/bin/env python3
"""
Main Telegram Bot Entry Point for Polymarket Nitter Monitor.
Handles all bot commands and integrates with the scheduler.
"""
import asyncio
import logging
import sys
import csv
import json
import io
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, BufferedInputFile
from aiogram.filters import Command, CommandStart
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

import config
from database import get_database, Database
from analytics import get_analytics, AnalyticsEngine
from notifications import (
    get_formatter, get_notification_manager,
    NotificationFormatter, NotificationManager
)
from scheduler import get_scheduler, BackgroundScheduler, GracefulShutdown

# Setup logging
def setup_logging():
    """Configure logging for the bot."""
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)

    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(
            config.LOG_FILE,
            maxBytes=config.LOG_MAX_BYTES,
            backupCount=config.LOG_BACKUP_COUNT,
        )
    ]

    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL),
        format=config.LOG_FORMAT,
        handlers=handlers,
    )

# Need to import after logging setup
import logging.handlers

logger = logging.getLogger(__name__)

# Initialize router
router = Router()


# ============ BOT COMMANDS ============

@router.message(CommandStart())
async def cmd_start(message: Message, db: Database, formatter: NotificationFormatter):
    """Handle /start command."""
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Register user with default settings
    db.set_user_settings(user_id, chat_id)

    welcome_text = """**Welcome to Polymarket Nitter Monitor Bot!**

I monitor Twitter/X (via Nitter) for Polymarket discussions and alert you about trending topics and viral posts.

**Quick Start:**
- /trending - See what's hot now
- /stats - View statistics
- /settings - Configure notifications
- /help - Full command list

Monitoring is active. You'll receive alerts for:
- Posts reaching engagement milestones (1K, 5K, 10K+)
- Sudden engagement spikes (+200%)
- Daily digest at 9:00 AM

Use /settings to customize your preferences."""

    await message.answer(welcome_text, parse_mode=ParseMode.MARKDOWN)


@router.message(Command("help"))
async def cmd_help(message: Message, formatter: NotificationFormatter):
    """Handle /help command."""
    await message.answer(formatter.format_help(), parse_mode=ParseMode.MARKDOWN)


@router.message(Command("trending"))
async def cmd_trending(message: Message, analytics: AnalyticsEngine, formatter: NotificationFormatter):
    """Handle /trending command."""
    # Parse optional hours argument
    args = message.text.split()[1:] if message.text else []
    hours = 24
    if args:
        try:
            hours = int(args[0])
        except ValueError:
            pass

    topics = analytics.get_trending_topics(hours=hours, limit=10)
    response = formatter.format_trending_list(
        topics,
        title=f"Trending Topics (Last {hours}h)"
    )
    await message.answer(response, parse_mode=ParseMode.MARKDOWN)


@router.message(Command("topic"))
async def cmd_topic(message: Message, analytics: AnalyticsEngine, formatter: NotificationFormatter):
    """Handle /topic <name> command."""
    args = message.text.split()[1:] if message.text else []

    if not args:
        await message.answer("Usage: /topic <topic_name>\nExample: /topic presidential-election")
        return

    topic = " ".join(args)
    analysis = analytics.get_topic_analysis(topic)

    if "error" in analysis:
        await message.answer(f"Topic '{topic}' not found. Try /trending to see available topics.")
        return

    response = formatter.format_topic_analysis(analysis)
    await message.answer(response, parse_mode=ParseMode.MARKDOWN)


@router.message(Command("stats"))
async def cmd_stats(message: Message, analytics: AnalyticsEngine, formatter: NotificationFormatter):
    """Handle /stats [period] command."""
    args = message.text.split()[1:] if message.text else []
    period = args[0] if args else "24h"

    if period not in config.TIME_PERIODS:
        await message.answer(f"Invalid period. Use one of: {', '.join(config.TIME_PERIODS.keys())}")
        return

    stats = analytics.get_period_stats(period)
    response = formatter.format_stats(stats)
    await message.answer(response, parse_mode=ParseMode.MARKDOWN)


@router.message(Command("threshold"))
async def cmd_threshold(message: Message, db: Database):
    """Handle /threshold <number> command."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    args = message.text.split()[1:] if message.text else []

    if not args:
        settings = db.get_user_settings(user_id)
        current = settings.get("engagement_threshold", config.DEFAULT_ENGAGEMENT_THRESHOLD) if settings else config.DEFAULT_ENGAGEMENT_THRESHOLD
        await message.answer(
            f"Current threshold: {current:,}\n"
            f"Usage: /threshold <number>\n"
            f"Example: /threshold 5000"
        )
        return

    try:
        threshold = int(args[0])
        if threshold < 0:
            raise ValueError("Negative threshold")

        db.set_user_settings(user_id, chat_id, engagement_threshold=threshold)
        await message.answer(f"Engagement threshold set to {threshold:,}")

    except ValueError:
        await message.answer("Please provide a valid positive number.")


@router.message(Command("filter"))
async def cmd_filter(message: Message, db: Database):
    """Handle /filter <keywords> command."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    args = message.text.split(maxsplit=1)[1:] if message.text else []

    if not args:
        settings = db.get_user_settings(user_id)
        current = settings.get("keyword_filters", "") if settings else ""
        await message.answer(
            f"Current filters: {current or 'None'}\n"
            f"Usage: /filter <keywords>\n"
            f"Example: /filter election,trump,bitcoin\n"
            f"Use /filter clear to remove all filters."
        )
        return

    keywords = args[0].strip()

    if keywords.lower() == "clear":
        db.set_user_settings(user_id, chat_id, keyword_filters="")
        await message.answer("Keyword filters cleared.")
    else:
        db.set_user_settings(user_id, chat_id, keyword_filters=keywords)
        await message.answer(f"Keyword filters set to: {keywords}")


@router.message(Command("export"))
async def cmd_export(message: Message, db: Database):
    """Handle /export [csv|json] command."""
    args = message.text.split()[1:] if message.text else []
    format_type = args[0].lower() if args else "csv"

    if format_type not in ["csv", "json"]:
        await message.answer("Usage: /export [csv|json]")
        return

    await message.answer("Preparing export, please wait...")

    try:
        # Get posts from last 7 days
        since = datetime.utcnow() - timedelta(days=7)
        posts = db.export_posts(since=since)

        if not posts:
            await message.answer("No posts to export.")
            return

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        if format_type == "csv":
            # Create CSV
            output = io.StringIO()
            if posts:
                writer = csv.DictWriter(output, fieldnames=posts[0].keys())
                writer.writeheader()
                writer.writerows(posts)

            content = output.getvalue().encode("utf-8")
            filename = f"polymarket_posts_{timestamp}.csv"

        else:
            # Create JSON
            content = json.dumps(posts, indent=2, ensure_ascii=False).encode("utf-8")
            filename = f"polymarket_posts_{timestamp}.json"

        # Send file
        file = BufferedInputFile(content, filename=filename)
        await message.answer_document(
            file,
            caption=f"Export: {len(posts)} posts from last 7 days"
        )

    except Exception as e:
        logger.error(f"Export error: {e}")
        await message.answer(f"Export failed: {str(e)}")


@router.message(Command("status"))
async def cmd_status(message: Message, scheduler: BackgroundScheduler, formatter: NotificationFormatter):
    """Handle /status command."""
    status = scheduler.get_status()
    response = formatter.format_bot_status(status)
    await message.answer(response, parse_mode=ParseMode.MARKDOWN)


@router.message(Command("settings"))
async def cmd_settings(message: Message, db: Database, formatter: NotificationFormatter):
    """Handle /settings command."""
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Parse arguments for setting updates
    args = message.text.split()[1:] if message.text else []

    if args:
        # Update settings
        setting = args[0].lower()
        value = args[1].lower() if len(args) > 1 else None

        valid_settings = {
            "milestones": "notify_milestones",
            "spikes": "notify_spikes",
            "digest": "notify_daily_digest",
        }

        if setting in valid_settings:
            if value in ["on", "1", "true", "yes"]:
                db.set_user_settings(user_id, chat_id, **{valid_settings[setting]: 1})
                await message.answer(f"{setting.title()} notifications enabled.")
            elif value in ["off", "0", "false", "no"]:
                db.set_user_settings(user_id, chat_id, **{valid_settings[setting]: 0})
                await message.answer(f"{setting.title()} notifications disabled.")
            else:
                await message.answer("Use 'on' or 'off'. Example: /settings milestones off")
        else:
            await message.answer(
                "Available settings:\n"
                "- milestones (on/off)\n"
                "- spikes (on/off)\n"
                "- digest (on/off)\n\n"
                "Example: /settings milestones off"
            )
        return

    # Show current settings
    settings = db.get_user_settings(user_id)
    if not settings:
        db.set_user_settings(user_id, chat_id)
        settings = db.get_user_settings(user_id)

    response = formatter.format_settings(settings)
    response += "\n\n**To change settings:**\n"
    response += "/settings milestones off\n"
    response += "/settings spikes on\n"
    response += "/settings digest off"

    await message.answer(response, parse_mode=ParseMode.MARKDOWN)


@router.message(Command("search"))
async def cmd_search(message: Message, analytics: AnalyticsEngine):
    """Handle /search <query> command."""
    args = message.text.split(maxsplit=1)[1:] if message.text else []

    if not args:
        await message.answer("Usage: /search <query>\nExample: /search bitcoin")
        return

    query = args[0]
    results = analytics.search_and_analyze(query, limit=10)

    if results["count"] == 0:
        await message.answer(f"No posts found matching '{query}'")
        return

    lines = [
        f"**Search Results: '{query}'**\n",
        f"Found: {results['count']} posts",
        f"Total Engagement: {results['total_engagement']:,}",
        f"Avg Engagement: {int(results['avg_engagement']):,}\n",
    ]

    for i, post in enumerate(results["posts"][:5], 1):
        username = post.get("username", "unknown")
        text = post.get("text", "")[:100]
        engagement = post.get("engagement_score", 0)
        lines.append(f"{i}. @{username} ({engagement:,})")
        lines.append(f"   {text}...")

    await message.answer("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@router.message(Command("scan"))
async def cmd_scan(message: Message, scheduler: BackgroundScheduler):
    """Handle /scan command - trigger immediate scan (admin only)."""
    await message.answer("Starting manual scan...")

    try:
        result = await scheduler.run_scan_now()

        if result.success:
            await message.answer(
                f"Scan completed!\n"
                f"Posts found: {result.posts_found}\n"
                f"New posts: {result.new_posts}"
            )
        else:
            await message.answer(f"Scan failed: {result.error}")

    except Exception as e:
        logger.error(f"Manual scan error: {e}")
        await message.answer(f"Scan error: {str(e)}")


# ============ NOTIFICATION CALLBACKS ============

async def send_notification(bot: Bot, chat_id: int, message: str):
    """Send a notification message."""
    try:
        await bot.send_message(chat_id, message, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Failed to send notification to {chat_id}: {e}")


async def send_digest(bot: Bot, chat_id: int, message: str):
    """Send a daily digest message."""
    try:
        await bot.send_message(chat_id, message, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Failed to send digest to {chat_id}: {e}")


# ============ MAIN ============

async def main():
    """Main entry point."""
    setup_logging()
    logger.info("Starting Polymarket Nitter Monitor Bot...")

    # Validate token
    if config.TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("Please set TELEGRAM_BOT_TOKEN in config.py or environment variable")
        sys.exit(1)

    # Initialize components
    db = get_database()
    analytics = get_analytics()
    formatter = get_formatter()
    notification_manager = get_notification_manager()
    scheduler = get_scheduler()

    # Initialize bot
    bot = Bot(
        token=config.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )

    # Setup notification callbacks
    async def notification_callback(chat_id: int, message: str):
        await send_notification(bot, chat_id, message)

    async def digest_callback(chat_id: int, message: str):
        await send_digest(bot, chat_id, message)

    scheduler.set_notification_callback(notification_callback)
    scheduler.set_digest_callback(digest_callback)

    # Create dispatcher with dependency injection
    dp = Dispatcher()
    dp.include_router(router)

    # Inject dependencies
    dp["db"] = db
    dp["analytics"] = analytics
    dp["formatter"] = formatter
    dp["notification_manager"] = notification_manager
    dp["scheduler"] = scheduler

    # Setup graceful shutdown
    shutdown_handler = GracefulShutdown(scheduler)
    shutdown_handler.setup_handlers()

    # Start scheduler
    scheduler.start()

    # Run initial scan
    logger.info("Running initial scan...")
    await scheduler.run_scan_now()

    # Start polling
    logger.info("Bot is running. Press Ctrl+C to stop.")
    try:
        await dp.start_polling(bot, allowed_updates=["message"])
    finally:
        scheduler.stop()
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
