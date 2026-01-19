"""
Database operations for Polymarket Nitter Monitor Bot.
Handles SQLite storage, retrieval, and analytics queries.
"""
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager
from pathlib import Path

import config
from nitter_parser import NitterPost

logger = logging.getLogger(__name__)


def dict_factory(cursor: sqlite3.Cursor, row: Tuple) -> Dict[str, Any]:
    """Convert SQLite row to dictionary."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


class Database:
    """SQLite database manager for the bot."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or config.DATABASE_PATH
        self._init_db()

    @contextmanager
    def get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = dict_factory
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def _init_db(self):
        """Initialize database schema."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Posts table - main storage for scraped posts
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id TEXT UNIQUE NOT NULL,
                    name TEXT,
                    username TEXT NOT NULL,
                    profile_id TEXT,
                    created_at TEXT,
                    lang TEXT,
                    count_bookmark INTEGER DEFAULT 0,
                    count_impression INTEGER DEFAULT 0,
                    count_like INTEGER DEFAULT 0,
                    count_reply INTEGER DEFAULT 0,
                    count_retweet INTEGER DEFAULT 0,
                    count_quote INTEGER DEFAULT 0,
                    tweet_type TEXT,
                    has_media INTEGER DEFAULT 0,
                    text TEXT,
                    html_structure TEXT,
                    links TEXT,
                    images TEXT,
                    videos TEXT,
                    hashtags TEXT,
                    mentions TEXT,
                    media_urls TEXT,
                    polymarket_topics TEXT,
                    engagement_score INTEGER DEFAULT 0,
                    scraped_at TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_updated_at TEXT NOT NULL
                )
            """)

            # Engagement history - track engagement over time
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS engagement_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id TEXT NOT NULL,
                    count_like INTEGER DEFAULT 0,
                    count_reply INTEGER DEFAULT 0,
                    count_retweet INTEGER DEFAULT 0,
                    count_quote INTEGER DEFAULT 0,
                    engagement_score INTEGER DEFAULT 0,
                    recorded_at TEXT NOT NULL,
                    FOREIGN KEY (post_id) REFERENCES posts(post_id)
                )
            """)

            # Topics table - track Polymarket topics
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT UNIQUE NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    mention_count INTEGER DEFAULT 0,
                    total_engagement INTEGER DEFAULT 0
                )
            """)

            # Topic mentions - link posts to topics
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS topic_mentions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic_id INTEGER NOT NULL,
                    post_id TEXT NOT NULL,
                    mentioned_at TEXT NOT NULL,
                    FOREIGN KEY (topic_id) REFERENCES topics(id),
                    FOREIGN KEY (post_id) REFERENCES posts(post_id),
                    UNIQUE(topic_id, post_id)
                )
            """)

            # User settings - per-user notification preferences
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    engagement_threshold INTEGER DEFAULT 1000,
                    notify_milestones INTEGER DEFAULT 1,
                    notify_spikes INTEGER DEFAULT 1,
                    notify_daily_digest INTEGER DEFAULT 1,
                    keyword_filters TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Notifications log - track sent notifications to avoid spam
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notifications_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    notification_type TEXT NOT NULL,
                    reference_id TEXT,
                    sent_at TEXT NOT NULL
                )
            """)

            # Scan history - track scraping operations
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scan_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    posts_found INTEGER DEFAULT 0,
                    new_posts INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'running',
                    error_message TEXT
                )
            """)

            # Create indexes for fast queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_post_id ON posts(post_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_engagement ON posts(engagement_score DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_username ON posts(username)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_engagement_history_post ON engagement_history(post_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_engagement_history_time ON engagement_history(recorded_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_topics_topic ON topics(topic)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_topic_mentions_topic ON topic_mentions(topic_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications_log(user_id, sent_at)")

            logger.info("Database initialized successfully")

    # ============ POST OPERATIONS ============

    def insert_post(self, post: NitterPost) -> Tuple[bool, bool]:
        """
        Insert or update a post.
        Returns (success, is_new).
        """
        now = datetime.utcnow().isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Check if post exists
            cursor.execute("SELECT id, engagement_score FROM posts WHERE post_id = ?", (post.post_id,))
            existing = cursor.fetchone()

            if existing:
                # Update existing post
                old_engagement = existing["engagement_score"]
                cursor.execute("""
                    UPDATE posts SET
                        count_like = ?,
                        count_reply = ?,
                        count_retweet = ?,
                        count_quote = ?,
                        engagement_score = ?,
                        last_updated_at = ?
                    WHERE post_id = ?
                """, (
                    post.count_like,
                    post.count_reply,
                    post.count_retweet,
                    post.count_quote,
                    post.engagement_score,
                    now,
                    post.post_id
                ))

                # Record engagement history if changed
                if post.engagement_score != old_engagement:
                    cursor.execute("""
                        INSERT INTO engagement_history
                        (post_id, count_like, count_reply, count_retweet, count_quote, engagement_score, recorded_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        post.post_id,
                        post.count_like,
                        post.count_reply,
                        post.count_retweet,
                        post.count_quote,
                        post.engagement_score,
                        now
                    ))

                return True, False  # Updated, not new

            else:
                # Insert new post
                cursor.execute("""
                    INSERT INTO posts (
                        post_id, name, username, profile_id, created_at, lang,
                        count_bookmark, count_impression, count_like, count_reply,
                        count_retweet, count_quote, tweet_type, has_media, text,
                        html_structure, links, images, videos, hashtags, mentions,
                        media_urls, polymarket_topics, engagement_score, scraped_at,
                        first_seen_at, last_updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    post.post_id, post.name, post.username, post.profile_id,
                    post.created_at, post.lang, post.count_bookmark, post.count_impression,
                    post.count_like, post.count_reply, post.count_retweet, post.count_quote,
                    post.tweet_type, int(post.has_media), post.text, post.html_structure,
                    post.links, post.images, post.videos, post.hashtags, post.mentions,
                    post.media_urls, post.polymarket_topics, post.engagement_score,
                    post.scraped_at, now, now
                ))

                # Record initial engagement
                cursor.execute("""
                    INSERT INTO engagement_history
                    (post_id, count_like, count_reply, count_retweet, count_quote, engagement_score, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    post.post_id,
                    post.count_like,
                    post.count_reply,
                    post.count_retweet,
                    post.count_quote,
                    post.engagement_score,
                    now
                ))

                # Process topics
                if post.polymarket_topics:
                    topics = [t.strip() for t in post.polymarket_topics.split(",") if t.strip()]
                    for topic in topics:
                        self._add_topic_mention(cursor, topic, post.post_id, post.engagement_score, now)

                return True, True  # Inserted, is new

    def _add_topic_mention(
        self,
        cursor: sqlite3.Cursor,
        topic: str,
        post_id: str,
        engagement: int,
        timestamp: str
    ):
        """Add or update topic and its mention."""
        # Insert or update topic
        cursor.execute("""
            INSERT INTO topics (topic, first_seen_at, last_seen_at, mention_count, total_engagement)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(topic) DO UPDATE SET
                last_seen_at = excluded.last_seen_at,
                mention_count = mention_count + 1,
                total_engagement = total_engagement + excluded.total_engagement
        """, (topic, timestamp, timestamp, engagement))

        # Get topic ID
        cursor.execute("SELECT id FROM topics WHERE topic = ?", (topic,))
        topic_row = cursor.fetchone()
        if topic_row:
            # Add mention link
            cursor.execute("""
                INSERT OR IGNORE INTO topic_mentions (topic_id, post_id, mentioned_at)
                VALUES (?, ?, ?)
            """, (topic_row["id"], post_id, timestamp))

    def bulk_insert_posts(self, posts: List[NitterPost]) -> Tuple[int, int]:
        """
        Bulk insert posts.
        Returns (total_processed, new_count).
        """
        new_count = 0
        for post in posts:
            success, is_new = self.insert_post(post)
            if is_new:
                new_count += 1
        return len(posts), new_count

    def get_latest_post_id(self) -> Optional[str]:
        """Get the most recent post ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT post_id FROM posts ORDER BY first_seen_at DESC LIMIT 1")
            row = cursor.fetchone()
            return row["post_id"] if row else None

    def get_post(self, post_id: str) -> Optional[Dict]:
        """Get a single post by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM posts WHERE post_id = ?", (post_id,))
            return cursor.fetchone()

    def get_posts_by_engagement(
        self,
        min_engagement: int = 0,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict]:
        """Get posts sorted by engagement."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM posts
                WHERE engagement_score >= ?
                ORDER BY engagement_score DESC
                LIMIT ? OFFSET ?
            """, (min_engagement, limit, offset))
            return cursor.fetchall()

    def get_posts_since(
        self,
        since: datetime,
        min_engagement: int = 0
    ) -> List[Dict]:
        """Get posts since a specific time."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM posts
                WHERE first_seen_at >= ? AND engagement_score >= ?
                ORDER BY first_seen_at DESC
            """, (since.isoformat(), min_engagement))
            return cursor.fetchall()

    def get_posts_by_topic(self, topic: str, limit: int = 50) -> List[Dict]:
        """Get posts mentioning a specific topic."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.* FROM posts p
                JOIN topic_mentions tm ON p.post_id = tm.post_id
                JOIN topics t ON tm.topic_id = t.id
                WHERE t.topic LIKE ?
                ORDER BY p.engagement_score DESC
                LIMIT ?
            """, (f"%{topic}%", limit))
            return cursor.fetchall()

    def search_posts(self, query: str, limit: int = 50) -> List[Dict]:
        """Search posts by text content."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM posts
                WHERE text LIKE ? OR hashtags LIKE ?
                ORDER BY engagement_score DESC
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", limit))
            return cursor.fetchall()

    def get_posts_count(self) -> int:
        """Get total number of posts."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM posts")
            return cursor.fetchone()["count"]

    # ============ TOPIC OPERATIONS ============

    def get_trending_topics(self, hours: int = 24, limit: int = 10) -> List[Dict]:
        """Get trending topics in the last N hours."""
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    t.topic,
                    COUNT(DISTINCT tm.post_id) as mention_count,
                    SUM(p.engagement_score) as total_engagement,
                    MAX(p.first_seen_at) as last_mention
                FROM topics t
                JOIN topic_mentions tm ON t.id = tm.topic_id
                JOIN posts p ON tm.post_id = p.post_id
                WHERE tm.mentioned_at >= ?
                GROUP BY t.id
                ORDER BY total_engagement DESC
                LIMIT ?
            """, (since, limit))
            return cursor.fetchall()

    def get_topic_stats(self, topic: str) -> Optional[Dict]:
        """Get statistics for a specific topic."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    t.*,
                    (SELECT COUNT(*) FROM topic_mentions WHERE topic_id = t.id) as post_count,
                    (SELECT SUM(engagement_score) FROM posts p
                     JOIN topic_mentions tm ON p.post_id = tm.post_id
                     WHERE tm.topic_id = t.id) as total_engagement
                FROM topics t
                WHERE t.topic LIKE ?
            """, (f"%{topic}%",))
            return cursor.fetchone()

    def get_all_topics(self, limit: int = 100) -> List[Dict]:
        """Get all topics sorted by engagement."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM topics
                ORDER BY total_engagement DESC
                LIMIT ?
            """, (limit,))
            return cursor.fetchall()

    # ============ ENGAGEMENT TRACKING ============

    def get_engagement_history(
        self,
        post_id: str,
        hours: int = 24
    ) -> List[Dict]:
        """Get engagement history for a post."""
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM engagement_history
                WHERE post_id = ? AND recorded_at >= ?
                ORDER BY recorded_at ASC
            """, (post_id, since))
            return cursor.fetchall()

    def get_posts_crossing_threshold(
        self,
        threshold: int,
        since_hours: int = 1
    ) -> List[Dict]:
        """Get posts that crossed an engagement threshold recently."""
        since = (datetime.utcnow() - timedelta(hours=since_hours)).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT p.* FROM posts p
                JOIN engagement_history eh ON p.post_id = eh.post_id
                WHERE p.engagement_score >= ?
                AND EXISTS (
                    SELECT 1 FROM engagement_history eh2
                    WHERE eh2.post_id = p.post_id
                    AND eh2.engagement_score < ?
                    AND eh2.recorded_at < eh.recorded_at
                )
                AND eh.recorded_at >= ?
                ORDER BY p.engagement_score DESC
            """, (threshold, threshold, since))
            return cursor.fetchall()

    def detect_engagement_spikes(
        self,
        spike_percent: int = 200,
        window_hours: int = 1
    ) -> List[Dict]:
        """Detect posts with engagement spikes."""
        since = (datetime.utcnow() - timedelta(hours=window_hours)).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Get posts with significant engagement changes
            cursor.execute("""
                SELECT
                    p.*,
                    eh_old.engagement_score as old_engagement,
                    eh_new.engagement_score as new_engagement,
                    CASE
                        WHEN eh_old.engagement_score > 0
                        THEN ((eh_new.engagement_score - eh_old.engagement_score) * 100.0 / eh_old.engagement_score)
                        ELSE 100
                    END as percent_change
                FROM posts p
                JOIN engagement_history eh_new ON p.post_id = eh_new.post_id
                JOIN engagement_history eh_old ON p.post_id = eh_old.post_id
                WHERE eh_new.recorded_at >= ?
                AND eh_old.recorded_at < eh_new.recorded_at
                AND eh_old.id = (
                    SELECT MAX(id) FROM engagement_history
                    WHERE post_id = p.post_id AND recorded_at < ?
                )
                AND ((eh_new.engagement_score - eh_old.engagement_score) * 100.0 /
                     CASE WHEN eh_old.engagement_score > 0 THEN eh_old.engagement_score ELSE 1 END) >= ?
                ORDER BY percent_change DESC
            """, (since, since, spike_percent))
            return cursor.fetchall()

    # ============ USER SETTINGS ============

    def get_user_settings(self, user_id: int) -> Optional[Dict]:
        """Get user settings."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,))
            return cursor.fetchone()

    def set_user_settings(
        self,
        user_id: int,
        chat_id: int,
        **settings
    ) -> bool:
        """Create or update user settings."""
        now = datetime.utcnow().isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Check if exists
            cursor.execute("SELECT user_id FROM user_settings WHERE user_id = ?", (user_id,))
            existing = cursor.fetchone()

            if existing:
                # Build update query
                updates = []
                values = []
                for key, value in settings.items():
                    if key in ["engagement_threshold", "notify_milestones", "notify_spikes",
                               "notify_daily_digest", "keyword_filters"]:
                        updates.append(f"{key} = ?")
                        values.append(value)

                if updates:
                    updates.append("updated_at = ?")
                    values.append(now)
                    values.append(user_id)

                    cursor.execute(
                        f"UPDATE user_settings SET {', '.join(updates)} WHERE user_id = ?",
                        values
                    )
            else:
                # Insert new
                cursor.execute("""
                    INSERT INTO user_settings (
                        user_id, chat_id, engagement_threshold, notify_milestones,
                        notify_spikes, notify_daily_digest, keyword_filters,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, chat_id,
                    settings.get("engagement_threshold", config.DEFAULT_ENGAGEMENT_THRESHOLD),
                    settings.get("notify_milestones", 1),
                    settings.get("notify_spikes", 1),
                    settings.get("notify_daily_digest", 1),
                    settings.get("keyword_filters", ""),
                    now, now
                ))

            return True

    def get_all_users_for_notifications(self) -> List[Dict]:
        """Get all users who have notifications enabled."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM user_settings
                WHERE notify_milestones = 1 OR notify_spikes = 1 OR notify_daily_digest = 1
            """)
            return cursor.fetchall()

    # ============ NOTIFICATION LOGGING ============

    def log_notification(
        self,
        user_id: int,
        notification_type: str,
        reference_id: Optional[str] = None
    ):
        """Log a sent notification."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO notifications_log (user_id, notification_type, reference_id, sent_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, notification_type, reference_id, datetime.utcnow().isoformat()))

    def was_notification_sent(
        self,
        user_id: int,
        notification_type: str,
        reference_id: str,
        cooldown_seconds: int = 300
    ) -> bool:
        """Check if a similar notification was recently sent."""
        since = (datetime.utcnow() - timedelta(seconds=cooldown_seconds)).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) as count FROM notifications_log
                WHERE user_id = ? AND notification_type = ? AND reference_id = ? AND sent_at >= ?
            """, (user_id, notification_type, reference_id, since))
            return cursor.fetchone()["count"] > 0

    def get_notifications_count(self, user_id: int, hours: int = 1) -> int:
        """Get notification count for rate limiting."""
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) as count FROM notifications_log
                WHERE user_id = ? AND sent_at >= ?
            """, (user_id, since))
            return cursor.fetchone()["count"]

    # ============ SCAN HISTORY ============

    def start_scan(self) -> int:
        """Record start of a scan, return scan ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO scan_history (started_at, status)
                VALUES (?, 'running')
            """, (datetime.utcnow().isoformat(),))
            return cursor.lastrowid

    def complete_scan(
        self,
        scan_id: int,
        posts_found: int,
        new_posts: int,
        error: Optional[str] = None
    ):
        """Record completion of a scan."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE scan_history SET
                    completed_at = ?,
                    posts_found = ?,
                    new_posts = ?,
                    status = ?,
                    error_message = ?
                WHERE id = ?
            """, (
                datetime.utcnow().isoformat(),
                posts_found,
                new_posts,
                "error" if error else "completed",
                error,
                scan_id
            ))

    def get_last_scan(self) -> Optional[Dict]:
        """Get the most recent scan info."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM scan_history
                ORDER BY id DESC
                LIMIT 1
            """)
            return cursor.fetchone()

    def get_scan_stats(self, hours: int = 24) -> Dict:
        """Get scan statistics."""
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    COUNT(*) as total_scans,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful_scans,
                    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as failed_scans,
                    SUM(posts_found) as total_posts_found,
                    SUM(new_posts) as total_new_posts
                FROM scan_history
                WHERE started_at >= ?
            """, (since,))
            return cursor.fetchone()

    # ============ STATISTICS ============

    def get_stats(self, period_seconds: int = 86400) -> Dict:
        """Get overall statistics for a time period."""
        since = (datetime.utcnow() - timedelta(seconds=period_seconds)).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Total posts
            cursor.execute("SELECT COUNT(*) as count FROM posts")
            total_posts = cursor.fetchone()["count"]

            # Posts in period
            cursor.execute(
                "SELECT COUNT(*) as count FROM posts WHERE first_seen_at >= ?",
                (since,)
            )
            period_posts = cursor.fetchone()["count"]

            # Total engagement in period
            cursor.execute("""
                SELECT SUM(engagement_score) as total FROM posts
                WHERE first_seen_at >= ?
            """, (since,))
            period_engagement = cursor.fetchone()["total"] or 0

            # Top users in period
            cursor.execute("""
                SELECT username, COUNT(*) as post_count, SUM(engagement_score) as total_engagement
                FROM posts
                WHERE first_seen_at >= ?
                GROUP BY username
                ORDER BY total_engagement DESC
                LIMIT 5
            """, (since,))
            top_users = cursor.fetchall()

            # Topic count
            cursor.execute("SELECT COUNT(*) as count FROM topics")
            total_topics = cursor.fetchone()["count"]

            return {
                "total_posts": total_posts,
                "period_posts": period_posts,
                "period_engagement": period_engagement,
                "top_users": top_users,
                "total_topics": total_topics,
                "period_name": self._get_period_name(period_seconds),
            }

    @staticmethod
    def _get_period_name(seconds: int) -> str:
        """Get human-readable period name."""
        if seconds <= 3600:
            return "1 hour"
        elif seconds <= 21600:
            return "6 hours"
        elif seconds <= 86400:
            return "24 hours"
        elif seconds <= 604800:
            return "7 days"
        else:
            return f"{seconds // 86400} days"

    # ============ EXPORT ============

    def export_posts(
        self,
        since: Optional[datetime] = None,
        min_engagement: int = 0,
        topic: Optional[str] = None
    ) -> List[Dict]:
        """Export posts with optional filters."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM posts WHERE 1=1"
            params = []

            if since:
                query += " AND first_seen_at >= ?"
                params.append(since.isoformat())

            if min_engagement > 0:
                query += " AND engagement_score >= ?"
                params.append(min_engagement)

            if topic:
                query += " AND polymarket_topics LIKE ?"
                params.append(f"%{topic}%")

            query += " ORDER BY engagement_score DESC"

            cursor.execute(query, params)
            return cursor.fetchall()


# Singleton instance
_db_instance: Optional[Database] = None


def get_database() -> Database:
    """Get or create database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
