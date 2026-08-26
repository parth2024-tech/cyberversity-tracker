"""
Database models and operations for the AI Security Monitor.
Uses SQLite for zero-cost, zero-dependency storage with WAL mode.
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path


class Database:
    """Thread-safe SQLite database for storing feed entries and intelligence analysis."""

    def __init__(self, db_path: str = "data/monitor.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
            # Enable WAL mode for high concurrency
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
            # Enable foreign key constraints
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    @contextmanager
    def transaction(self):
        """Context manager for database transactions."""
        conn = self._get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_db(self):
        """Initialize database schema with migration checks."""
        with self.transaction() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sources (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    name VARCHAR(255) UNIQUE NOT NULL,
                    category VARCHAR(50) NOT NULL,
                    type VARCHAR(50) NOT NULL,
                    url TEXT,
                    query TEXT,
                    rate_limit_seconds INTEGER NOT NULL,
                    enabled BOOLEAN NOT NULL,
                    last_fetched_at DATETIME,
                    last_status VARCHAR(20),
                    last_entries_new INTEGER NOT NULL DEFAULT 0,
                    config JSON NOT NULL DEFAULT '{}',
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS ix_sources_name ON sources (name);
                CREATE INDEX IF NOT EXISTS ix_sources_enabled ON sources (enabled);
                CREATE INDEX IF NOT EXISTS ix_sources_category ON sources (category);
                CREATE INDEX IF NOT EXISTS ix_sources_category_enabled ON sources (category, enabled);

                CREATE TABLE IF NOT EXISTS entries (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    source_id VARCHAR(36) NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    content_hash VARCHAR(64) NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    published_at DATETIME NOT NULL,
                    fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    category VARCHAR(50) NOT NULL,
                    tags JSON NOT NULL DEFAULT '[]',
                    metadata_json JSON NOT NULL DEFAULT '{}',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (source_id) REFERENCES sources (id)
                );

                CREATE INDEX IF NOT EXISTS ix_entries_source_id ON entries (source_id);
                CREATE INDEX IF NOT EXISTS ix_entries_category_published ON entries (category, published_at);
                CREATE INDEX IF NOT EXISTS ix_entries_fetched_at ON entries (fetched_at);
                CREATE INDEX IF NOT EXISTS ix_entries_source_published ON entries (source_id, published_at);
                CREATE INDEX IF NOT EXISTS ix_entries_published_at ON entries (published_at);
                CREATE INDEX IF NOT EXISTS ix_entries_category ON entries (category);
                CREATE UNIQUE INDEX IF NOT EXISTS ix_entries_content_hash ON entries (content_hash);

                CREATE TABLE IF NOT EXISTS digest_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    period_start TIMESTAMP NOT NULL,
                    period_end TIMESTAMP NOT NULL,
                    entry_count INTEGER DEFAULT 0,
                    delivery_method TEXT,
                    delivery_status TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS fetch_log (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    source_id VARCHAR(36) NOT NULL,
                    source_name VARCHAR(255) NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    entries_new INTEGER NOT NULL DEFAULT 0,
                    entries_total INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (source_id) REFERENCES sources (id)
                );

                CREATE INDEX IF NOT EXISTS ix_fetch_log_source_fetched ON fetch_log (source_id, fetched_at);
                CREATE INDEX IF NOT EXISTS ix_fetch_log_status ON fetch_log (status);
                CREATE INDEX IF NOT EXISTS ix_fetch_log_fetched_at ON fetch_log (fetched_at);
                CREATE INDEX IF NOT EXISTS ix_fetch_log_source_id ON fetch_log (source_id);

                CREATE TABLE IF NOT EXISTS entry_analysis (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    entry_id VARCHAR(36) NOT NULL UNIQUE,
                    attack_vector TEXT NOT NULL,
                    risk_assessment TEXT NOT NULL,
                    mitigation TEXT NOT NULL,
                    threat_velocity INTEGER NOT NULL,
                    severity_index INTEGER NOT NULL,
                    blast_radius_score INTEGER NOT NULL DEFAULT 0,
                    affected_ecosystem JSON NOT NULL DEFAULT '[]',
                    is_pre_cve_warning BOOLEAN NOT NULL DEFAULT 0,
                    attack_archetype VARCHAR(100) NOT NULL DEFAULT '',
                    weaponization_potential VARCHAR(50) NOT NULL DEFAULT 'Theoretical',
                    model VARCHAR(50) NOT NULL DEFAULT 'heuristic',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    overall_confidence REAL NOT NULL DEFAULT 0.7,
                    evidence_version VARCHAR(20) NOT NULL DEFAULT 'v1',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (entry_id) REFERENCES entries (id)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS ix_entry_analysis_entry_id ON entry_analysis (entry_id);
                CREATE INDEX IF NOT EXISTS ix_analysis_threat_velocity ON entry_analysis (threat_velocity);
                CREATE INDEX IF NOT EXISTS ix_analysis_pre_cve ON entry_analysis (is_pre_cve_warning);
                CREATE INDEX IF NOT EXISTS ix_analysis_severity ON entry_analysis (severity_index);

                -- Epistemic tracking: per-claim evidence for each analysis
                CREATE TABLE IF NOT EXISTS analysis_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_id VARCHAR(36) NOT NULL,
                    claim_type TEXT NOT NULL CHECK (claim_type IN ('fact','inference','hypothesis','assumption','unknown')),
                    claim_target TEXT NOT NULL,
                    claim_value TEXT NOT NULL,
                    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
                    evidence_json TEXT,
                    method TEXT NOT NULL CHECK (method IN ('heuristic','llm','hybrid')),
                    model_version TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (analysis_id) REFERENCES entry_analysis(id)
                );

                CREATE INDEX IF NOT EXISTS idx_analysis_evidence_analysis ON analysis_evidence(analysis_id);
                CREATE INDEX IF NOT EXISTS idx_analysis_evidence_target ON analysis_evidence(claim_target);
                CREATE INDEX IF NOT EXISTS idx_analysis_evidence_type ON analysis_evidence(claim_type);

                -- Ground truth outcomes for calibration
                CREATE TABLE IF NOT EXISTS analysis_outcome (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_id VARCHAR(36) NOT NULL,
                    outcome_type TEXT NOT NULL CHECK (outcome_type IN ('telegram_sent','user_dismissed','user_escalated','false_positive','confirmed')),
                    outcome_value TEXT,
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (analysis_id) REFERENCES entry_analysis(id)
                );

                CREATE INDEX IF NOT EXISTS idx_analysis_outcome_analysis ON analysis_outcome(analysis_id);
            """)

            # Safe column migrations for existing databases
            cursor = conn.execute("PRAGMA table_info(entry_analysis)")
            existing_cols = {row['name'] for row in cursor.fetchall()}

            new_columns = [
                ("blast_radius_score", "INTEGER DEFAULT 20"),
                ("affected_ecosystem", "TEXT"),
                ("is_pre_cve_warning", "BOOLEAN DEFAULT 0"),
                ("attack_archetype", "TEXT"),
                ("weaponization_potential", "TEXT"),
                ("overall_confidence", "REAL DEFAULT 0.7"),
                ("evidence_version", "TEXT DEFAULT 'v1'")
            ]
            for col_name, col_def in new_columns:
                if col_name not in existing_cols:
                    try:
                        conn.execute(f"ALTER TABLE entry_analysis ADD COLUMN {col_name} {col_def}")
                    except sqlite3.OperationalError:
                        pass

    def upsert_source(self, name: str, category: str, type_: str, url: str = None,
                      config: dict = None, rate_limit: int = 3600, enabled: bool = True) -> str:
        """Insert or update a source, return its ID."""
        import uuid
        from datetime import datetime
        config_json = json.dumps(config) if config else '{}'
        now = datetime.utcnow().isoformat()
        source_id = str(uuid.uuid4())
        with self.transaction() as conn:
            cursor = conn.execute("""
                INSERT INTO sources (id, name, category, type, url, config, query, rate_limit_seconds, enabled, last_entries_new, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    category=excluded.category,
                    type=excluded.type,
                    url=excluded.url,
                    config=excluded.config,
                    rate_limit_seconds=excluded.rate_limit_seconds,
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at
                RETURNING id
            """, (source_id, name, category, type_, url, config_json, None, rate_limit, enabled, 0, now, now))
            return cursor.fetchone()[0]

    def get_sources(self, enabled_only: bool = True) -> list[dict]:
        """Get all sources."""
        query = "SELECT * FROM sources"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY category, name"
        with self.transaction() as conn:
            return [dict(row) for row in conn.execute(query).fetchall()]

    def update_source_fetch(self, source_id: int, success: bool, error: str = None):
        """Update source last fetch time and error count."""
        with self.transaction() as conn:
            if success:
                conn.execute("""
                    UPDATE sources SET last_fetched = CURRENT_TIMESTAMP, last_success = CURRENT_TIMESTAMP, error_count = 0
                    WHERE id = ?
                """, (source_id,))
            else:
                conn.execute("""
                    UPDATE sources SET last_fetched = CURRENT_TIMESTAMP, error_count = error_count + 1
                    WHERE id = ?
                """, (source_id,))

    def log_fetch(self, source_id: int, source_name: str, status: str,
                  entries_found: int = 0, entries_new: int = 0,
                  error: str = None, duration_ms: int = 0):
        """Log a fetch attempt."""
        with self.transaction() as conn:
            conn.execute("""
                INSERT INTO fetch_log (source_id, source_name, status, entries_found, entries_new, error_message, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (source_id, source_name, status, entries_found, entries_new, error, duration_ms))

    def add_entry(self, source_id: int, source_name: str, category: str,
                  title: str, url: str, content_hash: str,
                  summary: str = None, published_at: datetime = None,
                  tags: list[str] = None, metadata: dict = None) -> int | None:
        """Add an entry if not duplicate (by content_hash). Returns inserted entry ID or None."""
        tags_json = json.dumps(tags) if tags else None
        metadata_json = json.dumps(metadata) if metadata else None
        pub_time = published_at.isoformat() if published_at else None

        with self.transaction() as conn:
            try:
                cursor = conn.execute("""
                    INSERT INTO entries (source_id, source_name, category, title, url, content_hash,
                                         summary, published_at, tags, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id
                """, (source_id, source_name, category, title, url, content_hash,
                      summary, pub_time, tags_json, metadata_json))
                row = cursor.fetchone()
                return row[0] if row else True
            except sqlite3.IntegrityError:
                return None  # Duplicate content_hash

    def save_analysis(self, entry_id: int, attack_vector: str, risk_assessment: str,
                      mitigation: str, threat_velocity: int, severity_index: int,
                      blast_radius_score: int = 20, affected_ecosystem: list[str] = None,
                      is_pre_cve_warning: bool = False, attack_archetype: str = None,
                      weaponization_potential: str = None, ai_model: str = "AetherGuard:v2",
                      overall_confidence: float = 0.7, evidence_version: str = "v1",
                      evidence_bundles: list | None = None):
        """Save AI analysis for an entry with epistemic evidence tracking."""
        affected_json = json.dumps(affected_ecosystem) if affected_ecosystem else None
        with self.transaction() as conn:
            # Insert analysis row
            cursor = conn.execute("""
                INSERT OR REPLACE INTO entry_analysis
                (entry_id, attack_vector, risk_assessment, mitigation, threat_velocity, severity_index,
                 blast_radius_score, affected_ecosystem, is_pre_cve_warning, attack_archetype,
                 weaponization_potential, model, overall_confidence, evidence_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (entry_id, attack_vector, risk_assessment, mitigation, threat_velocity, severity_index,
                  blast_radius_score, affected_json, 1 if is_pre_cve_warning else 0,
                  attack_archetype, weaponization_potential, ai_model, overall_confidence, evidence_version))
            
            analysis_id = cursor.lastrowid
            
            # Insert evidence bundles if provided
            if evidence_bundles:
                for bundle in evidence_bundles:
                    evidence_json = json.dumps(bundle.get('evidence', {})) if bundle.get('evidence') else None
                    conn.execute("""
                        INSERT INTO analysis_evidence
                        (analysis_id, claim_type, claim_target, claim_value, confidence, evidence_json, method, model_version)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        analysis_id,
                        bundle.get('claim_type', 'inference'),
                        bundle.get('claim_target', ''),
                        str(bundle.get('value', '')),
                        bundle.get('confidence', 0.7),
                        evidence_json,
                        bundle.get('method', 'heuristic'),
                        bundle.get('model_version', 'heuristic:v2.1')
                    ))

    def get_analysis(self, entry_id: int) -> dict | None:
        """Get analysis for an entry."""
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM entry_analysis WHERE entry_id = ?", (entry_id,)).fetchone()
            if row:
                d = dict(row)
                if d.get('affected_ecosystem'):
                    try:
                        d['affected_ecosystem'] = json.loads(d['affected_ecosystem'])
                    except Exception:
                        pass
                return d
            return None

    def get_entries(self, since: datetime = None, category: str = None,
                    limit: int = None, offset: int = 0,
                    pre_cve_only: bool = False, high_velocity_only: bool = False) -> list[dict]:
        """Get entries joined with AI analysis, Blast Radius, and Pre-CVE intelligence."""
        query = """
            SELECT 
                e.*,
                a.attack_vector,
                a.risk_assessment,
                a.mitigation,
                a.threat_velocity,
                a.severity_index,
                a.blast_radius_score,
                a.affected_ecosystem,
                a.is_pre_cve_warning,
                a.attack_archetype,
                a.weaponization_potential,
                a.model as analysis_model
            FROM entries e
            LEFT JOIN entry_analysis a ON e.id = a.entry_id
            WHERE 1=1
        """
        params = []

        if since:
            query += " AND e.published_at >= ?"
            params.append(since.isoformat())

        if category:
            query += " AND e.category = ?"
            params.append(category)

        if pre_cve_only:
            query += " AND a.is_pre_cve_warning = 1"

        if high_velocity_only:
            query += " AND a.threat_velocity >= 70"

        query += " ORDER BY e.published_at DESC"

        if limit:
            query += " LIMIT ?"
            params.append(limit)
        if offset:
            query += " OFFSET ?"
            params.append(offset)

        with self.transaction() as conn:
            rows = conn.execute(query, params).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                if d.get('tags'):
                    try:
                        d['tags'] = json.loads(d['tags'])
                    except Exception:
                        pass
                if d.get('metadata_json'):
                    try:
                        d['metadata'] = json.loads(d['metadata_json'])
                    except Exception:
                        pass
                if d.get('affected_ecosystem'):
                    try:
                        d['affected_ecosystem'] = json.loads(d['affected_ecosystem'])
                    except Exception:
                        pass

                # Structure analysis sub-object for convenience
                if d.get('threat_velocity') is not None:
                    d['analysis'] = {
                        'attack_vector': d.get('attack_vector'),
                        'risk_assessment': d.get('risk_assessment'),
                        'mitigation': d.get('mitigation'),
                        'threat_velocity': d.get('threat_velocity'),
                        'severity_index': d.get('severity_index'),
                        'blast_radius_score': d.get('blast_radius_score', 20),
                        'affected_ecosystem': d.get('affected_ecosystem', []),
                        'is_pre_cve_warning': bool(d.get('is_pre_cve_warning')),
                        'attack_archetype': d.get('attack_archetype'),
                        'weaponization_potential': d.get('weaponization_potential'),
                        'ai_model': d.get('analysis_model')
                    }
                result.append(d)
            return result

    def get_entries_for_digest(self, since: datetime, max_per_category: int = 10) -> dict[str, list[dict]]:
        """Get entries grouped by category for digest."""
        categories = ['ai_tech', 'ai_research', 'cybersecurity', 'vulnerabilities', 'github_trending']
        result = {}

        for cat in categories:
            entries = self.get_entries(since=since, category=cat, limit=max_per_category)
            if entries:
                result[cat] = entries

        return result

    def get_unanalyzed_entries(self, since: datetime = None, limit: int = 200) -> list[dict]:
        """Get entries that haven't been analyzed yet."""
        query = """
            SELECT e.* FROM entries e
            LEFT JOIN entry_analysis a ON e.id = a.entry_id
            WHERE a.entry_id IS NULL
        """
        params = []
        if since:
            query += " AND e.published_at >= ?"
            params.append(since.isoformat())
        query += " ORDER BY e.published_at DESC LIMIT ?"
        params.append(limit)

        with self.transaction() as conn:
            rows = conn.execute(query, params).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                if d.get('tags'):
                    try:
                        d['tags'] = json.loads(d['tags'])
                    except Exception:
                        pass
                if d.get('metadata_json'):
                    try:
                        d['metadata'] = json.loads(d['metadata_json'])
                    except Exception:
                        pass
                result.append(d)
            return result

    def get_stats(self) -> dict:
        """Get database statistics."""
        with self.transaction() as conn:
            stats = {}
            stats['total_entries'] = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            stats['total_sources'] = conn.execute("SELECT COUNT(*) FROM sources WHERE enabled=1").fetchone()[0]

            # Entries by category
            cat_rows = conn.execute("""
                SELECT category, COUNT(*) as count FROM entries GROUP BY category ORDER BY count DESC
            """).fetchall()
            stats['by_category'] = {row['category']: row['count'] for row in cat_rows}

            # Recent fetch status
            fetch_rows = conn.execute("""
                SELECT source_name, status, entries_new, fetched_at
                FROM fetch_log
                WHERE fetched_at >= datetime('now', '-24 hours')
                ORDER BY fetched_at DESC
            """).fetchall()
            stats['recent_fetches'] = [dict(row) for row in fetch_rows]

            # Analysis stats
            analyzed = conn.execute("SELECT COUNT(*) FROM entry_analysis").fetchone()[0]
            stats['analyzed_entries'] = analyzed
            high_vel = conn.execute("SELECT COUNT(*) FROM entry_analysis WHERE threat_velocity >= 70").fetchone()[0]
            stats['high_velocity_entries'] = high_vel
            pre_cve = conn.execute("SELECT COUNT(*) FROM entry_analysis WHERE is_pre_cve_warning = 1").fetchone()[0]
            stats['pre_cve_warnings'] = pre_cve

            return stats

    def cleanup_old_entries(self, days: int = 90):
        """Remove entries older than specified days."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self.transaction() as conn:
            cursor = conn.execute("DELETE FROM entries WHERE published_at < ?", (cutoff,))
            return cursor.rowcount

    def close(self):
        """Close thread-local connection."""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# Global instance
_db_instance = None


def get_db(db_path: str = "data/monitor.db") -> Database:
    """Get global database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database(db_path)
    return _db_instance
