"""
Translation API Router.

Provides real-time neural translation endpoints for arbitrary text and intelligence entries.
Automatically detects source languages (Chinese, Russian, Japanese, German, etc.)
and converts them into clear English security advisories.
"""
from __future__ import annotations

from uuid import UUID
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from ai_security_monitor.application.services.translation_service import (
    translation_service,
    LANGUAGE_NAMES,
)
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from ai_security_monitor.infrastructure.cache import response_cache

translation_router = APIRouter(prefix="/translate", tags=["Translation"])


class TranslateTextRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000, description="Text to translate into English")
    target: str = Field(default="en", description="Target language code (defaults to 'en')")


class TranslateTextResponse(BaseModel):
    original: str
    translated: str
    detected_language: str
    detected_language_name: str
    detected_language_flag: str
    is_translated: bool


class BackfillTranslationRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=500, description="Max entries to backfill")


@translation_router.post("", response_model=TranslateTextResponse)
@translation_router.post("/", response_model=TranslateTextResponse)
async def translate_text_endpoint(req: TranslateTextRequest):
    """Translate arbitrary text into English with automatic language detection."""
    trans, lang, is_trans = translation_service.translate_text(req.text, target=req.target)
    name, flag = LANGUAGE_NAMES.get(lang, (lang.upper(), "🌐"))

    return TranslateTextResponse(
        original=req.text,
        translated=trans,
        detected_language=lang,
        detected_language_name=name,
        detected_language_flag=flag,
        is_translated=is_trans,
    )


@translation_router.post("/entry/{entry_id}")
async def translate_entry_endpoint(entry_id: str):
    """Translate a specific database entry into English and persist original text in metadata."""
    try:
        e_uuid = UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry UUID")

    async with SqlAlchemyUnitOfWork() as uow:
        entry = await uow.entries.get(e_uuid)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")

        was_translated = translation_service.translate_entry(entry)
        if was_translated:
            await uow.entries.update(entry)
            await uow.commit()
            response_cache.clear()

        return {
            "id": str(entry.id),
            "title": entry.title,
            "summary": entry.summary,
            "original_title": entry.metadata.get("original_title", entry.title),
            "original_summary": entry.metadata.get("original_summary", entry.summary),
            "detected_language": entry.metadata.get("detected_language", "en"),
            "detected_language_name": entry.metadata.get("detected_language_name", "English"),
            "detected_language_flag": entry.metadata.get("detected_language_flag", "🌐"),
            "is_translated": entry.metadata.get("is_translated", False),
        }


from ai_security_monitor.domain.repositories import PaginationParams


@translation_router.post("/backfill")
async def backfill_translations(req: BackfillTranslationRequest):
    """Backfill translations for existing foreign language entries in the database."""
    translated_count = 0
    async with SqlAlchemyUnitOfWork() as uow:
        entries = await uow.entries.list(pagination=PaginationParams(limit=req.limit, offset=0))
        for entry in entries:
            # Check if entry is not already translated and contains non-English text
            if not entry.metadata.get("is_translated"):
                if translation_service.translate_entry(entry):
                    await uow.entries.update(entry)
                    translated_count += 1

        if translated_count > 0:
            await uow.commit()
            response_cache.clear()

    return {
        "status": "success",
        "processed": len(entries),
        "translated": translated_count,
        "message": f"Successfully translated {translated_count} foreign intelligence entries to English."
    }
