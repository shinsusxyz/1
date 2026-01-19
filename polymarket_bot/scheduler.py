"""
Background Scheduler for Polymarket Nitter Monitor Bot.
Handles continuous monitoring, periodic scans, and scheduled tasks.
"""
import asyncio
import logging
import signal
from datetime import datetime, timedelta
from typing import Optional, Callable, List, Dict, Any
from threading import Thread, Event
import traceback

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

import config
from database import get_database, Database
from nitter_parser import NitterParser
from analytics import get_analytics, AnalyticsEngine
from notifications import get_notification_manager, NotificationManager

logger = logging.getLogger(__name__)


class ScanResult:
    """Result of a scan operation."""

    def __init__(
        self,
        success: bool,
        posts_found: int = 0,
        new_posts: int = 0,
        error: Optional[str] = None
    ):
        self.success = success
        self.posts_found = posts_found
        self.new_posts = new_posts
        self.error = error
        self.timestamp = datetime.utcnow()


class BackgroundScheduler:
    """
    Background scheduler for continuous monitoring.
    Handles periodic scans, notifications, and scheduled tasks.
    """

    def __init__(
        self,
        db: Optional[Database] = None,
        parser: Optional[NitterParser] = None,
        analytics: Optional[AnalyticsEngine] = None,
        notification_manager: Optional[NotificationManager] = None
    ):
        self.db = db or get_database()
        self.parser = parser or NitterParser()
        self.analytics = analytics or get_analytics()
        self.notification_manager = notification_manager or get_notification_manager()

        self.scheduler = AsyncIOScheduler()
        self._running = False
        self._shutdown_event = Event()

        # Callbacks for notifications
        self._notification_callback: Optional[Callable] = None
        self._digest_callback: Optional[Callable] = None

        # Last scan result
        self.last_scan_result: Optional[ScanResult] = None

    def set_notification_callback(self, callback: Callable):
        """
        Set callback for sending notifications.
        Callback signature: async def callback(user_id: int, message: str)
        """
        self._notification_callback = callback

    def set_digest_callback(self, callback: Callable):
        """
        Set callback for sending daily digest.
        Callback signature: async def callback(user_id: int, message: str)
        """
        self._digest_callback = callback

    async def scan_nitter(self) -> ScanResult:
        """
        Perform a scan of Nitter for new posts.
        """
        logger.info("Starting Nitter scan...")
        scan_id = self.db.start_scan()

        try:
            # Get last known post ID for incremental updates
            last_post_id = self.db.get_latest_post_id()

            # Fetch new posts
            posts = self.parser.fetch_new_posts(last_post_id=last_post_id)

            # Insert posts into database
            total, new_count = self.db.bulk_insert_posts(posts)

            # Complete scan
            self.db.complete_scan(scan_id, total, new_count)

            result = ScanResult(
                success=True,
                posts_found=total,
                new_posts=new_count
            )
            self.last_scan_result = result

            logger.info(f"Scan completed: {total} posts found, {new_count} new")

            # Process notifications for new posts
            if new_count > 0:
                await self._process_notifications()

            return result

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Scan failed: {error_msg}")
            logger.error(traceback.format_exc())

            self.db.complete_scan(scan_id, 0, 0, error=error_msg)

            result = ScanResult(success=False, error=error_msg)
            self.last_scan_result = result
            return result

    async def _process_notifications(self):
        """Process and send notifications for all users."""
        if not self._notification_callback:
            logger.debug("No notification callback set, skipping notifications")
            return

        try:
            users = self.db.get_all_users_for_notifications()

            for user in users:
                user_id = user["user_id"]
                chat_id = user["chat_id"]

                # Get pending alerts
                alerts = self.notification_manager.get_pending_alerts(user_id)

                # Format and send messages
                messages = self.notification_manager.format_grouped_alerts(alerts)

                for message in messages:
                    try:
                        await self._notification_callback(chat_id, message)
                    except Exception as e:
                        logger.error(f"Failed to send notification to {user_id}: {e}")

                # Mark alerts as sent
                self.notification_manager.mark_alerts_sent(user_id, alerts)

        except Exception as e:
            logger.error(f"Error processing notifications: {e}")

    async def send_daily_digest(self):
        """Send daily digest to all subscribed users."""
        logger.info("Sending daily digest...")

        if not self._digest_callback:
            logger.debug("No digest callback set, skipping digest")
            return

        try:
            # Generate digest message
            message = self.notification_manager.generate_daily_digest_message()

            # Get users for digest
            users = self.notification_manager.get_users_for_daily_digest()

            for user in users:
                try:
                    await self._digest_callback(user["chat_id"], message)
                    self.db.log_notification(user["user_id"], "daily_digest", "")
                except Exception as e:
                    logger.error(f"Failed to send digest to {user['user_id']}: {e}")

            logger.info(f"Daily digest sent to {len(users)} users")

        except Exception as e:
            logger.error(f"Error sending daily digest: {e}")

    def start(self):
        """Start the scheduler."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        logger.info("Starting background scheduler...")

        # Add scan job
        self.scheduler.add_job(
            self.scan_nitter,
            IntervalTrigger(minutes=config.SCAN_INTERVAL_MINUTES),
            id="nitter_scan",
            name="Nitter Scan",
            replace_existing=True,
            max_instances=1,
        )

        # Add daily digest job
        self.scheduler.add_job(
            self.send_daily_digest,
            CronTrigger(
                hour=config.DAILY_DIGEST_HOUR,
                minute=config.DAILY_DIGEST_MINUTE
            ),
            id="daily_digest",
            name="Daily Digest",
            replace_existing=True,
        )

        # Start scheduler
        self.scheduler.start()
        self._running = True

        logger.info(
            f"Scheduler started. Scan interval: {config.SCAN_INTERVAL_MINUTES} min, "
            f"Daily digest at: {config.DAILY_DIGEST_HOUR:02d}:{config.DAILY_DIGEST_MINUTE:02d}"
        )

    def stop(self):
        """Stop the scheduler."""
        if not self._running:
            return

        logger.info("Stopping background scheduler...")
        self.scheduler.shutdown(wait=True)
        self._running = False
        self._shutdown_event.set()
        logger.info("Scheduler stopped")

    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running

    async def run_scan_now(self) -> ScanResult:
        """Trigger an immediate scan."""
        logger.info("Triggering immediate scan...")
        return await self.scan_nitter()

    def get_status(self) -> Dict[str, Any]:
        """Get scheduler status."""
        last_scan = self.db.get_last_scan()
        scan_stats = self.db.get_scan_stats(hours=24)

        return {
            "running": self._running,
            "total_posts": self.db.get_posts_count(),
            "total_topics": len(self.db.get_all_topics()),
            "last_scan": last_scan.get("started_at", "Never") if last_scan else "Never",
            "scan_status": last_scan.get("status", "Unknown") if last_scan else "Unknown",
            "posts_found": last_scan.get("posts_found", 0) if last_scan else 0,
            "new_posts": last_scan.get("new_posts", 0) if last_scan else 0,
            "scan_stats": scan_stats,
        }

    def get_jobs(self) -> List[Dict[str, Any]]:
        """Get list of scheduled jobs."""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time) if job.next_run_time else "Not scheduled",
            })
        return jobs


class GracefulShutdown:
    """Handle graceful shutdown signals."""

    def __init__(self, scheduler: BackgroundScheduler):
        self.scheduler = scheduler
        self._shutdown = False

    def setup_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        if self._shutdown:
            logger.warning("Force shutdown requested")
            raise SystemExit(1)

        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self._shutdown = True
        self.scheduler.stop()


# Singleton instance
_scheduler_instance: Optional[BackgroundScheduler] = None


def get_scheduler() -> BackgroundScheduler:
    """Get or create scheduler instance."""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = BackgroundScheduler()
    return _scheduler_instance


# For standalone testing
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format=config.LOG_FORMAT,
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    async def main():
        scheduler = get_scheduler()

        # Setup graceful shutdown
        shutdown_handler = GracefulShutdown(scheduler)
        shutdown_handler.setup_handlers()

        # Run initial scan
        result = await scheduler.scan_nitter()
        print(f"Initial scan: {result.posts_found} posts, {result.new_posts} new")

        # Start scheduler
        scheduler.start()

        # Keep running
        try:
            while scheduler.is_running():
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            scheduler.stop()

    asyncio.run(main())
