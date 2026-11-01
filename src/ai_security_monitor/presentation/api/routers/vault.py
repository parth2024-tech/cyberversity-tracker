"""
Vault API router.
Provides dedicated endpoints for managing pinned, starred, and permanently saved intelligence entries.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ai_security_monitor.core.auth import require_admin_auth
from ai_security_monitor.domain.exceptions import EntityNotFoundError
from ai_security_monitor.domain.repositories import EntryFilters, PaginationParams
from ai_security_monitor.infrastructure.cache import response_cache
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

vault_router = APIRouter(prefix="/vault")


class PinVaultRequest(BaseModel):
    reason: str | None = None


@vault_router.get("")
@vault_router.get("/")
async def list_vault_entries(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
):
    """List all entries permanently pinned/saved in the Vault with pagination."""
    cache_key = f"vault_list_{search}_{limit}_{offset}"

    async def _fetch():
        async with SqlAlchemyUnitOfWork() as uow:
            filters = EntryFilters(
                search=search,
                important_only=True,
            )
            pagination = PaginationParams(limit=limit, offset=offset)
            entries = await uow.entries.list(filters=filters, pagination=pagination)
            total = await uow.entries.count(filters=filters)

            items = []
            for e in entries:
                meta = e.metadata or {}
                items.append(
                    {
                        "id": str(e.id),
                        "title": e.title,
                        "url": e.url,
                        "category": e.category.value
                        if hasattr(e.category, "value")
                        else str(e.category),
                        "is_important": True,
                        "published_at": e.published_at.isoformat()
                        if e.published_at
                        else None,
                        "saved_at": meta.get("saved_at") or meta.get("vaulted_at"),
                        "importance_reason": meta.get("importance_reason"),
                        "metadata": meta,
                    }
                )

            return {
                "total": total,
                "limit": limit,
                "offset": offset,
                "entries": items,
            }

    data = await response_cache.get_or_set(cache_key, 30.0, _fetch)
    return data


@vault_router.post("/{entry_id}")
async def pin_to_vault(
    entry_id: str,
    payload: PinVaultRequest | None = None,
):
    """Pin/star an intelligence entry into the permanent Vault."""
    try:
        uid = UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry UUID")

    reason = payload.reason if payload else None

    async with SqlAlchemyUnitOfWork() as uow:
        try:
            # Explicitly mark important=True
            entry = await uow.entries.get(uid)
            if not entry:
                raise EntityNotFoundError("Entry", entry_id)

            # Explicitly mark important=True
            updated = await uow.entries.toggle_importance(
                uid, is_important=True, reason=reason
            )
            await uow.commit()
        except EntityNotFoundError:
            raise HTTPException(status_code=404, detail="Entry not found")

    response_cache.invalidate_prefix("entries_")
    response_cache.invalidate_prefix("vault_")
    response_cache.invalidate("total_unfiltered_count")

    # Refresh closed-loop Vault profile
    try:
        from ai_security_monitor.application.services.vault_feedback_service import (
            vault_feedback_service,
        )

        await vault_feedback_service.refresh_profile(force=True)
    except Exception:
        pass

    return {
        "status": "success",
        "id": str(updated.id),
        "is_vaulted": True,
        "importance_reason": reason,
        "message": "Entry pinned to Vault",
    }


@vault_router.delete("/{entry_id}")
async def unpin_from_vault(entry_id: str):
    """Unpin/remove an intelligence entry from the permanent Vault."""
    try:
        uid = UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry UUID")

    async with SqlAlchemyUnitOfWork() as uow:
        try:
            entry = await uow.entries.get(uid)
            if not entry:
                raise EntityNotFoundError("Entry", entry_id)

            # Explicitly mark important=False
            updated = await uow.entries.toggle_importance(uid, is_important=False)
            await uow.commit()
        except EntityNotFoundError:
            raise HTTPException(status_code=404, detail="Entry not found")

    response_cache.invalidate_prefix("entries_")
    response_cache.invalidate_prefix("vault_")
    response_cache.invalidate("total_unfiltered_count")

    try:
        from ai_security_monitor.application.services.vault_feedback_service import (
            vault_feedback_service,
        )

        await vault_feedback_service.refresh_profile(force=True)
    except Exception:
        pass

    return {
        "status": "success",
        "id": str(updated.id),
        "is_vaulted": False,
        "message": "Entry removed from Vault",
    }


@vault_router.get("/profile")
async def get_vault_profile():
    """Get active Rocchio personalization vector centroid telemetry and interest profile."""
    from ai_security_monitor.application.services.vault_feedback_service import (
        vault_feedback_service,
    )

    return vault_feedback_service.get_centroid_summary()


@vault_router.post("/profile/refresh")
async def refresh_vault_profile(_admin: bool = Depends(require_admin_auth)):
    """Manually trigger a refresh of the Rocchio personalization vector centroid."""
    from ai_security_monitor.application.services.vault_feedback_service import (
        vault_feedback_service,
    )

    await vault_feedback_service.refresh_profile(force=True)
    return {
        "status": "success",
        "profile": vault_feedback_service.get_centroid_summary(),
        "message": "Successfully refreshed personalization vector centroid.",
    }
