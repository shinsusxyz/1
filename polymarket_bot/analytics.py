"""
Analytics Engine for Polymarket Nitter Monitor Bot.
Handles trending detection, statistics calculation, and data analysis.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from collections import defaultdict

import config
from database import get_database, Database

logger = logging.getLogger(__name__)


@dataclass
class TrendingTopic:
    """A trending topic with statistics."""
    topic: str
    mention_count: int
    total_engagement: int
    growth_rate: float  # Percentage growth
    top_posts: List[Dict]
    first_seen: str
    last_seen: str


@dataclass
class EngagementAlert:
    """Alert for engagement milestone or spike."""
    post_id: str
    username: str
    text: str
    current_engagement: int
    previous_engagement: int
    alert_type: str  # 'milestone' or 'spike'
    milestone: Optional[int] = None
    spike_percent: Optional[float] = None


@dataclass
class DailyDigest:
    """Daily summary statistics."""
    date: str
    total_posts: int
    total_engagement: int
    new_topics: int
    top_topics: List[TrendingTopic]
    top_posts: List[Dict]
    milestone_alerts: int
    spike_alerts: int


class AnalyticsEngine:
    """Analytics engine for calculating trends and statistics."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()

    def calculate_engagement_score(
        self,
        likes: int,
        retweets: int,
        replies: int,
        quotes: int = 0
    ) -> int:
        """
        Calculate engagement score.
        Simple sum for now, could be weighted.
        """
        return likes + retweets + replies + quotes

    def get_trending_topics(
        self,
        hours: int = 24,
        limit: int = 10
    ) -> List[TrendingTopic]:
        """
        Get trending topics with full statistics.
        """
        topics = self.db.get_trending_topics(hours=hours, limit=limit)
        result = []

        for t in topics:
            # Get top posts for this topic
            top_posts = self.db.get_posts_by_topic(t["topic"], limit=5)

            # Calculate growth rate (compare to previous period)
            growth_rate = self._calculate_topic_growth(t["topic"], hours)

            result.append(TrendingTopic(
                topic=t["topic"],
                mention_count=t["mention_count"],
                total_engagement=t["total_engagement"] or 0,
                growth_rate=growth_rate,
                top_posts=top_posts,
                first_seen=t.get("first_seen_at", ""),
                last_seen=t.get("last_mention", ""),
            ))

        return result

    def _calculate_topic_growth(self, topic: str, hours: int) -> float:
        """
        Calculate growth rate compared to previous period.
        Returns percentage change.
        """
        now = datetime.utcnow()
        current_start = now - timedelta(hours=hours)
        previous_start = current_start - timedelta(hours=hours)

        # Get engagement for both periods
        current_posts = self.db.get_posts_by_topic(topic, limit=1000)
        current_engagement = sum(
            p["engagement_score"] for p in current_posts
            if p.get("first_seen_at", "") >= current_start.isoformat()
        )

        previous_engagement = sum(
            p["engagement_score"] for p in current_posts
            if previous_start.isoformat() <= p.get("first_seen_at", "") < current_start.isoformat()
        )

        if previous_engagement == 0:
            return 100.0 if current_engagement > 0 else 0.0

        return ((current_engagement - previous_engagement) / previous_engagement) * 100

    def detect_milestone_alerts(
        self,
        since_hours: int = 1
    ) -> List[EngagementAlert]:
        """
        Detect posts that crossed engagement milestones.
        """
        alerts = []

        for milestone in config.ENGAGEMENT_MILESTONES:
            posts = self.db.get_posts_crossing_threshold(milestone, since_hours)

            for post in posts:
                # Get previous engagement
                history = self.db.get_engagement_history(post["post_id"], hours=since_hours + 1)
                previous = history[0]["engagement_score"] if history else 0

                # Only alert if actually crossed this milestone
                if previous < milestone <= post["engagement_score"]:
                    alerts.append(EngagementAlert(
                        post_id=post["post_id"],
                        username=post["username"],
                        text=post["text"][:200],
                        current_engagement=post["engagement_score"],
                        previous_engagement=previous,
                        alert_type="milestone",
                        milestone=milestone,
                    ))

        return alerts

    def detect_spike_alerts(
        self,
        spike_percent: int = None,
        window_hours: int = None
    ) -> List[EngagementAlert]:
        """
        Detect posts with sudden engagement spikes.
        """
        if spike_percent is None:
            spike_percent = config.SPIKE_THRESHOLD_PERCENT
        if window_hours is None:
            window_hours = config.SPIKE_WINDOW_HOURS

        alerts = []
        spikes = self.db.detect_engagement_spikes(spike_percent, window_hours)

        for spike in spikes:
            alerts.append(EngagementAlert(
                post_id=spike["post_id"],
                username=spike["username"],
                text=spike["text"][:200],
                current_engagement=spike["new_engagement"],
                previous_engagement=spike["old_engagement"],
                alert_type="spike",
                spike_percent=spike["percent_change"],
            ))

        return alerts

    def get_period_stats(self, period: str = "24h") -> Dict[str, Any]:
        """
        Get statistics for a time period.

        Args:
            period: One of '1h', '6h', '24h', '7d'
        """
        seconds = config.TIME_PERIODS.get(period, 86400)
        stats = self.db.get_stats(seconds)

        # Get trending topics for the period
        hours = seconds // 3600
        trending = self.get_trending_topics(hours=hours, limit=5)

        # Get top posts
        since = datetime.utcnow() - timedelta(seconds=seconds)
        top_posts = self.db.get_posts_since(since, min_engagement=100)[:10]

        return {
            **stats,
            "trending_topics": trending,
            "top_posts": top_posts,
            "period": period,
        }

    def compare_periods(
        self,
        period1: str = "24h",
        period2: str = "7d"
    ) -> Dict[str, Any]:
        """
        Compare statistics between two periods.
        """
        stats1 = self.get_period_stats(period1)
        stats2 = self.get_period_stats(period2)

        # Calculate deltas
        post_delta = stats1["period_posts"] - (stats2["period_posts"] / 7) if period2 == "7d" else 0
        engagement_delta = stats1["period_engagement"] - (stats2["period_engagement"] / 7) if period2 == "7d" else 0

        return {
            "current": stats1,
            "previous": stats2,
            "post_delta": post_delta,
            "engagement_delta": engagement_delta,
            "post_growth_percent": (post_delta / max(stats2["period_posts"] / 7, 1)) * 100 if period2 == "7d" else 0,
            "engagement_growth_percent": (engagement_delta / max(stats2["period_engagement"] / 7, 1)) * 100 if period2 == "7d" else 0,
        }

    def generate_daily_digest(self, date: Optional[datetime] = None) -> DailyDigest:
        """
        Generate a daily digest summary.
        """
        if date is None:
            date = datetime.utcnow() - timedelta(days=1)

        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)

        # Get posts for the day
        posts = self.db.get_posts_since(start, min_engagement=0)
        day_posts = [p for p in posts if p.get("first_seen_at", "") < end.isoformat()]

        # Calculate totals
        total_posts = len(day_posts)
        total_engagement = sum(p["engagement_score"] for p in day_posts)

        # Get trending topics
        trending = self.get_trending_topics(hours=24, limit=config.TOP_TOPICS_COUNT)

        # Get top posts
        top_posts = sorted(day_posts, key=lambda p: p["engagement_score"], reverse=True)[:10]

        # Count alerts
        milestone_alerts = len(self.detect_milestone_alerts(since_hours=24))
        spike_alerts = len(self.detect_spike_alerts(window_hours=24))

        # Count new topics (simplified)
        all_topics = self.db.get_all_topics(limit=1000)
        new_topics = len([
            t for t in all_topics
            if t.get("first_seen_at", "") >= start.isoformat()
            and t.get("first_seen_at", "") < end.isoformat()
        ])

        return DailyDigest(
            date=start.strftime("%Y-%m-%d"),
            total_posts=total_posts,
            total_engagement=total_engagement,
            new_topics=new_topics,
            top_topics=trending,
            top_posts=top_posts,
            milestone_alerts=milestone_alerts,
            spike_alerts=spike_alerts,
        )

    def get_topic_analysis(self, topic: str) -> Dict[str, Any]:
        """
        Get detailed analysis for a specific topic.
        """
        stats = self.db.get_topic_stats(topic)
        posts = self.db.get_posts_by_topic(topic, limit=100)

        if not stats or not posts:
            return {"error": "Topic not found"}

        # Calculate engagement distribution
        engagements = [p["engagement_score"] for p in posts]
        avg_engagement = sum(engagements) / len(engagements) if engagements else 0
        max_engagement = max(engagements) if engagements else 0

        # Get timeline (mentions over time)
        timeline = defaultdict(int)
        for post in posts:
            date = post.get("first_seen_at", "")[:10]
            if date:
                timeline[date] += 1

        # Top contributors
        contributors = defaultdict(lambda: {"count": 0, "engagement": 0})
        for post in posts:
            username = post["username"]
            contributors[username]["count"] += 1
            contributors[username]["engagement"] += post["engagement_score"]

        top_contributors = sorted(
            contributors.items(),
            key=lambda x: x[1]["engagement"],
            reverse=True
        )[:5]

        return {
            "topic": topic,
            "total_posts": len(posts),
            "total_engagement": stats.get("total_engagement", 0),
            "avg_engagement": round(avg_engagement, 1),
            "max_engagement": max_engagement,
            "first_seen": stats.get("first_seen_at", ""),
            "last_seen": stats.get("last_seen_at", ""),
            "timeline": dict(sorted(timeline.items())),
            "top_contributors": [
                {"username": u, **data} for u, data in top_contributors
            ],
            "top_posts": posts[:5],
        }

    def get_user_analysis(self, username: str) -> Dict[str, Any]:
        """
        Get analysis for a specific user's posts.
        """
        posts = self.db.search_posts(f"@{username}" if not username.startswith("@") else username)

        # Also search by username field
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM posts WHERE username = ? ORDER BY engagement_score DESC LIMIT 100",
                (username.lstrip("@"),)
            )
            user_posts = cursor.fetchall()

        if not user_posts:
            return {"error": "User not found"}

        engagements = [p["engagement_score"] for p in user_posts]

        return {
            "username": username,
            "total_posts": len(user_posts),
            "total_engagement": sum(engagements),
            "avg_engagement": round(sum(engagements) / len(engagements), 1),
            "max_engagement": max(engagements),
            "top_posts": user_posts[:5],
        }

    def search_and_analyze(
        self,
        query: str,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Search posts and provide analysis.
        """
        posts = self.db.search_posts(query, limit=limit)

        if not posts:
            return {"query": query, "count": 0, "posts": []}

        engagements = [p["engagement_score"] for p in posts]

        return {
            "query": query,
            "count": len(posts),
            "total_engagement": sum(engagements),
            "avg_engagement": round(sum(engagements) / len(engagements), 1),
            "posts": posts,
        }


# Singleton instance
_analytics_instance: Optional[AnalyticsEngine] = None


def get_analytics() -> AnalyticsEngine:
    """Get or create analytics engine instance."""
    global _analytics_instance
    if _analytics_instance is None:
        _analytics_instance = AnalyticsEngine()
    return _analytics_instance
