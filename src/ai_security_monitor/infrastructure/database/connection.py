"""
Database connection and session management.
Async SQLAlchemy with SQLite (aiosqlite) for zero-cost deployment.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from ai_security_monitor.config.settings import settings


def _ensure_seed_database(db_path: str) -> None:
    """Ensure SQLite database directory exists without auto-seeding dummy entries."""
    import os

    dir_name = os.path.dirname(db_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    return


class DatabaseManager:
    """Manages database engine and sessions."""

    def __init__(self, url: str | None = None, echo: bool | None = None):
        self._custom_url = url
        self._echo = echo if echo is not None else settings.database.echo
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def url(self) -> str:
        if self._custom_url is not None:
            return self._custom_url
        return settings.database.resolved_url

    def reset(self) -> None:
        """Reset lazy engine and session factory to force re-evaluation of URL."""
        self._engine = None
        self._session_factory = None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            self._engine = self._create_engine()
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            self._session_factory = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )
        return self._session_factory

    def _create_engine(self) -> AsyncEngine:
        """Create async engine with appropriate configuration."""
        # For SQLite, ensure directory exists and use NullPool
        if self.url.startswith("sqlite"):
            import os

            db_path = (
                self.url.replace("sqlite+aiosqlite:///", "")
                .replace("sqlite:///", "")
                .split("?")[0]
            )
            dir_name = os.path.dirname(db_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

            # Auto-seed initial intelligence database on fresh cloud boot
            _ensure_seed_database(db_path)

            engine = create_async_engine(
                self.url,
                echo=self._echo,
                poolclass=NullPool,
                connect_args={"check_same_thread": False},
            )
        else:
            engine = create_async_engine(
                self.url,
                echo=self._echo,
                pool_size=settings.database.pool_size,
                max_overflow=settings.database.max_overflow,
            )

        # Enable WAL mode for SQLite
        if self.url.startswith("sqlite"):

            @event.listens_for(engine.sync_engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.execute("PRAGMA synchronous=NORMAL")
                # Memory-optimized SQLite PRAGMAs for Render 512MB Free Tier
                cursor.execute(
                    f"PRAGMA cache_size={settings.database.sqlite_cache_size}"
                )  # 4MB page cache
                cursor.execute(
                    "PRAGMA temp_store=FILE"
                )  # spill temp tables to disk, preserving heap
                cursor.execute(
                    f"PRAGMA mmap_size={settings.database.sqlite_mmap_size}"
                )  # 32MB mmap (down from 256MB)
                cursor.execute(
                    f"PRAGMA wal_autocheckpoint={settings.database.sqlite_wal_autocheckpoint}"
                )  # checkpoint every 100 pages (400KB)
                try:
                    cursor.execute("PRAGMA auto_vacuum = INCREMENTAL")
                except Exception:
                    pass
                try:
                    cursor.execute("PRAGMA optimize")
                except Exception:
                    pass
                cursor.close()

                # Zero-Daemon In-Process Vector Memory: sqlite-vec extension (Pillar 1)
                try:
                    import sqlite_vec

                    raw_conn = dbapi_connection
                    while hasattr(raw_conn, "_connection"):
                        raw_conn = raw_conn._connection
                    if hasattr(raw_conn, "enable_load_extension"):
                        raw_conn.enable_load_extension(True)
                        sqlite_vec.load(raw_conn)
                        raw_conn.enable_load_extension(False)
                except Exception:
                    pass

        return engine

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session with automatic transaction management."""
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession, None]:
        """Explicit transaction context manager."""
        async with self.session() as session:
            async with session.begin():
                yield session

    async def close(self) -> None:
        """Close the engine and all connections."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

    async def health_check(self) -> bool:
        """Check database connectivity."""
        try:
            async with self.session() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def init_db(self) -> None:
        """Initialize database - create tables if they don't exist."""
        db_path = None
        if self.url.startswith("sqlite"):
            db_path = (
                self.url.replace("sqlite+aiosqlite:///", "")
                .replace("sqlite:///", "")
                .split("?")[0]
            )
            _ensure_seed_database(db_path)
        from ai_security_monitor.infrastructure.database.models import Base

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Ensure soft-delete columns exist on pre-existing databases
        if self.url.startswith("sqlite"):
            try:
                async with self.engine.begin() as conn:
                    await conn.execute(
                        text(
                            "ALTER TABLE entries ADD COLUMN is_purged BOOLEAN DEFAULT 0"
                        )
                    )
            except Exception:
                pass
            try:
                async with self.engine.begin() as conn:
                    await conn.execute(
                        text("ALTER TABLE entries ADD COLUMN purged_at DATETIME")
                    )
            except Exception:
                pass
            try:
                async with self.engine.begin() as conn:
                    await conn.execute(
                        text(
                            "ALTER TABLE entries ADD COLUMN is_user_saved BOOLEAN DEFAULT 0"
                        )
                    )
            except Exception:
                pass

            # Pillar 3 Telemetry Columns on llm_receipts
            for col, col_type in [
                ("execution_tier", "VARCHAR(30)"),
                ("cache_read_input_tokens", "INTEGER DEFAULT 0"),
                ("cache_creation_input_tokens", "INTEGER DEFAULT 0"),
            ]:
                try:
                    async with self.engine.begin() as conn:
                        await conn.execute(
                            text(
                                f"ALTER TABLE llm_receipts ADD COLUMN {col} {col_type}"
                            )
                        )
                except Exception:
                    pass

            # Decision Brief column on entry_analysis and entry_analyses
            for tbl in ("entry_analysis", "entry_analyses"):
                try:
                    async with self.engine.begin() as conn:
                        await conn.execute(
                            text(f"ALTER TABLE {tbl} ADD COLUMN decision_brief JSON")
                        )
                except Exception:
                    pass

            # Source auto-quarantine metadata columns
            for col, col_type in [
                ("is_quarantined", "BOOLEAN DEFAULT 0"),
                ("consecutive_failures", "INTEGER DEFAULT 0"),
                ("quarantined_at", "DATETIME"),
                ("quarantine_reason", "TEXT"),
            ]:
                try:
                    async with self.engine.begin() as conn:
                        await conn.execute(
                            text(f"ALTER TABLE sources ADD COLUMN {col} {col_type}")
                        )
                except Exception:
                    pass

            # Pillar 4: AI Entity & Benchmark Knowledge Graph Table
            try:
                async with self.engine.begin() as conn:
                    await conn.execute(
                        text(
                            "CREATE TABLE IF NOT EXISTS entry_entities ("
                            "id VARCHAR(36) PRIMARY KEY, "
                            "entry_id VARCHAR(36) NOT NULL REFERENCES entries(id) ON DELETE CASCADE, "
                            "entity_type VARCHAR(32) NOT NULL, "
                            "name VARCHAR(128) NOT NULL, "
                            "display_name VARCHAR(128) NOT NULL, "
                            "metric_value VARCHAR(64), "
                            "context TEXT, "
                            "confidence FLOAT DEFAULT 1.0, "
                            "created_at DATETIME NOT NULL"
                            ")"
                        )
                    )
                    await conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_entry_entities_entry_id "
                            "ON entry_entities(entry_id)"
                        )
                    )
                    await conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_entry_entities_type_name "
                            "ON entry_entities(entity_type, name)"
                        )
                    )
                    await conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_entry_entities_created_type "
                            "ON entry_entities(created_at, entity_type)"
                        )
                    )
            except Exception:
                pass

            # Audit and Replay Log: research_runs Table (Workstream A1)
            try:
                async with self.engine.begin() as conn:
                    await conn.execute(
                        text(
                            "CREATE TABLE IF NOT EXISTS research_runs ("
                            "id VARCHAR(36) PRIMARY KEY, "
                            "query VARCHAR(512) NOT NULL, "
                            "sources_count INTEGER DEFAULT 0, "
                            "execution_steps JSON, "
                            "cost_estimate FLOAT DEFAULT 0.0, "
                            "coverage_score FLOAT DEFAULT 1.0, "
                            "output_markdown TEXT NOT NULL, "
                            "created_at DATETIME NOT NULL"
                            ")"
                        )
                    )
                    await conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_research_runs_query "
                            "ON research_runs(query)"
                        )
                    )
                    await conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_research_runs_created_at "
                            "ON research_runs(created_at)"
                        )
                    )
            except Exception:
                pass

            # Zero-Daemon Search: SQLite FTS5 Full-Text Index & Database Triggers (Technique 9)
            try:
                async with self.engine.begin() as conn:
                    await conn.execute(
                        text(
                            "CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5("
                            "title, summary, category, entry_id UNINDEXED"
                            ")"
                        )
                    )
                    # Refresh triggers with idempotent duplicate-deletion on insert/replace
                    await conn.execute(text("DROP TRIGGER IF EXISTS entries_ai"))
                    await conn.execute(text("DROP TRIGGER IF EXISTS entries_au"))
                    await conn.execute(text("DROP TRIGGER IF EXISTS entries_ad"))

                    await conn.execute(
                        text(
                            "CREATE TRIGGER entries_ai AFTER INSERT ON entries BEGIN "
                            "DELETE FROM entries_fts WHERE entry_id = new.id; "
                            "INSERT INTO entries_fts(entry_id, title, summary, category) "
                            "VALUES (new.id, new.title, new.summary, new.category); "
                            "END;"
                        )
                    )
                    await conn.execute(
                        text(
                            "CREATE TRIGGER entries_ad AFTER DELETE ON entries BEGIN "
                            "DELETE FROM entries_fts WHERE entry_id = old.id; "
                            "END;"
                        )
                    )
                    await conn.execute(
                        text(
                            "CREATE TRIGGER entries_au AFTER UPDATE ON entries BEGIN "
                            "DELETE FROM entries_fts WHERE entry_id = old.id; "
                            "INSERT INTO entries_fts(entry_id, title, summary, category) "
                            "VALUES (new.id, new.title, new.summary, new.category); "
                            "END;"
                        )
                    )
                    # Backfill existing entries into FTS5 index only if FTS table is completely empty but entries exist
                    fts_count_res = await conn.execute(
                        text("SELECT count(*) FROM entries_fts")
                    )
                    entries_count_res = await conn.execute(
                        text("SELECT count(*) FROM entries WHERE is_purged = 0")
                    )
                    if (fts_count_res.scalar() or 0) == 0 and (entries_count_res.scalar() or 0) > 0:
                        await conn.execute(
                            text(
                                "INSERT INTO entries_fts(entry_id, title, summary, category) "
                                "SELECT id, title, summary, category FROM entries "
                                "WHERE is_purged = 0"
                            )
                        )
            except Exception:
                pass

            # Zero-Daemon Vector Memory: sqlite-vec vec0 Virtual Table (Pillar 1)
            try:
                async with self.engine.begin() as conn:
                    await conn.execute(
                        text(
                            "CREATE VIRTUAL TABLE IF NOT EXISTS entries_vec USING vec0("
                            "entry_id text primary key, "
                            "embedding float[384]"
                            ")"
                        )
                    )
            except Exception:
                pass

    async def maintain_fts_and_storage(self) -> None:
        """Run FTS rebuild, segment optimization, and incremental vacuum (Defect Ledger D2)."""
        if not self._url.startswith("sqlite"):
            return
        async with self.engine.begin() as conn:
            try:
                # Rebuild FTS5 index to eliminate orphan or duplicate segments
                await conn.execute(
                    text("INSERT INTO entries_fts(entries_fts) VALUES('rebuild')")
                )
            except Exception:
                pass
            try:
                # Merge FTS5 b-tree index segments
                await conn.execute(
                    text("INSERT INTO entries_fts(entries_fts) VALUES('optimize')")
                )
            except Exception:
                pass
            try:
                await conn.execute(text("PRAGMA incremental_vacuum"))
            except Exception:
                pass
            try:
                await conn.execute(text("PRAGMA optimize"))
            except Exception:
                pass


# Global database manager instance
db_manager = DatabaseManager()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for getting a database session."""
    async with db_manager.session() as session:
        yield session
