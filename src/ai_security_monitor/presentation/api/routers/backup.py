"""
Backup and Data Portability router for AetherGuard.
Enables exporting vaulted entries, sources, and intelligence state to JSON,
and importing external backup packages safely with schema validation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from ai_security_monitor.core.auth import require_admin_auth
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.domain.entities import Category, Entry, Source, SourceType
from ai_security_monitor.domain.repositories import EntryFilters, PaginationParams
from ai_security_monitor.domain.value_objects import ContentHash
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

logger = get_logger(__name__)

backup_router = APIRouter(prefix="/backup", tags=["Backup & Portability"])


class BackupImportPayload(BaseModel):
    version: str = "2.0.0"
    export_date: str | None = None
    vault_entries: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)


@backup_router.get("/export")
async def export_system_backup() -> Response:
    """Export all pinned Vault entries and registered sources into a standardized portable JSON package."""
    async with SqlAlchemyUnitOfWork() as uow:
        # Retrieve all vaulted (important) entries without arbitrary truncation
        filters = EntryFilters(important_only=True)
        vault_entries: list[Entry] = []
        offset = 0
        batch_size = 200
        while True:
            pagination = PaginationParams(limit=batch_size, offset=offset)
            batch = await uow.entries.list(
                filters=filters,
                pagination=pagination,
            )
            if not batch:
                break
            vault_entries.extend(batch)
            if len(batch) < pagination.limit:
                break
            offset += len(batch)
        sources = await uow.sources.list()

    serialized_vault = []
    for entry in vault_entries:
        serialized_vault.append(
            {
                "id": str(entry.id),
                "source_id": str(entry.source_id),
                "title": entry.title,
                "url": entry.url,
                "summary": entry.summary,
                "category": entry.category.value
                if hasattr(entry.category, "value")
                else str(entry.category),
                "published_at": entry.published_at.isoformat()
                if entry.published_at
                else None,
                "tags": entry.tags or [],
                "metadata": entry.metadata or {},
            }
        )

    serialized_sources = []
    for src in sources:
        serialized_sources.append(
            {
                "id": str(src.id),
                "name": src.name,
                "url": src.url,
                "type": src.type.value if hasattr(src.type, "value") else str(src.type),
                "category": src.category.value
                if hasattr(src.category, "value")
                else str(src.category),
                "enabled": src.enabled,
            }
        )

    backup_data = {
        "format": "aetherguard-intelligence-backup",
        "version": "2.0.0",
        "export_date": datetime.now(UTC).isoformat(),
        "vault_entries": serialized_vault,
        "sources": serialized_sources,
        "summary": {
            "total_vaulted": len(serialized_vault),
            "total_sources": len(serialized_sources),
        },
    }

    content_bytes = json.dumps(backup_data, indent=2).encode("utf-8")
    today_str = datetime.now(UTC).strftime("%Y-%m-%d")
    filename = f"aetherguard-intelligence-backup-{today_str}.json"

    return Response(
        content=content_bytes,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


@backup_router.post("/import")
async def import_system_backup(
    payload: BackupImportPayload,
    _admin: bool = Depends(require_admin_auth),
) -> dict[str, Any]:
    """Import vaulted entries and preferences from an external backup package."""
    imported_count = 0
    skipped_count = 0

    async with SqlAlchemyUnitOfWork() as uow:
        # Retrieve or create fallback source
        sources = await uow.sources.list()
        default_source_id: UUID | None = sources[0].id if sources else None
        if not default_source_id:
            default_src = Source(
                name="Imported Archive",
                category=Category.AI_RESEARCH,
                type=SourceType.RSS,
                url="https://aetherguard.internal/imported",
            )
            created_src = await uow.sources.add(default_src)
            default_source_id = created_src.id

        for item in payload.vault_entries:
            try:
                entry_url = item.get("url")
                if not entry_url:
                    continue

                title = item.get("title", "Imported Intelligence Dispatch")
                content_hash = item.get("content_hash") or str(
                    ContentHash.from_content(f"{title}\n{entry_url}")
                )

                # Check if entry exists by ID or content hash
                existing: Entry | None = None
                item_id = item.get("id")
                if item_id:
                    try:
                        existing = await uow.entries.get(UUID(item_id))
                    except Exception:
                        pass

                if not existing:
                    existing = await uow.entries.get_by_content_hash(content_hash)

                if existing:
                    meta = existing.metadata or {}
                    if not meta.get("is_important"):
                        meta["is_important"] = True
                        meta["vaulted_at"] = datetime.now(UTC).isoformat()
                        existing.metadata = meta
                        await uow.entries.update(existing)
                        imported_count += 1
                    else:
                        skipped_count += 1
                    continue

                # Create new entry from backup
                cat_str = item.get("category", "ai_research")
                try:
                    cat = Category(cat_str)
                except ValueError:
                    cat = Category.AI_RESEARCH

                meta = item.get("metadata") or {}
                meta["is_important"] = True
                meta["vaulted_at"] = (
                    meta.get("vaulted_at") or datetime.now(UTC).isoformat()
                )

                pub_at_str = item.get("published_at")
                pub_at = (
                    datetime.fromisoformat(pub_at_str)
                    if pub_at_str
                    else datetime.now(UTC)
                )

                # Validate foreign key source_id
                target_source_id = default_source_id
                if item.get("source_id"):
                    try:
                        src_candidate = await uow.sources.get(UUID(item["source_id"]))
                        if src_candidate:
                            target_source_id = src_candidate.id
                    except Exception:
                        pass

                new_entry = Entry(
                    id=UUID(item_id) if item_id else uuid4(),
                    source_id=target_source_id,
                    title=title,
                    url=entry_url,
                    content_hash=content_hash,
                    summary=item.get("summary", ""),
                    category=cat,
                    published_at=pub_at,
                    tags=item.get("tags", []),
                    metadata=meta,
                )
                await uow.entries.add(new_entry)
                imported_count += 1

            except Exception as e:
                logger.warning(f"Failed to import backup entry: {e}")
                skipped_count += 1

        await uow.commit()

    return {
        "status": "success",
        "imported": imported_count,
        "skipped": skipped_count,
        "total_in_payload": len(payload.vault_entries),
    }
