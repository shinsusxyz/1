"""
Notification Logic and Formatting for Polymarket Nitter Monitor Bot.
Handles message formatting, notification grouping, and delivery.
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

import config
from database import get_database, Database
from analytics import (
    AnalyticsEngine, get_analytics,
    TrendingTopic, EngagementAlert, DailyDigest
)

logger = logging.getLogger(__name__)


def format_number(n: int) -> str:
    """Format large numbers with K/M suffix."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def truncate_text(text: str, max_length: int = 200) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


def escape_markdown(text: str) -> str:
    """Escape special characters for Telegram Markdown."""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f"\\{char}")
    return text


class NotificationFormatter:
    """Formats notifications for Telegram."""

    @staticmethod
    def format_post_summary(post: Dict, include_link: bool = True) -> str:
        """Format a single post summary."""
        username = post.get("username", "unknown")
        text = truncate_text(post.get("text", ""), 150)
        engagement = post.get("engagement_score", 0)
        likes = post.get("count_like", 0)
        retweets = post.get("count_retweet", 0)
        replies = post.get("count_reply", 0)

        lines = [
            f"**@{username}**",
            f"{text}",
            f"Engagement: {format_number(engagement)} "
            f"(Likes: {format_number(likes)}, RT: {format_number(retweets)}, "
            f"Replies: {format_number(replies)})",
        ]

        if include_link:
            post_id = post.get("post_id", "")
            if post_id:
                lines.append(f"[View Tweet](https://twitter.com/{username}/status/{post_id})")

        return "\n".join(lines)

    @staticmethod
    def format_milestone_alert(alert: EngagementAlert) -> str:
        """Format a milestone alert message."""
        milestone_str = format_number(alert.milestone) if alert.milestone else "?"

        return (
            f"**Milestone Reached: {milestone_str} Engagement**\n\n"
            f"**@{alert.username}**\n"
            f"{truncate_text(alert.text, 200)}\n\n"
            f"Current: {format_number(alert.current_engagement)} "
            f"(was {format_number(alert.previous_engagement)})\n"
            f"[View Tweet](https://twitter.com/{alert.username}/status/{alert.post_id})"
        )

    @staticmethod
    def format_spike_alert(alert: EngagementAlert) -> str:
        """Format a spike alert message."""
        spike_str = f"+{alert.spike_percent:.0f}%" if alert.spike_percent else "?"

        return (
            f"**Engagement Spike: {spike_str}**\n\n"
            f"**@{alert.username}**\n"
            f"{truncate_text(alert.text, 200)}\n\n"
            f"Current: {format_number(alert.current_engagement)} "
            f"(was {format_number(alert.previous_engagement)})\n"
            f"[View Tweet](https://twitter.com/{alert.username}/status/{alert.post_id})"
        )

    @staticmethod
    def format_trending_topic(topic: TrendingTopic, rank: int = 0) -> str:
        """Format a trending topic."""
        rank_str = f"#{rank} " if rank > 0 else ""
        growth_str = f"+{topic.growth_rate:.0f}%" if topic.growth_rate > 0 else f"{topic.growth_rate:.0f}%"

        lines = [
            f"**{rank_str}{topic.topic}**",
            f"Mentions: {topic.mention_count} | Engagement: {format_number(topic.total_engagement)}",
            f"Growth: {growth_str}",
        ]

        return "\n".join(lines)

    @staticmethod
    def format_trending_list(topics: List[TrendingTopic], title: str = "Trending Topics") -> str:
        """Format a list of trending topics."""
        if not topics:
            return f"**{title}**\n\nNo trending topics found."

        lines = [f"**{title}**\n"]

        for i, topic in enumerate(topics, 1):
            growth_str = f"+{topic.growth_rate:.0f}%" if topic.growth_rate > 0 else f"{topic.growth_rate:.0f}%"
            lines.append(
                f"{i}. **{topic.topic}**\n"
                f"   {topic.mention_count} mentions | {format_number(topic.total_engagement)} engagement | {growth_str}"
            )

        return "\n".join(lines)

    @staticmethod
    def format_stats(stats: Dict[str, Any]) -> str:
        """Format statistics message."""
        period = stats.get("period_name", "24 hours")

        lines = [
            f"**Statistics ({period})**\n",
            f"Total Posts: {stats.get('total_posts', 0):,}",
            f"Posts in Period: {stats.get('period_posts', 0):,}",
            f"Total Engagement: {format_number(stats.get('period_engagement', 0))}",
            f"Total Topics: {stats.get('total_topics', 0):,}",
        ]

        top_users = stats.get("top_users", [])
        if top_users:
            lines.append("\n**Top Contributors:**")
            for i, user in enumerate(top_users[:5], 1):
                lines.append(
                    f"{i}. @{user['username']} - {user['post_count']} posts, "
                    f"{format_number(user['total_engagement'])} engagement"
                )

        return "\n".join(lines)

    @staticmethod
    def format_daily_digest(digest: DailyDigest) -> str:
        """Format daily digest message."""
        lines = [
            f"**Daily Digest - {digest.date}**\n",
            f"Posts: {digest.total_posts:,}",
            f"Total Engagement: {format_number(digest.total_engagement)}",
            f"New Topics: {digest.new_topics}",
            f"Milestone Alerts: {digest.milestone_alerts}",
            f"Spike Alerts: {digest.spike_alerts}",
        ]

        if digest.top_topics:
            lines.append("\n**Top Topics:**")
            for i, topic in enumerate(digest.top_topics[:5], 1):
                lines.append(f"{i}. {topic.topic} ({format_number(topic.total_engagement)} engagement)")

        if digest.top_posts:
            lines.append("\n**Top Posts:**")
            for i, post in enumerate(digest.top_posts[:3], 1):
                username = post.get("username", "unknown")
                text = truncate_text(post.get("text", ""), 100)
                engagement = post.get("engagement_score", 0)
                lines.append(f"{i}. @{username}: {text} ({format_number(engagement)})")

        return "\n".join(lines)

    @staticmethod
    def format_topic_analysis(analysis: Dict[str, Any]) -> str:
        """Format topic analysis message."""
        if "error" in analysis:
            return f"Topic not found: {analysis.get('topic', 'unknown')}"

        lines = [
            f"**Topic Analysis: {analysis['topic']}**\n",
            f"Total Posts: {analysis['total_posts']:,}",
            f"Total Engagement: {format_number(analysis['total_engagement'])}",
            f"Avg Engagement: {format_number(int(analysis['avg_engagement']))}",
            f"Max Engagement: {format_number(analysis['max_engagement'])}",
            f"First Seen: {analysis['first_seen'][:10] if analysis['first_seen'] else 'N/A'}",
            f"Last Seen: {analysis['last_seen'][:10] if analysis['last_seen'] else 'N/A'}",
        ]

        contributors = analysis.get("top_contributors", [])
        if contributors:
            lines.append("\n**Top Contributors:**")
            for c in contributors[:5]:
                lines.append(f"- @{c['username']}: {c['count']} posts, {format_number(c['engagement'])} engagement")

        return "\n".join(lines)

    @staticmethod
    def format_bot_status(status: Dict[str, Any]) -> str:
        """Format bot status message."""
        lines = [
            "**Bot Status**\n",
            f"Status: {'Running' if status.get('running') else 'Stopped'}",
            f"Total Posts: {status.get('total_posts', 0):,}",
            f"Total Topics: {status.get('total_topics', 0):,}",
            f"Last Scan: {status.get('last_scan', 'Never')}",
            f"Scan Status: {status.get('scan_status', 'Unknown')}",
            f"Posts Found (last scan): {status.get('posts_found', 0)}",
            f"New Posts (last scan): {status.get('new_posts', 0)}",
        ]

        scan_stats = status.get("scan_stats", {})
        if scan_stats:
            lines.append(f"\n**Last 24h Scans:**")
            lines.append(f"Total: {scan_stats.get('total_scans', 0)}")
            lines.append(f"Successful: {scan_stats.get('successful_scans', 0)}")
            lines.append(f"Failed: {scan_stats.get('failed_scans', 0)}")

        return "\n".join(lines)

    @staticmethod
    def format_settings(settings: Dict[str, Any]) -> str:
        """Format user settings message."""
        lines = [
            "**Your Settings**\n",
            f"Engagement Threshold: {format_number(settings.get('engagement_threshold', 1000))}",
            f"Milestone Alerts: {'On' if settings.get('notify_milestones') else 'Off'}",
            f"Spike Alerts: {'On' if settings.get('notify_spikes') else 'Off'}",
            f"Daily Digest: {'On' if settings.get('notify_daily_digest') else 'Off'}",
        ]

        filters = settings.get("keyword_filters", "")
        if filters:
            lines.append(f"Keyword Filters: {filters}")

        return "\n".join(lines)

    @staticmethod
    def format_help() -> str:
        """Format help message."""
        return """**Polymarket Nitter Monitor Bot**

**Commands:**

/start - Welcome message
/trending - Current hot topics with engagement stats
/topic <name> - Posts about specific Polymarket event
/stats [1h|6h|24h|7d] - Statistics for time period
/threshold <number> - Set minimum engagement for notifications
/filter <keywords> - Add keyword filters (comma-separated)
/export [csv|json] - Export collected data
/status - Bot health and last scan info
/settings - View/configure notification preferences
/search <query> - Search posts by text
/help - This help message

**Notifications:**
The bot can automatically notify you when:
- Posts cross engagement milestones (1K, 5K, 10K, etc.)
- Posts show sudden engagement spikes (+200%)
- Daily digest at 9:00 AM

Configure notifications with /settings command.

**Tips:**
- Use /trending to see what's hot right now
- Set /threshold to filter noise
- Export data for external analysis"""


@dataclass
class NotificationGroup:
    """Group of related notifications."""
    notifications: List[str]
    count: int
    group_type: str  # 'milestone', 'spike', 'digest'


class NotificationManager:
    """Manages notification sending with rate limiting and grouping."""

    def __init__(self, db: Optional[Database] = None, analytics: Optional[AnalyticsEngine] = None):
        self.db = db or get_database()
        self.analytics = analytics or get_analytics()
        self.formatter = NotificationFormatter()

    def should_send_notification(
        self,
        user_id: int,
        notification_type: str,
        reference_id: str
    ) -> bool:
        """Check if notification should be sent (rate limiting)."""
        # Check cooldown
        if self.db.was_notification_sent(
            user_id, notification_type, reference_id, config.NOTIFICATION_COOLDOWN
        ):
            return False

        # Check hourly rate limit
        count = self.db.get_notifications_count(user_id, hours=1)
        if count >= config.MAX_NOTIFICATIONS_PER_HOUR:
            logger.warning(f"Rate limit reached for user {user_id}")
            return False

        return True

    def get_pending_alerts(self, user_id: int) -> Dict[str, List]:
        """Get all pending alerts for a user."""
        settings = self.db.get_user_settings(user_id)
        if not settings:
            return {"milestones": [], "spikes": []}

        alerts = {"milestones": [], "spikes": []}

        # Get milestone alerts
        if settings.get("notify_milestones"):
            milestone_alerts = self.analytics.detect_milestone_alerts(since_hours=1)
            for alert in milestone_alerts:
                if self.should_send_notification(user_id, "milestone", alert.post_id):
                    # Check engagement threshold
                    if alert.current_engagement >= settings.get("engagement_threshold", 0):
                        alerts["milestones"].append(alert)

        # Get spike alerts
        if settings.get("notify_spikes"):
            spike_alerts = self.analytics.detect_spike_alerts()
            for alert in spike_alerts:
                if self.should_send_notification(user_id, "spike", alert.post_id):
                    if alert.current_engagement >= settings.get("engagement_threshold", 0):
                        alerts["spikes"].append(alert)

        return alerts

    def format_grouped_alerts(self, alerts: Dict[str, List]) -> List[str]:
        """Format alerts into grouped messages."""
        messages = []

        # Format milestones
        milestones = alerts.get("milestones", [])
        if milestones:
            if len(milestones) == 1:
                messages.append(self.formatter.format_milestone_alert(milestones[0]))
            else:
                # Group multiple milestones
                lines = [f"**{len(milestones)} Milestone Alerts**\n"]
                for alert in milestones[:5]:  # Limit to 5
                    lines.append(
                        f"- @{alert.username}: {format_number(alert.current_engagement)} "
                        f"(milestone: {format_number(alert.milestone)})"
                    )
                if len(milestones) > 5:
                    lines.append(f"... and {len(milestones) - 5} more")
                messages.append("\n".join(lines))

        # Format spikes
        spikes = alerts.get("spikes", [])
        if spikes:
            if len(spikes) == 1:
                messages.append(self.formatter.format_spike_alert(spikes[0]))
            else:
                lines = [f"**{len(spikes)} Spike Alerts**\n"]
                for alert in spikes[:5]:
                    lines.append(
                        f"- @{alert.username}: +{alert.spike_percent:.0f}% "
                        f"({format_number(alert.current_engagement)})"
                    )
                if len(spikes) > 5:
                    lines.append(f"... and {len(spikes) - 5} more")
                messages.append("\n".join(lines))

        return messages

    def mark_alerts_sent(self, user_id: int, alerts: Dict[str, List]):
        """Mark alerts as sent in the database."""
        for alert in alerts.get("milestones", []):
            self.db.log_notification(user_id, "milestone", alert.post_id)

        for alert in alerts.get("spikes", []):
            self.db.log_notification(user_id, "spike", alert.post_id)

    def generate_daily_digest_message(self) -> str:
        """Generate daily digest message."""
        digest = self.analytics.generate_daily_digest()
        return self.formatter.format_daily_digest(digest)

    def get_users_for_daily_digest(self) -> List[Dict]:
        """Get users who should receive daily digest."""
        users = self.db.get_all_users_for_notifications()
        return [u for u in users if u.get("notify_daily_digest")]


# Singleton instances
_formatter_instance: Optional[NotificationFormatter] = None
_manager_instance: Optional[NotificationManager] = None


def get_formatter() -> NotificationFormatter:
    """Get formatter instance."""
    global _formatter_instance
    if _formatter_instance is None:
        _formatter_instance = NotificationFormatter()
    return _formatter_instance


def get_notification_manager() -> NotificationManager:
    """Get notification manager instance."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = NotificationManager()
    return _manager_instance
