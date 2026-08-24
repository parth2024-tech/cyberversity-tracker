"""
Feed fetchers for various source types.
Each fetcher handles a specific type of source (RSS, arXiv, Hacker News, NVD, GitHub, etc.)
"""

import feedparser
import requests
import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from urllib.parse import urljoin, urlparse
import time
import logging

logger = logging.getLogger(__name__)


class BaseFetcher:
    """Base class for all fetchers."""

    def __init__(self, rate_limit_seconds: int = 3600, **kwargs):
        self.rate_limit_seconds = rate_limit_seconds
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'AI-Security-Monitor/1.0 (+https://github.com/your-repo; contact: your-email)'
        })

    def _make_content_hash(self, *parts: str) -> str:
        """Create a unique hash for deduplication."""
        content = '|'.join(str(p) for p in parts if p)
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def _clean_html(self, text: str) -> str:
        """Basic HTML cleaning."""
        if not text:
            return ""
        # Remove scripts and styles
        text = re.sub(r'<script.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        # Decode common entities
        text = text.replace('&nbsp;', ' ').replace('&', '&').replace('<', '<').replace('>', '>')
        text = text.replace('"', '"').replace('\u2018', "'").replace('\u2019', "'")
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _truncate(self, text: str, max_len: int = 300) -> str:
        """Truncate text to max length."""
        if not text:
            return ""
        if len(text) <= max_len:
            return text
        return text[:max_len].rsplit(' ', 1)[0] + "..."


class RSSFetcher(BaseFetcher):
    """Fetch entries from RSS/Atom feeds."""

    def fetch(self, url: str, source_name: str, category: str,
              max_entries: int = 50) -> List[Dict]:
        """Fetch and parse RSS feed."""
        entries = []
        try:
            # Polite request with timeout
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            # Parse with feedparser
            feed = feedparser.parse(response.content)

            if feed.bozo and feed.bozo_exception:
                logger.warning(f"Feed parse warning for {source_name}: {feed.bozo_exception}")

            for item in feed.entries[:max_entries]:
                # Extract fields with fallbacks
                title = item.get('title', '').strip()
                link = item.get('link', '').strip()

                # Try multiple fields for content
                summary = (
                    item.get('summary', '') or
                    item.get('description', '') or
                    item.get('content', [{}])[0].get('value', '') if item.get('content') else ''
                )
                summary = self._clean_html(summary)

                # Published date
                published_at = None
                for date_field in ['published_parsed', 'updated_parsed', 'created_parsed']:
                    if item.get(date_field):
                        try:
                            published_at = datetime(*item[date_field][:6])
                            break
                        except (TypeError, ValueError):
                            pass

                # Generate content hash for deduplication
                content_hash = self._make_content_hash(title, link, summary)

                # Tags/categories
                tags = []
                if item.get('tags'):
                    tags = [t.get('term', '') for t in item.get('tags', []) if t.get('term')]

                entries.append({
                    'title': title,
                    'url': link,
                    'summary': self._truncate(summary),
                    'published_at': published_at,
                    'content_hash': content_hash,
                    'tags': tags,
                    'metadata': {
                        'feed_title': feed.feed.get('title', ''),
                        'feed_link': feed.feed.get('link', ''),
                    }
                })

            logger.info(f"Fetched {len(entries)} entries from {source_name}")

        except requests.RequestException as e:
            logger.error(f"Network error fetching {source_name}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error parsing {source_name}: {e}")
            raise

        return entries


class ArxivFetcher(BaseFetcher):
    """Fetch papers from arXiv API."""

    BASE_URL = "http://export.arxiv.org/api/query"

    def __init__(self, rate_limit_seconds: int = 1800, query: str = "", max_results: int = 50):
        super().__init__(rate_limit_seconds)
        self.default_query = query
        self.default_max_results = max_results

    def fetch(self, query: str = "", max_results: int = 50,
              source_name: str = "arXiv", category: str = "ai_research") -> List[Dict]:
        """Fetch papers from arXiv."""
        # Use defaults if not provided
        query = query or self.default_query
        max_results = max_results or self.default_max_results
        entries = []
        try:
            params = {
                'search_query': query,
                'start': 0,
                'max_results': max_results,
                'sortBy': 'submittedDate',
                'sortOrder': 'descending'
            }

            response = self.session.get(self.BASE_URL, params=params, timeout=30)
            response.raise_for_status()

            feed = feedparser.parse(response.content)

            for item in feed.entries:
                title = item.get('title', '').strip().replace('\n', ' ')
                link = item.get('link', '').strip()

                # Get PDF link
                pdf_link = None
                for link_obj in item.get('links', []):
                    if link_obj.get('title') == 'pdf':
                        pdf_link = link_obj.get('href')
                        break

                summary = item.get('summary', '').strip().replace('\n', ' ')
                summary = self._clean_html(summary)

                # Authors
                authors = []
                for author in item.get('authors', []):
                    authors.append(author.get('name', ''))

                # Categories
                tags = []
                for tag in item.get('tags', []):
                    tags.append(tag.get('term', ''))

                # Published date
                published_at = None
                if item.get('published_parsed'):
                    try:
                        published_at = datetime(*item.published_parsed[:6])
                    except (TypeError, ValueError):
                        pass

                # Use arXiv ID as part of hash for better deduplication
                arxiv_id = link.split('/')[-1] if link else ''
                content_hash = self._make_content_hash(arxiv_id, title)

                entries.append({
                    'title': title,
                    'url': link,
                    'summary': self._truncate(summary),
                    'published_at': published_at,
                    'content_hash': content_hash,
                    'tags': tags,
                    'metadata': {
                        'arxiv_id': arxiv_id,
                        'pdf_url': pdf_link,
                        'authors': authors,
                        'categories': tags,
                    }
                })

            logger.info(f"Fetched {len(entries)} papers from {source_name}")

        except Exception as e:
            logger.error(f"Error fetching from arXiv: {e}")
            raise

        return entries


class HackerNewsFetcher(BaseFetcher):
    """Fetch stories from Hacker News via Firebase API."""

    BASE_URL = "https://hacker-news.firebaseio.com/v0"

    def __init__(self, rate_limit_seconds: int = 600, tags: List[str] = None):
        super().__init__(rate_limit_seconds)
        self.tags = [t.lower() for t in (tags or [])]

    def _get_item(self, item_id: int) -> Optional[Dict]:
        """Fetch a single item by ID."""
        try:
            response = self.session.get(f"{self.BASE_URL}/item/{item_id}.json", timeout=10)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.warning(f"Error fetching HN item {item_id}: {e}")
        return None

    def _matches_tags(self, title: str, text: str = "") -> bool:
        """Check if story matches any of our tags."""
        if not self.tags:
            return True
        combined = f"{title} {text}".lower()
        return any(tag in combined for tag in self.tags)

    def fetch(self, source_name: str = "Hacker News", category: str = "ai_tech",
              max_stories: int = 30) -> List[Dict]:
        """Fetch top/new stories from Hacker News."""
        entries = []
        try:
            # Get top story IDs
            response = self.session.get(f"{self.BASE_URL}/topstories.json", timeout=15)
            response.raise_for_status()
            story_ids = response.json()[:max_stories * 2]  # Get extra to filter

            for story_id in story_ids:
                if len(entries) >= max_stories:
                    break

                item = self._get_item(story_id)
                if not item or item.get('type') != 'story':
                    continue

                title = item.get('title', '').strip()
                url = item.get('url', f"https://news.ycombinator.com/item?id={story_id}")
                text = item.get('text', '')

                # Filter by tags
                if not self._matches_tags(title, text):
                    continue

                # Build summary from text or use title
                summary = self._clean_html(text) if text else title
                summary = self._truncate(summary)

                # Published time
                published_at = None
                if item.get('time'):
                    try:
                        published_at = datetime.fromtimestamp(item['time'])
                    except (TypeError, ValueError, OSError):
                        pass

                content_hash = self._make_content_hash(str(story_id), title)

                entries.append({
                    'title': title,
                    'url': url,
                    'summary': summary,
                    'published_at': published_at,
                    'content_hash': content_hash,
                    'tags': ['hackernews'] + self.tags,
                    'metadata': {
                        'hn_id': story_id,
                        'score': item.get('score', 0),
                        'by': item.get('by', ''),
                        'descendants': item.get('descendants', 0),
                    }
                })

                # Polite delay between item fetches
                time.sleep(0.1)

            logger.info(f"Fetched {len(entries)} stories from {source_name}")

        except Exception as e:
            logger.error(f"Error fetching from Hacker News: {e}")
            raise

        return entries


class NVDFetcher(BaseFetcher):
    """Fetch CVE data from NVD feeds."""

    def fetch(self, url: str, source_name: str = "NVD", category: str = "vulnerabilities") -> List[Dict]:
        """Fetch and parse NVD CVE feed (XML)."""
        entries = []
        try:
            response = self.session.get(url, timeout=60)
            response.raise_for_status()

            # Parse XML with feedparser (handles namespaces)
            feed = feedparser.parse(response.content)

            for item in feed.entries:
                title = item.get('title', '').strip()
                link = item.get('link', '').strip()

                # NVD entries have summary in description
                summary = item.get('summary', '') or item.get('description', '')
                summary = self._clean_html(summary)

                # Published date
                published_at = None
                if item.get('published_parsed'):
                    try:
                        published_at = datetime(*item.published_parsed[:6])
                    except (TypeError, ValueError):
                        pass

                # Extract CVE ID from title or link
                cve_match = re.search(r'(CVE-\d{4}-\d{4,})', title + ' ' + link)
                cve_id = cve_match.group(1) if cve_match else ''

                content_hash = self._make_content_hash(cve_id, title)

                # Tags from categories
                tags = []
                if item.get('tags'):
                    tags = [t.get('term', '') for t in item.get('tags', []) if t.get('term')]

                entries.append({
                    'title': title,
                    'url': link,
                    'summary': self._truncate(summary),
                    'published_at': published_at,
                    'content_hash': content_hash,
                    'tags': tags,
                    'metadata': {
                        'cve_id': cve_id,
                        'source': 'nvd',
                    }
                })

            logger.info(f"Fetched {len(entries)} CVEs from {source_name}")

        except Exception as e:
            logger.error(f"Error fetching from NVD: {e}")
            raise

        return entries


class NVDAPIFetcher(BaseFetcher):
    """Fetch CVE data from NVD API v2.0."""

    BASE_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"

    def __init__(self, rate_limit_seconds: int = 3600, **kwargs):
        super().__init__(rate_limit_seconds)

    def fetch(self, source_name: str = "NVD API", category: str = "vulnerabilities",
              results_per_page: int = 50) -> List[Dict]:
        """Fetch recent CVEs from NVD API."""
        entries = []
        try:
            # Get CVEs modified in last 7 days (NVD API requires both lastModStartDate and lastModEndDate)
            import datetime as dt
            now = dt.datetime.now(dt.timezone.utc)
            mod_start = (now - dt.timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
            mod_end = now.strftime('%Y-%m-%dT%H:%M:%S.000Z')

            params = {
                'lastModStartDate': mod_start,
                'lastModEndDate': mod_end,
                'resultsPerPage': results_per_page,
                'startIndex': 0
            }

            response = self.session.get(self.BASE_URL, params=params, timeout=60)
            response.raise_for_status()

            data = response.json()

            for vuln in data.get('vulnerabilities', []):
                cve = vuln.get('cve', {})
                cve_id = cve.get('id', '')
                title = f"{cve_id}: {cve.get('descriptions', [{}])[0].get('value', '')[:100]}"

                # Get URL
                url = f"https://nvd.nist.gov/vuln/detail/{cve_id}"

                # Get description
                descriptions = cve.get('descriptions', [])
                summary = ''
                for desc in descriptions:
                    if desc.get('lang') == 'en':
                        summary = desc.get('value', '')
                        break
                summary = self._clean_html(summary)

                # Published date
                published_at = None
                if cve.get('published'):
                    try:
                        published_at = datetime.fromisoformat(cve['published'].replace('Z', '+00:00'))
                    except (ValueError, AttributeError):
                        pass

                # Get CVSS scores
                metrics = cve.get('metrics', {})
                cvss_score = None
                for metric_type in ['cvssMetricV31', 'cvssMetricV30', 'cvssMetricV2']:
                    if metric_type in metrics and metrics[metric_type]:
                        cvss_score = metrics[metric_type][0].get('cvssData', {}).get('baseScore')
                        break

                content_hash = self._make_content_hash(cve_id)

                # Tags from weaknesses
                tags = []
                for weakness in cve.get('weaknesses', []):
                    for desc in weakness.get('description', []):
                        if desc.get('lang') == 'en':
                            tags.append(desc.get('value', ''))

                entries.append({
                    'title': title,
                    'url': url,
                    'summary': self._truncate(summary),
                    'published_at': published_at,
                    'content_hash': content_hash,
                    'tags': tags[:5],
                    'metadata': {
                        'cve_id': cve_id,
                        'cvss_score': cvss_score,
                        'source': 'nvd_api',
                    }
                })

            logger.info(f"Fetched {len(entries)} CVEs from {source_name}")

        except Exception as e:
            logger.error(f"Error fetching from NVD API: {e}")
            raise

        return entries


class GitHubTrendingFetcher(BaseFetcher):
    """Fetch trending repositories from GitHub (via web scraping since no official API)."""

    BASE_URL = "https://github.com/trending"

    def __init__(self, rate_limit_seconds: int = 3600, language: str = "", since: str = "daily", **kwargs):
        super().__init__(rate_limit_seconds, **kwargs)
        self.default_language = language
        self.default_since = since

    def fetch(self, language: str = "", since: str = "daily",
              source_name: str = "GitHub Trending", category: str = "github_trending") -> List[Dict]:
        """Fetch trending repos."""
        # Use defaults if not provided
        language = language or self.default_language
        since = since or self.default_since
        entries = []
        try:
            params = {}
            if language:
                params['l'] = language
            params['since'] = since

            url = self.BASE_URL
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()

            # Parse HTML - GitHub trending page structure
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')

            # Find repo articles
            repos = soup.find_all('article', class_='Box-row')

            for repo in repos[:30]:
                try:
                    # Repo name and link
                    h2 = repo.find('h2', class_='h3')
                    if not h2:
                        continue
                    a_tag = h2.find('a')
                    if not a_tag:
                        continue

                    repo_name = a_tag.get_text(strip=True).replace(' ', '')
                    repo_url = urljoin('https://github.com', a_tag['href'])

                    # Description
                    desc_tag = repo.find('p', class_='col-9')
                    description = desc_tag.get_text(strip=True) if desc_tag else ''

                    # Language
                    lang_tag = repo.find('span', itemprop='programmingLanguage')
                    language = lang_tag.get_text(strip=True) if lang_tag else ''

                    # Stars today/this period
                    stars_tag = repo.find('span', class_='d-inline-block float-sm-right')
                    stars_text = stars_tag.get_text(strip=True) if stars_tag else ''

                    # Build summary
                    summary_parts = []
                    if description:
                        summary_parts.append(description)
                    if language:
                        summary_parts.append(f"Language: {language}")
                    if stars_text:
                        summary_parts.append(f"Stars: {stars_text}")
                    summary = self._truncate(' | '.join(summary_parts))

                    content_hash = self._make_content_hash(repo_name, repo_url)

                    entries.append({
                        'title': repo_name,
                        'url': repo_url,
                        'summary': summary,
                        'published_at': datetime.now(),  # Trending is current
                        'content_hash': content_hash,
                        'tags': [language.lower()] if language else [],
                        'metadata': {
                            'language': language,
                            'stars_period': stars_text,
                            'period': since,
                        }
                    })
                except Exception as e:
                    logger.warning(f"Error parsing repo: {e}")
                    continue

            logger.info(f"Fetched {len(entries)} trending repos from {source_name}")

        except Exception as e:
            logger.error(f"Error fetching GitHub trending: {e}")
            raise

        return entries


class GitHubAdvisoriesFetcher(BaseFetcher):
    """Fetch GitHub Security Advisories via API."""

    BASE_URL = "https://api.github.com/advisories"

    def fetch(self, source_name: str = "GitHub Advisories", category: str = "vulnerabilities",
              per_page: int = 50) -> List[Dict]:
        """Fetch recent security advisories."""
        entries = []
        try:
            params = {
                'per_page': per_page,
                'sort': 'published',
                'direction': 'desc'
            }

            response = self.session.get(self.BASE_URL, params=params, timeout=30)
            response.raise_for_status()

            advisories = response.json()

            for adv in advisories:
                title = adv.get('summary', '').strip()
                url = adv.get('html_url', '').strip()

                # Description
                description = adv.get('description', '')
                summary = self._clean_html(description)
                summary = self._truncate(summary)

                # Published date
                published_at = None
                if adv.get('published_at'):
                    try:
                        published_at = datetime.fromisoformat(adv['published_at'].replace('Z', '+00:00'))
                    except (ValueError, AttributeError):
                        pass

                # GHSA ID
                ghsa_id = adv.get('ghsa_id', '')

                # Severity
                severity = adv.get('severity', '')

                content_hash = self._make_content_hash(ghsa_id, title)

                # Tags from vulnerabilities
                tags = []
                for vuln in adv.get('vulnerabilities', []):
                    pkg = vuln.get('package', {})
                    if pkg.get('name'):
                        tags.append(pkg['name'])

                entries.append({
                    'title': title,
                    'url': url,
                    'summary': summary,
                    'published_at': published_at,
                    'content_hash': content_hash,
                    'tags': tags,
                    'metadata': {
                        'ghsa_id': ghsa_id,
                        'severity': severity,
                        'source': 'github_advisories',
                    }
                })

            logger.info(f"Fetched {len(entries)} advisories from {source_name}")

        except Exception as e:
            logger.error(f"Error fetching GitHub advisories: {e}")
            raise

        return entries


class CISAKEVFetcher(BaseFetcher):
    """Fetch CISA Known Exploited Vulnerabilities from JSON feed."""

    def fetch(self, url: str, source_name: str = "CISA KEV", category: str = "vulnerabilities") -> List[Dict]:
        """Fetch and parse CISA KEV JSON feed."""
        entries = []
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            data = response.json()
            vulnerabilities = data.get('vulnerabilities', [])

            for vuln in vulnerabilities:
                cve_id = vuln.get('cveID', '')
                title = f"{cve_id}: {vuln.get('vulnerabilityName', '')}"
                url_vuln = f"https://nvd.nist.gov/vuln/detail/{cve_id}"

                # Build summary from description
                short_desc = vuln.get('shortDescription', '')
                summary = self._clean_html(short_desc)
                summary = self._truncate(summary)

                # Published date (dateAdded)
                published_at = None
                date_added = vuln.get('dateAdded')
                if date_added:
                    try:
                        published_at = datetime.fromisoformat(date_added.replace('Z', '+00:00'))
                    except (ValueError, AttributeError):
                        pass

                # Tags from required action, vendor, product
                tags = []
                if vuln.get('requiredAction'):
                    tags.append(vuln['requiredAction'])
                if vuln.get('vendorProject'):
                    tags.append(vuln['vendorProject'])
                if vuln.get('product'):
                    tags.append(vuln['product'])

                content_hash = self._make_content_hash(cve_id)

                entries.append({
                    'title': title,
                    'url': url_vuln,
                    'summary': summary,
                    'published_at': published_at,
                    'content_hash': content_hash,
                    'tags': tags[:5],
                    'metadata': {
                        'cve_id': cve_id,
                        'source': 'cisa_kev',
                        'known_ransomware': vuln.get('knownRansomwareCampaignUse', ''),
                        'notes': vuln.get('notes', ''),
                    }
                })

            logger.info(f"Fetched {len(entries)} KEVs from {source_name}")

        except Exception as e:
            logger.error(f"Error fetching CISA KEV: {e}")
            raise

        return entries


# Fetcher registry
FETCHERS = {
    'rss': RSSFetcher,
    'arxiv': ArxivFetcher,
    'hackernews': HackerNewsFetcher,
    'nvd': NVDFetcher,
    'nvd_api': NVDAPIFetcher,
    'github_trending': GitHubTrendingFetcher,
    'github_advisories': GitHubAdvisoriesFetcher,
    'cisa_kev_json': CISAKEVFetcher,
}


def get_fetcher(fetcher_type: str, **kwargs) -> BaseFetcher:
    """Get fetcher instance by type."""
    fetcher_class = FETCHERS.get(fetcher_type)
    if not fetcher_class:
        raise ValueError(f"Unknown fetcher type: {fetcher_type}")
    return fetcher_class(**kwargs)