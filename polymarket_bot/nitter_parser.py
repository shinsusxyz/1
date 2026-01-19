"""
Nitter Parser - Core scraping logic translated from JavaScript.
Handles parsing search results from Nitter instances.
"""
import re
import time
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple
from urllib.parse import urlencode, urlparse, parse_qs, unquote
from dataclasses import dataclass, asdict
import json

import requests
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)


@dataclass
class NitterPost:
    """Data structure for a parsed Nitter post (matches JS scraper structure)."""
    post_id: str
    name: str                   # Full name
    username: str               # @username without @
    profile_id: str
    created_at: str
    lang: str
    count_bookmark: int
    count_impression: int
    count_like: int
    count_reply: int
    count_retweet: int
    count_quote: int
    tweet_type: str             # post, reply, quote
    has_media: bool
    text: str
    html_structure: str
    links: str                  # JSON string of links
    images: str                 # JSON string of images
    videos: str                 # JSON string of videos
    hashtags: str               # Comma-separated
    mentions: str               # Comma-separated
    media_urls: str             # Pipe-separated
    polymarket_topics: str      # Extracted Polymarket event topics
    engagement_score: int       # likes + retweets + replies + quotes
    scraped_at: str             # When this post was scraped

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class NitterParser:
    """
    Parser for Nitter search results.
    Replicates the JavaScript scraper logic in Python.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "User-Agent": config.USER_AGENT,
        })
        self.current_instance_index = 0
        self.instances = config.NITTER_INSTANCES.copy()

    def _get_current_instance(self) -> str:
        """Get current Nitter instance."""
        if not self.instances:
            self.instances = config.NITTER_INSTANCES.copy()
            self.current_instance_index = 0
        return self.instances[self.current_instance_index % len(self.instances)]

    def _switch_instance(self) -> str:
        """Switch to next Nitter instance."""
        self.current_instance_index += 1
        new_instance = self._get_current_instance()
        logger.info(f"Switched to Nitter instance: {new_instance}")
        return new_instance

    @staticmethod
    def parse_stat_number(text: Optional[str]) -> int:
        """
        Parse stat numbers like '1.2K', '5M', '100'.
        Replicates JS parseStatNumber function.
        """
        if not text:
            return 0

        text = text.strip().replace(",", "")

        # Handle K, M, B suffixes
        match = re.match(r"^([\d.]+)\s*([KMB])$", text, re.IGNORECASE)
        if match:
            num = float(match.group(1))
            suffix = match.group(2).upper()
            multipliers = {"K": 1000, "M": 1000000, "B": 1000000000}
            return round(num * multipliers[suffix])

        # Extract digits only
        digits = re.sub(r"\D", "", text)
        return int(digits) if digits else 0

    def build_search_url(
        self,
        params: Dict[str, str],
        cursor: str = "",
        instance: Optional[str] = None
    ) -> str:
        """
        Build search URL with parameters.
        Replicates JS buildSearchUrl function.
        """
        if instance is None:
            instance = self._get_current_instance()

        query_params = {k: v for k, v in params.items() if v}
        if cursor:
            query_params["cursor"] = cursor

        return f"{instance}/search?{urlencode(query_params)}"

    def _extract_cursor(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract cursor for pagination from 'load more' link.
        """
        # Look for load more link with cursor
        load_more = soup.select_one('a[href*="cursor="]')
        if not load_more:
            load_more = soup.select_one("a.show-more, .show-more a, .load-more")

        if load_more:
            href = load_more.get("href", "")
            cursor_match = re.search(r"cursor=([^&]+)", href)
            if cursor_match:
                return unquote(cursor_match.group(1))

            # Try to parse from full URL
            if href:
                try:
                    parsed = urlparse(href if href.startswith("http") else f"https://example.com{href}")
                    params = parse_qs(parsed.query)
                    if "cursor" in params:
                        return params["cursor"][0]
                except Exception:
                    pass

        return None

    def _extract_polymarket_topics(self, text: str, links: List[Dict]) -> List[str]:
        """
        Extract Polymarket event topics from text and links.
        """
        topics = []

        # Check text for Polymarket URLs
        for match in re.finditer(config.POLYMARKET_URL_PATTERN, text):
            topic = match.group(1)
            if topic not in topics:
                topics.append(topic)

        # Check links
        for link in links:
            url = link.get("url", "")
            for match in re.finditer(config.POLYMARKET_URL_PATTERN, url):
                topic = match.group(1)
                if topic not in topics:
                    topics.append(topic)

        return topics

    def _parse_post(self, post_element: BeautifulSoup, instance: str) -> Optional[NitterPost]:
        """
        Parse a single post element.
        Replicates JS parsePost function.
        """
        try:
            # Post ID from status link
            tweet_link = post_element.select_one('a[href*="/status/"]')
            post_id = ""
            if tweet_link:
                href = tweet_link.get("href", "")
                match = re.search(r"/status/(\d+)", href)
                if match:
                    post_id = match.group(1)

            if not post_id:
                return None

            # Author info
            author_link = post_element.select_one(".username a")
            username = ""
            if author_link:
                username = author_link.get_text().replace("@", "").strip()

            fullname_elem = post_element.select_one(".fullname")
            name = fullname_elem.get_text().strip() if fullname_elem else ""

            # Profile ID
            profile_link = post_element.select_one(".avatar a")
            profile_id = ""
            if profile_link:
                href = profile_link.get("href", "")
                profile_id = href.split("/")[-1] if href else ""

            # Created at - parse date
            date_elem = post_element.select_one('.tweet-date a, a[href*="/status/"] .tweet-date a')
            created_at = ""
            if date_elem:
                date_text = date_elem.get("title") or date_elem.get_text()
                try:
                    # Try various date formats
                    for fmt in [
                        "%b %d, %Y · %I:%M %p %Z",
                        "%b %d, %Y · %I:%M %p",
                        "%Y-%m-%d %H:%M:%S",
                        "%d/%m/%Y %H:%M:%S",
                    ]:
                        try:
                            dt = datetime.strptime(date_text.strip(), fmt)
                            created_at = dt.strftime("%m/%d/%Y %H:%M:%S")
                            break
                        except ValueError:
                            continue

                    if not created_at:
                        created_at = date_text.strip()
                except Exception:
                    created_at = date_text.strip() if date_text else ""

            # Language
            lang_elem = post_element.select_one("[lang]")
            lang = lang_elem.get("lang", "und") if lang_elem else "und"

            # Stats
            like_elem = post_element.select_one(".icon-heart + span, .tweet-stat .icon-heart")
            reply_elem = post_element.select_one(".icon-comment + span, .tweet-stat .icon-comment")
            retweet_elem = post_element.select_one(".icon-retweet + span, .tweet-stat .icon-retweet")
            quote_elem = post_element.select_one(".icon-quote + span, .tweet-stat .icon-quote")

            # For stats, also try parent element text
            count_like = 0
            count_reply = 0
            count_retweet = 0
            count_quote = 0

            for stat in post_element.select(".tweet-stat"):
                stat_text = stat.get_text()
                if "heart" in str(stat) or "like" in stat_text.lower():
                    count_like = self.parse_stat_number(stat_text)
                elif "comment" in str(stat) or "repl" in stat_text.lower():
                    count_reply = self.parse_stat_number(stat_text)
                elif "retweet" in str(stat):
                    count_retweet = self.parse_stat_number(stat_text)
                elif "quote" in str(stat):
                    count_quote = self.parse_stat_number(stat_text)

            # Fallback to individual elements
            if not count_like and like_elem:
                parent = like_elem.parent
                count_like = self.parse_stat_number(parent.get_text() if parent else like_elem.get_text())
            if not count_reply and reply_elem:
                parent = reply_elem.parent
                count_reply = self.parse_stat_number(parent.get_text() if parent else reply_elem.get_text())
            if not count_retweet and retweet_elem:
                parent = retweet_elem.parent
                count_retweet = self.parse_stat_number(parent.get_text() if parent else retweet_elem.get_text())
            if not count_quote and quote_elem:
                parent = quote_elem.parent
                count_quote = self.parse_stat_number(parent.get_text() if parent else quote_elem.get_text())

            # Tweet type
            tweet_type = "post"
            if post_element.select_one(".quote"):
                tweet_type = "quote"
            elif post_element.find_parent(class_="replies"):
                if not post_element.select_one(".retweet-header"):
                    tweet_type = "reply"

            # Has media
            has_media = bool(post_element.select_one(".attachment, .gallery, .video-container"))

            # Text content
            text_elem = post_element.select_one(".tweet-content")
            text = text_elem.get_text().strip() if text_elem else ""
            text = re.sub(r"\s+", " ", text)

            # HTML structure
            html_structure = str(post_element)

            # Collect links
            links = []
            for link in post_element.select("a[href]"):
                href = link.get("href", "")
                if href:
                    full_url = href if href.startswith("http") else f"{instance}{href}"
                    links.append({
                        "url": full_url,
                        "text": link.get_text().strip(),
                        "title": link.get("title", ""),
                    })

            # Collect images
            images = []
            media_urls = []
            for img in post_element.select("img"):
                src = img.get("src") or img.get("data-src")
                if src:
                    full_url = src if src.startswith("http") else f"{instance}{src}"
                    images.append({
                        "url": full_url,
                        "alt": img.get("alt", ""),
                        "title": img.get("title", ""),
                    })
                    media_urls.append(full_url)

            # Collect videos
            videos = []
            for video in post_element.select("video, [data-video], .video-container video"):
                src = video.get("src") or video.get("data-src")
                poster = video.get("poster", "")
                video_url = src if src and src.startswith("http") else (f"{instance}{src}" if src else "")
                poster_url = poster if poster.startswith("http") else (f"{instance}{poster}" if poster else "")

                if video_url or poster_url:
                    videos.append({
                        "url": video_url,
                        "poster": poster_url,
                    })
                    if video_url:
                        media_urls.append(video_url)
                    if poster_url:
                        media_urls.append(poster_url)

            # Collect hashtags
            hashtags = []
            for hashtag_link in post_element.select('a[href*="/hashtag/"]'):
                tag_text = hashtag_link.get_text().strip()
                if tag_text.startswith("#"):
                    hashtags.append(tag_text)

            # Collect mentions
            mentions = []
            for mention in post_element.select("a[href]"):
                text_content = mention.get_text().strip()
                href = mention.get("href", "")
                if text_content.startswith("@") and "/hashtag/" not in href:
                    mentions.append(text_content)

            # Extract Polymarket topics
            polymarket_topics = self._extract_polymarket_topics(text, links)

            # Calculate engagement score
            engagement_score = count_like + count_retweet + count_reply + count_quote

            return NitterPost(
                post_id=post_id,
                name=name,
                username=username,
                profile_id=profile_id,
                created_at=created_at,
                lang=lang,
                count_bookmark=0,
                count_impression=0,
                count_like=count_like,
                count_reply=count_reply,
                count_retweet=count_retweet,
                count_quote=count_quote,
                tweet_type=tweet_type,
                has_media=has_media,
                text=text,
                html_structure=html_structure,
                links=json.dumps(links),
                images=json.dumps(images),
                videos=json.dumps(videos),
                hashtags=", ".join(hashtags),
                mentions=", ".join(mentions),
                media_urls=" | ".join(media_urls),
                polymarket_topics=", ".join(polymarket_topics),
                engagement_score=engagement_score,
                scraped_at=datetime.utcnow().isoformat(),
            )

        except Exception as e:
            logger.error(f"Error parsing post: {e}")
            return None

    def _load_page(
        self,
        url: str,
        retry_count: int = 0
    ) -> Tuple[Optional[BeautifulSoup], bool]:
        """
        Load and parse a page.
        Returns (soup, should_switch_instance).
        Replicates JS loadPage function with retry logic.
        """
        try:
            response = self.session.get(url, timeout=config.REQUEST_TIMEOUT)

            # Handle 429 (Too Many Requests)
            if response.status_code == 429:
                logger.warning(
                    f"Rate limit (429). Pausing for {config.RATE_LIMIT_PAUSE}s..."
                )
                time.sleep(config.RATE_LIMIT_PAUSE)
                return self._load_page(url, retry_count=0)

            # Handle other errors
            if response.status_code >= 400:
                if retry_count < config.MAX_RETRIES:
                    delay = config.DELAY_BETWEEN_REQUESTS * (retry_count + 1)
                    logger.warning(
                        f"HTTP {response.status_code}. Retry {retry_count + 1}/{config.MAX_RETRIES} "
                        f"in {delay}s..."
                    )
                    time.sleep(delay)
                    return self._load_page(url, retry_count + 1)
                else:
                    logger.error(f"HTTP {response.status_code} after {config.MAX_RETRIES} retries")
                    return None, True  # Switch instance

            soup = BeautifulSoup(response.text, "html.parser")
            return soup, False

        except requests.exceptions.Timeout:
            logger.error(f"Timeout loading {url}")
            if retry_count < config.MAX_RETRIES:
                time.sleep(config.DELAY_BETWEEN_REQUESTS * (retry_count + 1))
                return self._load_page(url, retry_count + 1)
            return None, True

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            if retry_count < config.MAX_RETRIES:
                time.sleep(config.DELAY_BETWEEN_REQUESTS * (retry_count + 1))
                return self._load_page(url, retry_count + 1)
            return None, True

    def fetch_search_posts(
        self,
        search_params: Optional[Dict[str, str]] = None,
        max_pages: int = 10,
        since_post_id: Optional[str] = None,
        callback: Optional[callable] = None
    ) -> List[NitterPost]:
        """
        Fetch all posts from search results.

        Args:
            search_params: Search parameters (uses config defaults if None)
            max_pages: Maximum pages to fetch (0 for unlimited)
            since_post_id: Stop when reaching this post ID (for incremental updates)
            callback: Optional callback(posts, cursor, page) called after each page

        Returns:
            List of NitterPost objects
        """
        if search_params is None:
            search_params = config.SEARCH_PARAMS.copy()

        all_posts: List[NitterPost] = []
        cursor = ""
        page = 0
        seen_post_ids = set()
        reached_existing = False
        instances_tried = 0

        logger.info(f"Starting search for: {search_params.get('q', 'polymarket')}")

        while (max_pages == 0 or page < max_pages) and instances_tried < len(self.instances):
            instance = self._get_current_instance()
            url = self.build_search_url(search_params, cursor, instance)

            logger.info(f"Loading page {page + 1}: {url}")

            soup, should_switch = self._load_page(url)

            if soup is None:
                if should_switch:
                    self._switch_instance()
                    instances_tried += 1
                    continue
                break

            instances_tried = 0  # Reset on success

            # Find post elements
            items = soup.select(".timeline-item, .tweet-item")
            if not items:
                items = soup.select(".tweet")

            if not items:
                # Check for no results message
                no_results = soup.select_one(".timeline-no-results, .no-results, .empty-timeline")
                if no_results:
                    logger.info("Search returned no results")
                else:
                    logger.warning("No posts found on page")
                break

            new_posts_count = 0
            for item in items:
                post = self._parse_post(item, instance)
                if post and post.post_id:
                    # Check for duplicates
                    if post.post_id in seen_post_ids:
                        continue

                    # Check if we've reached existing posts
                    if since_post_id and post.post_id == since_post_id:
                        logger.info(f"Reached existing post {since_post_id}")
                        reached_existing = True
                        break

                    seen_post_ids.add(post.post_id)
                    all_posts.append(post)
                    new_posts_count += 1

            logger.info(f"Found {new_posts_count} new posts (total: {len(all_posts)})")

            if reached_existing:
                break

            # Call callback if provided
            if callback:
                callback(all_posts, cursor, page)

            # Get next cursor
            next_cursor = self._extract_cursor(soup)
            if not next_cursor:
                logger.info("No more pages (no cursor found)")
                break

            if next_cursor == cursor:
                logger.warning("Cursor unchanged, stopping to prevent infinite loop")
                break

            cursor = next_cursor
            page += 1

            # Delay before next request
            if max_pages == 0 or page < max_pages:
                time.sleep(config.DELAY_BETWEEN_REQUESTS)

        logger.info(f"Search completed. Total posts: {len(all_posts)}")
        return all_posts

    def fetch_new_posts(
        self,
        last_post_id: Optional[str] = None,
        search_params: Optional[Dict[str, str]] = None
    ) -> List[NitterPost]:
        """
        Fetch only new posts since the last known post ID.
        Optimized for incremental updates.
        """
        return self.fetch_search_posts(
            search_params=search_params,
            max_pages=5,  # Limit pages for incremental updates
            since_post_id=last_post_id
        )


def export_to_csv(posts: List[NitterPost], filepath: str) -> None:
    """
    Export posts to CSV file (same format as JS scraper).
    """
    import csv

    headers = [
        "PostId", "Name", "Username", "ProfileId", "CreatedAt", "Lang",
        "CountBookmark", "CountImpression", "CountLike", "CountReply",
        "CountRetweet", "CountQuote", "TweetType", "HasMedia", "Text",
        "HtmlStructure", "Links", "Images", "Videos", "Hashtags",
        "Mentions", "MediaUrls", "PolymarketTopics", "EngagementScore", "ScrapedAt"
    ]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for post in posts:
            writer.writerow([
                post.post_id,
                post.name,
                post.username,
                post.profile_id,
                post.created_at,
                post.lang,
                post.count_bookmark,
                post.count_impression,
                post.count_like,
                post.count_reply,
                post.count_retweet,
                post.count_quote,
                post.tweet_type,
                post.has_media,
                post.text,
                post.html_structure,
                post.links,
                post.images,
                post.videos,
                post.hashtags,
                post.mentions,
                post.media_urls,
                post.polymarket_topics,
                post.engagement_score,
                post.scraped_at,
            ])


def export_to_json(posts: List[NitterPost], filepath: str) -> None:
    """
    Export posts to JSON file.
    """
    data = [post.to_dict() for post in posts]
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# Test function
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = NitterParser()
    posts = parser.fetch_search_posts(max_pages=1)
    for post in posts[:3]:
        print(f"@{post.username}: {post.text[:100]}... ({post.engagement_score} engagement)")
