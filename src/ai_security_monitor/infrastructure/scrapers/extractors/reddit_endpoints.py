"""
Extractor for unwinding Reddit REST API endpoints and discussion comment trees.
"""

from __future__ import annotations

import html
from typing import Any

from ai_security_monitor.infrastructure.scrapers.models.reddit_post import (
    RedditComment,
    RedditPost,
)


class RedditEndpointsExtractor:
    """Extracts posts and comment trees from Reddit JSON endpoints."""

    @classmethod
    def extract_posts_from_listing(cls, payload: dict[str, Any]) -> list[RedditPost]:
        """Extract RedditPost models from a /r/{sub}/hot.json or search listing payload."""
        posts: list[RedditPost] = []
        children = payload.get("data", {}).get("children", [])
        if not isinstance(children, list):
            return posts

        for child in children:
            if not isinstance(child, dict):
                continue
            data = child.get("data", {})
            if not data or data.get("stickied"):
                continue

            post_id = str(data.get("id", ""))
            title = html.unescape(data.get("title", "")).strip()
            if not post_id or not title:
                continue

            selftext = html.unescape(data.get("selftext", "")).strip()

            post = RedditPost(
                id=post_id,
                title=title,
                subreddit=data.get("subreddit", "unknown"),
                author=data.get("author", "redditor"),
                score=int(data.get("score", 0)),
                num_comments=int(data.get("num_comments", 0)),
                url=data.get("url", ""),
                permalink=data.get("permalink", ""),
                selftext=selftext,
                created_utc=float(data.get("created_utc", 0.0)),
                stickied=bool(data.get("stickied", False)),
                is_self=bool(data.get("is_self", True)),
                raw_data=data,
            )
            posts.append(post)

        return posts

    @classmethod
    def extract_comments_from_thread(
        cls, payload: list[Any] | dict[str, Any], max_comments: int = 5
    ) -> list[RedditComment]:
        """Extract top RedditComment models from a /comments/{id}.json payload."""
        comments: list[RedditComment] = []
        if not isinstance(payload, list) or len(payload) < 2:
            return comments

        comments_listing = payload[1]
        if not isinstance(comments_listing, dict):
            return comments

        children = comments_listing.get("data", {}).get("children", [])
        for child in children:
            if not isinstance(child, dict):
                continue
            cdata = child.get("data", {})
            author = cdata.get("author", "[deleted]")
            body = html.unescape(cdata.get("body", "")).strip()
            comment_id = str(cdata.get("id") or f"c_{len(comments)}")

            if body and body != "[deleted]" and len(body) > 10:
                clean_body = body[:350] + "..." if len(body) > 350 else body
                comments.append(
                    RedditComment(
                        id=comment_id,
                        author=author,
                        body=clean_body,
                        score=int(cdata.get("score", 0)),
                        created_utc=float(cdata.get("created_utc", 0.0))
                        if cdata.get("created_utc")
                        else None,
                    )
                )

            if len(comments) >= max_comments:
                break

        return comments
