"""
Chinese-Language Launch Coverage and Bridge Feed Fetcher (Feature 7).
Enables WeChat, Weibo, and Chinese tech media launch ingestion with:
- Dual-bridge automated failover (404, HTML captcha/block page, empty feed recovery)
- Chinese-first ingestion triage guard (pre-filters out off-topic articles before translation)
- Untranslated original Chinese content preservation in metadata for epistemic grounding
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import feedparser
import httpx
from dateutil import parser as dt_parser

from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.core.sanitizer import AIPromptSanitizer
from ai_security_monitor.domain.entities import Category, Entry
from ai_security_monitor.domain.exceptions import FetchError
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.fetchers.base import (
    BaseFetcher,
    fetcher_registry,
)

logger = get_logger(__name__)

# Chinese Frontier Labs & Models
CHINESE_AI_ENTITIES = (
    "深度求索",
    "deepseek",
    "通义千问",
    "qwen",
    "阿里云",
    "阿里",
    "智谱",
    "zhipu",
    "glm",
    "月之暗面",
    "moonshot",
    "kimi",
    "百川智能",
    "baichuan",
    "minimax",
    "名之梦",
    "阶跃星辰",
    "stepfun",
    "字节跳动",
    "bytedance",
    "豆包",
    "doubao",
    "腾讯混元",
    "hunyuan",
    "百度文心",
    "ernie",
    "商汤",
    "sensetime",
    "日日新",
    "零一万物",
    "01.ai",
    "yi-",
    "上海人工智能实验室",
    "shanghai ai lab",
    "书生",
    "internlm",
    "中科院",
    "清华",
    "thudm",
    "面壁智能",
    "minicpm",
)

# Chinese AI Launch Keywords & Verbs
CHINESE_LAUNCH_KEYWORDS = (
    "开源",
    "发布",
    "上线",
    "推出",
    "大模型",
    "基础模型",
    "参数",
    "基准",
    "推理",
    "微调",
    "多模态",
    "agent",
    "智能体",
    "生成式ai",
    "生成式人工智能",
    "算力",
    "token",
    "权重",
    "测评",
    "评测",
    "sota",
    "架构",
    "蒸馏",
    "强化学习",
    "长上下文",
    "代码大模型",
    "数学推理",
)


def is_chinese_ai_launch(title: str, text: str) -> bool:
    """Triage Chinese text to ensure it covers genuine AI models, tools, or research."""
    combined = f"{title} {text}".lower()

    # Check for known frontier lab or model entity
    has_entity = any(entity.lower() in combined for entity in CHINESE_AI_ENTITIES)

    # Check for technical launch action or model vocabulary
    has_launch_term = any(kw.lower() in combined for kw in CHINESE_LAUNCH_KEYWORDS)

    # Valid if it mentions a lab + action/model, or multiple launch keywords
    if has_entity and has_launch_term:
        return True

    # If general AI news with multiple technical keywords
    matched_kws = sum(1 for kw in CHINESE_LAUNCH_KEYWORDS if kw.lower() in combined)
    return matched_kws >= 2


class BridgeFeedFetcher(BaseFetcher):
    """Fault-tolerant RSS/Atom Bridge Fetcher with automated multi-bridge failover."""

    @property
    def fetcher_type(self) -> str:
        return "bridge_feed"

    def get_candidate_bridges(self) -> list[str]:
        """Collect ordered list of candidate bridge endpoints (primary + fallbacks)."""
        bridges: list[str] = []
        if self.source.url:
            bridges.append(self.source.url)

        cfg = self.source.config or {}
        # Support fallback_url
        if cfg.get("fallback_url") and cfg["fallback_url"] not in bridges:
            bridges.append(cfg["fallback_url"])

        # Support list of bridges or mirrors
        for alt_key in ("bridges", "mirrors", "bridge_urls"):
            alts = cfg.get(alt_key)
            if isinstance(alts, list):
                for b in alts:
                    if isinstance(b, str) and b and b not in bridges:
                        bridges.append(b)

        return bridges

    async def _fetch_raw(self) -> list[dict[str, Any]]:
        """Fetch and parse feed from bridges with automatic failover."""
        bridges = self.get_candidate_bridges()
        if not bridges:
            raise FetchError(
                f"No bridge URLs configured for source: {self.source.name}"
            )

        stealth_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
            ),
            "Accept": "application/atom+xml,application/rdf+xml,application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        last_error: Exception | None = None
        raw_items: list[dict[str, Any]] = []

        async with httpx.AsyncClient(
            timeout=float(self.timeout), follow_redirects=True
        ) as client:
            for idx, bridge_url in enumerate(bridges):
                is_failover = idx > 0
                if is_failover:
                    logger.warning(
                        f"Failing over to secondary bridge [{idx + 1}/{len(bridges)}] "
                        f"for {self.source.name}: {bridge_url}"
                    )

                try:
                    resp = await client.get(bridge_url, headers=stealth_headers)

                    # 1. Non-2xx check
                    if resp.status_code != 200:
                        logger.warning(
                            f"Bridge HTTP {resp.status_code} on {bridge_url} (source: {self.source.name})"
                        )
                        last_error = FetchError(
                            f"Bridge HTTP {resp.status_code}: {bridge_url}"
                        )
                        continue

                    # 2. HTML Block / Captcha / WeChat Verification check
                    content_type = resp.headers.get("content-type", "").lower()
                    body_start = resp.text[:1000].lower().strip()

                    is_html_block = (
                        "text/html" in content_type
                        and not any(
                            tag in body_start for tag in ("<rss", "<feed", "<rdf")
                        )
                    ) or any(
                        block_sig in body_start
                        for block_sig in (
                            "验证码",
                            "security verification",
                            "weixin.qq.com/verify",
                            "blocked",
                            "cloudflare",
                            "captcha",
                            "<title>403</title>",
                            "<title>404</title>",
                        )
                    )

                    if is_html_block:
                        logger.warning(
                            f"Bridge returned HTML block/captcha page on {bridge_url} (source: {self.source.name})"
                        )
                        last_error = FetchError(
                            f"Bridge returned HTML block page: {bridge_url}"
                        )
                        continue

                    # 3. Parse XML / Feed
                    parsed = feedparser.parse(resp.content)
                    if not parsed.entries:
                        logger.warning(
                            f"Bridge returned 0 entries on {bridge_url} (source: {self.source.name})"
                        )
                        last_error = FetchError(
                            f"Bridge returned empty feed (0 entries): {bridge_url}"
                        )
                        continue

                    # Success! Extract items and record which bridge succeeded
                    for entry_item in parsed.entries:
                        item_dict = dict(entry_item)
                        item_dict["_bridge_url"] = bridge_url
                        item_dict["_failover_occurred"] = is_failover
                        raw_items.append(item_dict)

                    logger.info(
                        f"Successfully ingested {len(raw_items)} raw items from bridge: {bridge_url} "
                        f"(failover: {is_failover})"
                    )
                    break

                except Exception as exc:
                    logger.warning(
                        f"Error connecting to bridge {bridge_url} for {self.source.name}: {exc}"
                    )
                    last_error = exc
                    continue

        if not raw_items:
            raise FetchError(
                f"All {len(bridges)} candidate bridges failed for {self.source.name}. "
                f"Last error: {last_error}"
            )

        return raw_items

    def _parse_entry(self, raw: dict[str, Any]) -> Entry:
        """Parse raw feed item with Chinese-first triage and original text preservation."""
        title = AIPromptSanitizer.sanitize_text(raw.get("title", "")).strip()
        link = raw.get("link", "").strip()

        # Extract content / summary
        summary = ""
        if "summary" in raw:
            summary = raw["summary"]
        elif "content" in raw and isinstance(raw["content"], list) and raw["content"]:
            summary = raw["content"][0].get("value", "")
        elif "description" in raw:
            summary = raw["description"]

        # Clean HTML tags from summary for text extraction
        clean_summary = re.sub(r"<[^>]+>", " ", summary).strip()
        clean_summary = AIPromptSanitizer.sanitize_text(clean_summary)

        # Chinese-first Ingestion Triage Guard:
        # Check if item covers AI launches before queuing for translation/analysis
        passes_triage = is_chinese_ai_launch(title, clean_summary)

        # Parse publication date
        pub_date = datetime.now(UTC)
        for date_key in ("published", "pubDate", "created", "updated"):
            date_str = raw.get(date_key)
            if date_str:
                try:
                    parsed_dt = dt_parser.parse(date_str)
                    pub_date = (
                        parsed_dt if parsed_dt.tzinfo else parsed_dt.replace(tzinfo=UTC)
                    )
                    break
                except Exception:
                    pass

        # Compute content hash
        content_hash = ContentHash.from_content(
            title,
            link,
            clean_summary,
            str(pub_date),
        ).value

        bridge_url = raw.get("_bridge_url", self.source.url)
        failover_occurred = raw.get("_failover_occurred", False)

        metadata: dict[str, Any] = {
            "bridge_url": bridge_url,
            "failover_occurred": failover_occurred,
            "channel": self.source.config.get("channel", "wechat")
            if self.source.config
            else "wechat",
            "original_chinese": f"{title}\n\n{clean_summary}".strip(),
            "raw_original_content": f"{title}\n\n{clean_summary}".strip(),
            "original_title": title,
            "source_type": "bridge_feed",
            "passed_chinese_triage": passes_triage,
            "subject_region": "china",
            "region": "china",
        }

        # If it failed triage, mark it so ingestion pipeline can safely filter it
        if not passes_triage:
            metadata["is_filtered_out"] = True
            metadata["filter_reason"] = "off_topic_chinese_news"

        return Entry(
            id=uuid4(),
            source_id=self.source.id,
            title=title,
            url=link or f"{bridge_url}#{content_hash[:16]}",
            content_hash=content_hash,
            summary=clean_summary,
            category=Category.AI_MODELS,
            published_at=pub_date,
            fetched_at=datetime.now(UTC),
            metadata=metadata,
        )


# Register fetcher in global registry
fetcher_registry.register("bridge_feed", BridgeFeedFetcher)
