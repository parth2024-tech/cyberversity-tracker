"""
Main monitor orchestration - coordinates fetching, storing, analyzing, and delivering.
"""

import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from analyzer import create_analyzer
from database import get_db
from delivery import get_delivery
from fetchers import get_fetcher

logger = logging.getLogger(__name__)


class AISecurityMonitor:
    """Main monitor class that orchestrates the entire pipeline."""

    def __init__(self, config_path: str = "config/sources.yaml"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.db = get_db(self.config['database']['path'])
        self._setup_logging()
        self._init_sources()

    def _load_config(self) -> dict:
        """Load configuration from YAML."""
        with open(self.config_path) as f:
            return yaml.safe_load(f)

    def _setup_logging(self):
        """Configure logging."""
        log_config = self.config.get('logging', {})
        log_file = log_config.get('file', 'logs/monitor.log')
        log_level = getattr(logging, log_config.get('level', 'INFO'))

        Path(log_file).parent.mkdir(parents=True, exist_ok=True)

        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )

    def _init_sources(self):
        """Initialize sources in database from config."""
        for source_config in self.config.get('sources', []):
            if not source_config.get('enabled', True):
                continue

            self.db.upsert_source(
                name=source_config['name'],
                category=source_config['category'],
                type_=source_config['type'],
                url=source_config.get('url'),
                config={k: v for k, v in source_config.items()
                        if k not in ['name', 'category', 'type', 'url', 'rate_limit_seconds', 'enabled']},
                rate_limit=source_config.get('rate_limit_seconds', 3600),
                enabled=source_config.get('enabled', True)
            )

    def _should_fetch(self, source: dict) -> bool:
        """Check if source should be fetched based on rate limit."""
        if not source.get('last_fetched'):
            return True

        last_fetch = datetime.fromisoformat(source['last_fetched'].replace('Z', '+00:00'))
        rate_limit = timedelta(seconds=source.get('rate_limit_seconds', 3600))
        return datetime.now() - last_fetch >= rate_limit

    def fetch_source(self, source: dict, on_entry_found: callable = None) -> dict:
        """Fetch entries from a single source."""
        source_id = source['id']
        source_name = source['name']
        source_type = source['type']
        category = source['category']

        start_time = time.time()
        entries_found = 0
        entries_new = 0
        error = None

        try:
            # Check rate limit
            if not self._should_fetch(source):
                logger.info(f"Skipping {source_name} (rate limited)")
                self.db.log_fetch(source_id, source_name, 'skipped', 0, 0, 'rate limited', 0)
                return {'status': 'skipped', 'entries_found': 0, 'entries_new': 0}

            # Get fetcher
            fetcher_kwargs = {'rate_limit_seconds': source.get('rate_limit_seconds', 3600)}
            source_config = source.get('config_json')
            if source_config:
                import json
                fetcher_kwargs.update(json.loads(source_config))

            fetcher = get_fetcher(source_type, **fetcher_kwargs)

            # Fetch entries based on source type
            url = source.get('url')
            if source_type == 'rss':
                entries = fetcher.fetch(url, source_name, category)
            elif source_type == 'arxiv':
                entries = fetcher.fetch(
                    fetcher_kwargs.get('query', ''),
                    fetcher_kwargs.get('max_results', 50),
                    source_name, category
                )
            elif source_type == 'hackernews':
                entries = fetcher.fetch(source_name, category, fetcher_kwargs.get('max_stories', 30))
            elif source_type == 'nvd':
                entries = fetcher.fetch(url, source_name, category)
            elif source_type == 'nvd_api':
                entries = fetcher.fetch(source_name, category, fetcher_kwargs.get('results_per_page', 50))
            elif source_type == 'github_trending':
                entries = fetcher.fetch(
                    fetcher_kwargs.get('language', ''),
                    fetcher_kwargs.get('since', 'daily'),
                    source_name, category
                )
            elif source_type == 'github_advisories':
                entries = fetcher.fetch(source_name, category, fetcher_kwargs.get('per_page', 50))
            elif source_type == 'cisa_kev_json':
                entries = fetcher.fetch(url, source_name, category)
            else:
                raise ValueError(f"Unknown source type: {source_type}")

            entries_found = len(entries)

            # Store new entries
            for entry in entries:
                entry_id = self.db.add_entry(
                    source_id=source_id,
                    source_name=source_name,
                    category=category,
                    title=entry['title'],
                    url=entry['url'],
                    content_hash=entry['content_hash'],
                    summary=entry.get('summary'),
                    published_at=entry.get('published_at'),
                    tags=entry.get('tags'),
                    metadata=entry.get('metadata')
                )
                if entry_id:
                    entries_new += 1
                    # Auto-analyze immediately (Features 1, 3, 5)
                    try:
                        from analyzer import create_analyzer
                        analyzer = create_analyzer(self.config.get('analyzer', {}))
                        raw_dict = {
                            'id': entry_id if isinstance(entry_id, int) else 0,
                            'title': entry['title'],
                            'url': entry['url'],
                            'summary': entry.get('summary', ''),
                            'category': category,
                            'source_name': source_name,
                            'published_at': entry.get('published_at'),
                            'tags': entry.get('tags', []),
                            'metadata': entry.get('metadata', {})
                        }
                        analysis = analyzer.analyze(raw_dict)
                        if isinstance(entry_id, int):
                            self.db.save_analysis(
                                entry_id=entry_id,
                                attack_vector=analysis.attack_vector,
                                risk_assessment=analysis.risk_assessment,
                                mitigation=analysis.mitigation,
                                threat_velocity=analysis.threat_velocity,
                                severity_index=analysis.severity_index,
                                blast_radius_score=analysis.blast_radius_score,
                                affected_ecosystem=analysis.affected_ecosystem,
                                is_pre_cve_warning=analysis.is_pre_cve_warning,
                                attack_archetype=analysis.attack_archetype,
                                weaponization_potential=analysis.weaponization_potential,
                                ai_model=analysis.ai_model
                            )
                    except Exception as an_err:
                        logger.warning(f"Error auto-analyzing entry: {an_err}")
                        analysis = None

                    if on_entry_found:
                        try:
                            live_entry = {
                                'source_name': source_name,
                                'category': category,
                                'title': entry['title'],
                                'url': entry['url'],
                                'summary': entry.get('summary'),
                                'published_at': entry.get('published_at').isoformat() if isinstance(entry.get('published_at'), datetime) else str(entry.get('published_at') or ''),
                                'tags': entry.get('tags', []),
                                'metadata': entry.get('metadata', {})
                            }
                            if analysis:
                                live_entry['analysis'] = {
                                    'attack_vector': analysis.attack_vector,
                                    'risk_assessment': analysis.risk_assessment,
                                    'mitigation': analysis.mitigation,
                                    'threat_velocity': analysis.threat_velocity,
                                    'severity_index': analysis.severity_index,
                                    'blast_radius_score': analysis.blast_radius_score,
                                    'affected_ecosystem': analysis.affected_ecosystem,
                                    'is_pre_cve_warning': analysis.is_pre_cve_warning,
                                    'attack_archetype': analysis.attack_archetype,
                                    'weaponization_potential': analysis.weaponization_potential,
                                }
                            on_entry_found(live_entry)
                        except Exception as cb_err:
                            logger.warning(f"Error in on_entry_found callback: {cb_err}")

            duration_ms = int((time.time() - start_time) * 1000)
            self.db.log_fetch(source_id, source_name, 'success', entries_found, entries_new, None, duration_ms)
            self.db.update_source_fetch(source_id, True)

            logger.info(f"Fetched {source_name}: {entries_found} found, {entries_new} new")
            return {'status': 'success', 'entries_found': entries_found, 'entries_new': entries_new}

        except Exception as e:
            error = str(e)
            duration_ms = int((time.time() - start_time) * 1000)
            self.db.log_fetch(source_id, source_name, 'error', entries_found, entries_new, error, duration_ms)
            self.db.update_source_fetch(source_id, False, error)
            logger.error(f"Error fetching {source_name}: {e}")
            return {'status': 'error', 'entries_found': entries_found, 'entries_new': entries_new, 'error': error}

    def fetch_all(self, on_entry_found: callable = None, ignore_rate_limit: bool = False) -> dict:
        """Fetch from all enabled sources."""
        sources = self.db.get_sources(enabled_only=True)
        results = {'success': 0, 'error': 0, 'skipped': 0, 'total_new': 0}

        for source in sources:
            if ignore_rate_limit:
                source['last_fetched'] = None
            result = self.fetch_source(source, on_entry_found=on_entry_found)
            results[result['status']] = results.get(result['status'], 0) + 1
            results['total_new'] += result.get('entries_new', 0)

        return results

    def generate_digest(self, since: datetime = None, max_per_category: int = 10) -> dict:
        """Generate digest content grouped by category."""
        if since is None:
            # Default to last 24 hours for daily, 7 days for weekly
            schedule = self.config.get('digest', {}).get('schedule', 'daily')
            days = 1 if schedule == 'daily' else 7
            since = datetime.now() - timedelta(days=days)

        max_per_cat = self.config.get('digest', {}).get('max_items_per_category', max_per_category)
        entries_by_category = self.db.get_entries_for_digest(since, max_per_cat)

        # Build text content
        category_labels = {
            'ai_tech': '🤖 AI Technology Launches',
            'ai_research': '📚 AI Research Papers (arXiv)',
            'cybersecurity': '🔒 Cybersecurity News',
            'vulnerabilities': '⚠️ Vulnerabilities & CVEs',
            'github_trending': '⭐ GitHub Trending Security',
        }

        lines = []
        total_entries = sum(len(e) for e in entries_by_category.values())

        lines.append("AI & Security Monitor Digest")
        lines.append(f"Period: {since.strftime('%Y-%m-%d')} to {datetime.now().strftime('%Y-%m-%d')}")
        lines.append(f"Total new items: {total_entries}")
        lines.append("=" * 60)

        for cat, entries in entries_by_category.items():
            if not entries:
                continue

            label = category_labels.get(cat, cat.replace('_', ' ').title())
            lines.append(f"\n{label} ({len(entries)} items)")
            lines.append("-" * 40)

            for i, entry in enumerate(entries, 1):
                pub_date = entry.get('published_at')
                if isinstance(pub_date, datetime):
                    date_str = pub_date.strftime('%Y-%m-%d %H:%M')
                elif isinstance(pub_date, str):
                    date_str = pub_date[:16]
                else:
                    date_str = 'Unknown date'

                source = entry.get('source_name', 'Unknown')
                lines.append(f"\n{i}. {entry['title']}")
                lines.append(f"   Source: {source} | Date: {date_str}")
                lines.append(f"   URL: {entry['url']}")

                summary = entry.get('summary')
                if summary:
                    lines.append(f"   Summary: {summary}")

                tags = entry.get('tags', [])
                if tags:
                    lines.append(f"   Tags: {', '.join(tags[:5])}")

        content = '\n'.join(lines)
        return {
            'content': content,
            'entries_by_category': entries_by_category,
            'total_entries': total_entries,
            'period_start': since,
            'period_end': datetime.now()
        }

    def send_digest(self, method: str = 'console', custom_config: dict = None) -> bool:
        """Generate and send digest via specified method."""
        digest = self.generate_digest()

        # Get delivery config
        delivery_config = self.config.get('delivery', {}).get(method, {})
        if custom_config:
            delivery_config.update(custom_config)

        # Add console as fallback
        if method != 'console':
            delivery_config.setdefault('fallback', True)

        try:
            delivery = get_delivery(method, delivery_config)
            subject = f"AI & Security Digest - {datetime.now().strftime('%Y-%m-%d')}"

            success = delivery.send(subject, digest['content'], digest['entries_by_category'])

            # Log digest history
            with self.db.transaction() as conn:
                conn.execute("""
                    INSERT INTO digest_history (period_start, period_end, entry_count, delivery_method, delivery_status)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    digest['period_start'].isoformat(),
                    digest['period_end'].isoformat(),
                    digest['total_entries'],
                    method,
                    'success' if success else 'failed'
                ))

            return success

        except Exception as e:
            logger.error(f"Failed to send digest via {method}: {e}")
            # Try console fallback
            if method != 'console':
                logger.info("Falling back to console output")
                return self.send_digest('console')
            return False

    def get_stats(self) -> dict:
        """Get monitor statistics."""
        return self.db.get_stats()

    def cleanup(self, days: int = 90):
        """Clean up old entries."""
        return self.db.cleanup_old_entries(days)

    def run_analysis(self, since: datetime = None, limit: int = 50) -> dict:
        """Run AI analysis on unanalyzed entries."""
        if since is None:
            schedule = self.config.get('digest', {}).get('schedule', 'daily')
            days = 1 if schedule == 'daily' else 7
            since = datetime.now() - timedelta(days=days)

        # Get unanalyzed entries
        unanalyzed = self.db.get_unanalyzed_entries(since=since, limit=limit)

        if not unanalyzed:
            logger.info("No unanalyzed entries to process")
            return {'analyzed': 0, 'failed': 0, 'high_velocity': 0}

        # Get analyzer (automatically manages LLM with fast heuristic fallback)
        analyzer_config = self.config.get('analyzer', {})
        analyzer = create_analyzer(analyzer_config)

        # Analyze batch
        results = analyzer.analyze_batch(unanalyzed)

        # Save analyses
        analyzed = 0
        high_velocity = 0
        for entry_id, analysis in results:
            self.db.save_analysis(
                entry_id=entry_id,
                attack_vector=analysis.attack_vector,
                risk_assessment=analysis.risk_assessment,
                mitigation=analysis.mitigation,
                threat_velocity=analysis.threat_velocity,
                severity_index=analysis.severity_index,
                blast_radius_score=analysis.blast_radius_score,
                affected_ecosystem=analysis.affected_ecosystem,
                is_pre_cve_warning=analysis.is_pre_cve_warning,
                attack_archetype=analysis.attack_archetype,
                weaponization_potential=analysis.weaponization_potential,
                ai_model=analysis.ai_model
            )
            analyzed += 1
            if analysis.threat_velocity >= 70:
                high_velocity += 1

        logger.info(f"AI Analysis complete: {analyzed} analyzed, {high_velocity} high velocity")
        return {'analyzed': analyzed, 'failed': len(unanalyzed) - analyzed, 'high_velocity': high_velocity}

    def generate_enriched_digest(self, since: datetime = None, max_per_category: int = 10) -> dict:
        """Generate digest with AI analysis enrichment."""
        if since is None:
            schedule = self.config.get('digest', {}).get('schedule', 'daily')
            days = 1 if schedule == 'daily' else 7
            since = datetime.now() - timedelta(days=days)

        max_per_cat = self.config.get('digest', {}).get('max_items_per_category', max_per_category)
        entries_by_category = self.db.get_entries_for_digest(since, max_per_cat)

        # Enrich with analysis where available
        for cat, entries in entries_by_category.items():
            for entry in entries:
                analysis = self.db.get_analysis(entry['id'])
                if analysis:
                    entry['analysis'] = analysis

        # Build text content
        category_labels = {
            'ai_tech': '🤖 AI Technology Launches',
            'ai_research': '📚 AI Research Papers (arXiv)',
            'cybersecurity': '🔒 Cybersecurity News',
            'vulnerabilities': '⚠️ Vulnerabilities & CVEs',
            'github_trending': '⭐ GitHub Trending Security',
        }

        lines = []
        total_entries = sum(len(e) for e in entries_by_category.values())

        lines.append("AI & Security Monitor Digest (AI-Enriched)")
        lines.append(f"Period: {since.strftime('%Y-%m-%d')} to {datetime.now().strftime('%Y-%m-%d')}")
        lines.append(f"Total new items: {total_entries}")
        lines.append("=" * 60)

        for cat, entries in entries_by_category.items():
            if not entries:
                continue

            label = category_labels.get(cat, cat.replace('_', ' ').title())
            lines.append(f"\n{label} ({len(entries)} items)")
            lines.append("-" * 40)

            for i, entry in enumerate(entries, 1):
                pub_date = entry.get('published_at')
                if isinstance(pub_date, datetime):
                    date_str = pub_date.strftime('%Y-%m-%d %H:%M')
                elif isinstance(pub_date, str):
                    date_str = pub_date[:16]
                else:
                    date_str = 'Unknown date'

                source = entry.get('source_name', 'Unknown')
                lines.append(f"\n{i}. {entry['title']}")
                lines.append(f"   Source: {source} | Date: {date_str}")
                lines.append(f"   URL: {entry['url']}")

                # Show AI analysis if available
                if entry.get('analysis'):
                    a = entry['analysis']
                    lines.append(f"   🎯 Attack Vector: {a['attack_vector']}")
                    lines.append(f"   ⚠️ Risk: {a['risk_assessment']}")
                    lines.append(f"   🛡️ Mitigation: {a['mitigation']}")
                    lines.append(f"   📊 Threat Velocity: {a['threat_velocity']}/100 | Severity: {a['severity_index']}/100")
                else:
                    summary = entry.get('summary')
                    if summary:
                        lines.append(f"   Summary: {summary}")

                tags = entry.get('tags', [])
                if tags:
                    lines.append(f"   Tags: {', '.join(tags[:5])}")

        content = '\n'.join(lines)
        return {
            'content': content,
            'entries_by_category': entries_by_category,
            'total_entries': total_entries,
            'period_start': since,
            'period_end': datetime.now()
        }


def run_fetch_job(config_path: str = "config/sources.yaml"):
    """Standalone function for cron job - fetch all sources."""
    monitor = AISecurityMonitor(config_path)
    return monitor.fetch_all()


def run_digest_job(config_path: str = "config/sources.yaml", method: str = 'console', delivery_config: dict = None):
    """Standalone function for cron job - generate and send digest."""
    monitor = AISecurityMonitor(config_path)
    return monitor.send_digest(method, delivery_config)
