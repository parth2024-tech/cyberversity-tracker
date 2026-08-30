"""
Test suite for Audio & Neural Text-To-Speech service and endpoints.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from ai_security_monitor.presentation.api.main import create_app


@pytest.mark.asyncio
async def test_audio_voices_endpoint():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/audio/voices")
        assert resp.status_code == 200
        data = resp.json()
        assert "voices" in data
        assert len(data["voices"]) > 0
        assert data["default"] == "en-US-GuyNeural"


@pytest.mark.asyncio
async def test_audio_tts_get_endpoint():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/audio/tts?text=Test+audio+alert&voice=en-US-GuyNeural")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/mpeg"
        assert len(resp.content) > 1000


@pytest.mark.asyncio
async def test_audio_tts_post_endpoint():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {"text": "AetherGuard intelligence broadcast test.", "voice": "en-US-GuyNeural", "rate": "+0%"}
        resp = await client.post("/api/audio/tts", json=payload)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/mpeg"
        assert len(resp.content) > 1000
