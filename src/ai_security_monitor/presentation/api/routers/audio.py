"""
Audio & Neural Text-To-Speech API Router.
Provides platform-independent, broadcast-grade neural audio streaming
using Microsoft Edge Neural TTS with Google TTS fallback and disk caching.
Eliminates all OS-level speech-dispatcher dependencies.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)

audio_router = APIRouter(prefix="/audio", tags=["Audio"])

# Directory to cache synthesized speech clips
CACHE_DIR = Path("data/audio_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_VOICE = "en-US-GuyNeural"

CURATED_VOICES = [
    {"id": "en-US-GuyNeural", "name": "Guy (US Anchor)", "gender": "Male", "locale": "en-US"},
    {"id": "en-US-ChristopherNeural", "name": "Christopher (US Executive)", "gender": "Male", "locale": "en-US"},
    {"id": "en-US-AriaNeural", "name": "Aria (US Intel Briefer)", "gender": "Female", "locale": "en-US"},
    {"id": "en-US-JennyNeural", "name": "Jenny (US Natural)", "gender": "Female", "locale": "en-US"},
    {"id": "en-GB-SoniaNeural", "name": "Sonia (UK News)", "gender": "Female", "locale": "en-GB"},
    {"id": "en-GB-RyanNeural", "name": "Ryan (UK Broadcast)", "gender": "Male", "locale": "en-GB"},
    {"id": "en-IN-PrabhatNeural", "name": "Prabhat (IN Clear)", "gender": "Male", "locale": "en-IN"},
    {"id": "en-AU-WilliamMultilingualNeural", "name": "William (AU Tactical)", "gender": "Male", "locale": "en-AU"},
]


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="Text to synthesize")
    voice: str = Field(default=DEFAULT_VOICE, description="Voice ID")
    rate: str = Field(default="+0%", description="Speech rate adjustment, e.g. +0%, +25%")


def _get_cache_path(text: str, voice: str, rate: str) -> Path:
    """Generate deterministic file path based on hash of parameters."""
    key = f"{voice}::{rate}::{text}".strip()
    file_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{file_hash}.mp3"


async def _synthesize_edge_tts(text: str, voice: str, rate: str, output_path: Path) -> bool:
    """Synthesize speech using edge-tts."""
    try:
        import edge_tts

        communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
        await communicate.save(str(output_path))
        return output_path.exists() and output_path.stat().st_size > 0
    except Exception as e:
        logger.warning(f"edge-tts synthesis failed, trying fallback: {e}")
        return False


def _synthesize_gtts(text: str, output_path: Path) -> bool:
    """Fallback synthesis using Google TTS."""
    try:
        from gtts import gTTS

        tts = gTTS(text=text, lang="en")
        tts.save(str(output_path))
        return output_path.exists() and output_path.stat().st_size > 0
    except Exception as e:
        logger.error(f"gTTS fallback synthesis failed: {e}")
        return False


async def _generate_audio_file(text: str, voice: str = DEFAULT_VOICE, rate: str = "+0%") -> Path:
    """Check cache or synthesize audio file."""
    output_path = _get_cache_path(text, voice, rate)
    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path

    # Try edge-tts first
    success = await _synthesize_edge_tts(text, voice, rate, output_path)
    if not success:
        # Fallback to gTTS
        success = _synthesize_gtts(text, output_path)

    if not success:
        raise HTTPException(
            status_code=500,
            detail="Speech synthesis failed on all available engines (edge-tts and gTTS).",
        )

    return output_path


@audio_router.get("/voices")
async def list_voices() -> dict[str, Any]:
    """List curated neural voices suitable for security briefings."""
    return {"voices": CURATED_VOICES, "default": DEFAULT_VOICE}


@audio_router.get("/tts")
@audio_router.head("/tts")
async def text_to_speech_get(
    text: str = Query(..., min_length=1, max_length=5000),
    voice: str = Query(DEFAULT_VOICE),
    rate: str = Query("+0%"),
):
    """
    Stream or download synthesized speech MP3.
    Directly playable in HTML5 <audio> tag without speech-dispatcher dependencies.
    """
    path = await _generate_audio_file(text, voice, rate)
    return FileResponse(
        path=path,
        media_type="audio/mpeg",
        filename="speech.mp3",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@audio_router.post("/tts")
async def text_to_speech_post(payload: TTSRequest):
    """
    Synthesize text via POST body (for longer advisories without query-string truncation).
    Returns MP3 audio stream.
    """
    path = await _generate_audio_file(payload.text, payload.voice, payload.rate)
    return FileResponse(
        path=path,
        media_type="audio/mpeg",
        filename="speech.mp3",
        headers={"Cache-Control": "public, max-age=86400"},
    )
