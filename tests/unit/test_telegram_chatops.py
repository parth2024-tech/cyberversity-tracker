"""
Unit tests for Telegram ChatOps (Pillar 6).
Tests two-way inline callbacks, payload limits (<64 bytes), dual-mode transport,
allowed user ID enforcement, undo toggles, and non-blocking deep triage.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.application.services.telegram_chatops_service import (
    TelegramChatOpsService,
    _parse_entry_uuid,
)
from ai_security_monitor.config.settings import settings
from ai_security_monitor.domain.entities import Analysis, Category, Entry
from ai_security_monitor.infrastructure.analyzers.embedding_service import (
    EmbeddingService,
)
from ai_security_monitor.infrastructure.delivery.telegram_delivery import (
    TelegramDelivery,
    build_entry_inline_keyboard,
)
from ai_security_monitor.presentation.api.main import create_app


@pytest.fixture
def test_entry() -> Entry:
    return Entry(
        id=UUID("12345678-1234-5678-1234-567812345678"),
        source_id=uuid4(),
        title="DeepSeek-R1 Architecture Open Weights Release",
        url="https://arxiv.org/abs/2501.12948",
        content_hash="b" * 64,
        summary="DeepSeek releases open reasoning model weights and paper.",
        published_at=datetime.now(UTC),
        category=Category.AI_MODELS,
        tags=["deepseek", "reasoning", "open-source"],
    )


def test_parse_entry_uuid():
    """Verify parsing valid and invalid 32-hex UUID strings."""
    valid_uuid = UUID("abcdef01-2345-6789-abcd-ef0123456789")
    assert _parse_entry_uuid("abcdef0123456789abcdef0123456789") == valid_uuid
    assert _parse_entry_uuid("abcdef01-2345-6789-abcd-ef0123456789") == valid_uuid
    assert _parse_entry_uuid("invalid-hex-too-short") is None
    assert _parse_entry_uuid("z" * 32) is None


def test_build_entry_inline_keyboard_payload_limits(test_entry: Entry):
    """Ensure all callback_data payloads are strictly under Telegram's 64-byte limit."""
    # Standard states
    kb = build_entry_inline_keyboard(
        entry_id=test_entry.id,
        source_id="huggingface_daily_papers",
        is_vaulted=False,
        is_dismissed=False,
        is_muted=False,
        is_analyzing=False,
    )
    for row in kb["inline_keyboard"]:
        for btn in row:
            cb_data = btn["callback_data"]
            assert len(cb_data.encode("utf-8")) < 64, (
                f"Payload exceeded 64 bytes: {cb_data}"
            )

    # Vaulted & Muted states
    kb_toggled = build_entry_inline_keyboard(
        entry_id=test_entry.id,
        source_id="huggingface_daily_papers",
        is_vaulted=True,
        is_dismissed=True,
        is_muted=True,
        is_analyzing=True,
    )
    for row in kb_toggled["inline_keyboard"]:
        for btn in row:
            cb_data = btn["callback_data"]
            assert len(cb_data.encode("utf-8")) < 64, (
                f"Toggled payload exceeded 64 bytes: {cb_data}"
            )


def test_build_entry_inline_keyboard_ultra_long_source_slug(test_entry: Entry):
    """Ensure ultra-long source slugs are hashed to prevent exceeding 64 bytes."""
    long_source = "very_long_source_organization_name_with_lots_of_nested_subcategories_and_special_trackers_2026"
    kb = build_entry_inline_keyboard(
        entry_id=test_entry.id,
        source_id=long_source,
    )
    mute_button = kb["inline_keyboard"][1][1]
    assert mute_button["callback_data"].startswith("m:")
    assert len(mute_button["callback_data"].encode("utf-8")) < 64


@pytest.mark.asyncio
async def test_telegram_delivery_edit_message_text_clamping():
    """Verify that edit_message_text clamps strings longer than 4096 characters."""
    delivery = TelegramDelivery({"bot_token": "fake_token", "chat_id": "-10012345"})

    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"ok": True})
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    huge_text = "<b>Headline</b>\n" + ("x" * 5000)
    with patch("httpx.AsyncClient", return_value=mock_client):
        success = await delivery.edit_message_text(
            chat_id="-10012345",
            message_id=42,
            text=huge_text,
        )

    assert success is True
    assert mock_client.post.called
    sent_payload = mock_client.post.call_args[1]["json"]
    assert len(sent_payload["text"]) <= 4096
    assert "[truncated to Telegram 4096-char limit]" in sent_payload["text"]


@pytest.mark.asyncio
async def test_telegram_webhook_secret_verification():
    """Test webhook endpoint verifies X-Telegram-Bot-Api-Secret-Token correctly."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Case 1: No secret configured in settings -> allows call
        with patch.object(settings.delivery, "telegram_webhook_secret", ""):
            resp = await client.post("/api/telegram/webhook", json={"update_id": 1})
            assert resp.status_code == 200

        # Case 2: Secret configured, missing header -> 403 Forbidden
        with patch.object(
            settings.delivery, "telegram_webhook_secret", "super_secret_token_xyz"
        ):
            resp = await client.post("/api/telegram/webhook", json={"update_id": 2})
            assert resp.status_code == 403
            assert "Invalid Telegram webhook secret token" in resp.json()["detail"]

            # Case 3: Secret configured, wrong header -> 403 Forbidden
            resp = await client.post(
                "/api/telegram/webhook",
                json={"update_id": 3},
                headers={"X-Telegram-Bot-Api-Secret-Token": "wrong_secret"},
            )
            assert resp.status_code == 403

            # Case 4: Secret configured, valid header -> 200 OK
            with patch(
                "ai_security_monitor.presentation.api.routers.telegram.telegram_chatops_service.handle_update",
                new_callable=AsyncMock,
            ) as mock_handle:
                mock_handle.return_value = {"handled": True}
                resp = await client.post(
                    "/api/telegram/webhook",
                    json={"update_id": 4},
                    headers={
                        "X-Telegram-Bot-Api-Secret-Token": "super_secret_token_xyz"
                    },
                )
                assert resp.status_code == 200
                assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_telegram_chatops_status_endpoint():
    """Test GET /api/telegram/status returns current telemetry."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/telegram/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert "mode" in data
        assert "polling_active" in data
        assert "last_update_id" in data


@pytest.mark.asyncio
async def test_telegram_callback_unauthorized_user():
    """Verify unauthorized Telegram user cannot trigger actions when allowed_user_id is configured."""
    mock_delivery = MagicMock(spec=TelegramDelivery)
    mock_delivery.answer_callback_query = AsyncMock(return_value=True)

    service = TelegramChatOpsService(delivery=mock_delivery)

    with patch.object(settings.delivery, "telegram_allowed_user_id", "12345678"):
        callback_query = {
            "id": "cb_query_99",
            "from": {"id": 99999999, "username": "intruder"},
            "data": "v:12345678123456781234567812345678",
            "message": {"message_id": 101, "chat": {"id": -100123}},
        }
        res = await service.handle_callback_query(callback_query)
        assert res.get("status") == "unauthorized"
        mock_delivery.answer_callback_query.assert_called_once_with(
            "cb_query_99",
            text="⛔ Unauthorized: Actions restricted to tracker owner.",
            show_alert=True,
        )


@pytest.mark.asyncio
async def test_telegram_vault_and_undo_actions(test_entry: Entry):
    """Test Vault (v:) and Undo Vault (uv:) inline callback flows."""
    mock_delivery = MagicMock(spec=TelegramDelivery)
    mock_delivery.answer_callback_query = AsyncMock(return_value=True)
    mock_delivery.edit_message_reply_markup = AsyncMock(return_value=True)

    service = TelegramChatOpsService(delivery=mock_delivery)

    mock_entry_repo = MagicMock()
    mock_entry_repo.get = AsyncMock(return_value=test_entry)
    mock_entry_repo.toggle_importance = AsyncMock(return_value=True)

    mock_uow = MagicMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)
    mock_uow.entries = mock_entry_repo
    mock_uow.commit = AsyncMock()

    with (
        patch(
            "ai_security_monitor.application.services.telegram_chatops_service.SqlAlchemyUnitOfWork",
            return_value=mock_uow,
        ),
        patch(
            "ai_security_monitor.application.services.telegram_chatops_service.vault_feedback_service.refresh_profile",
            new_callable=AsyncMock,
        ) as mock_refresh,
    ):
        # 1. Action: Vault
        cb_vault = {
            "id": "cb_vault_1",
            "from": {"id": 111},
            "data": f"v:{test_entry.id.hex}",
            "message": {"message_id": 201, "chat": {"id": -100123}},
        }
        res_v = await service.handle_callback_query(cb_vault)
        assert res_v["action"] == "vault"
        assert res_v["status"] == "success"
        mock_refresh.assert_called_once()
        mock_delivery.answer_callback_query.assert_called_with(
            "cb_vault_1",
            text="⭐ Saved to Vault & interest vector updated!",
        )

        # 2. Action: Undo Vault
        mock_refresh.reset_mock()
        cb_unvault = {
            "id": "cb_unvault_1",
            "from": {"id": 111},
            "data": f"uv:{test_entry.id.hex}",
            "message": {"message_id": 201, "chat": {"id": -100123}},
        }
        res_uv = await service.handle_callback_query(cb_unvault)
        assert res_uv["action"] == "unvault"
        assert res_uv["status"] == "success"
        mock_refresh.assert_called_once()
        mock_delivery.answer_callback_query.assert_called_with(
            "cb_unvault_1",
            text="↩️ Unvaulted & interest vector updated!",
        )


@pytest.mark.asyncio
async def test_telegram_dismiss_and_undo_actions(test_entry: Entry):
    """Test Dismiss (x:) and Undo Dismiss (ux:) inline callback flows."""
    mock_delivery = MagicMock(spec=TelegramDelivery)
    mock_delivery.answer_callback_query = AsyncMock(return_value=True)
    mock_delivery.edit_message_reply_markup = AsyncMock(return_value=True)

    service = TelegramChatOpsService(delivery=mock_delivery)

    mock_entry_repo = MagicMock()
    mock_entry_repo.get = AsyncMock(return_value=test_entry)
    mock_entry_repo.delete = AsyncMock(return_value=True)
    mock_entry_repo.restore_entry = AsyncMock(return_value=True)

    mock_uow = MagicMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)
    mock_uow.entries = mock_entry_repo
    mock_uow.commit = AsyncMock()

    with (
        patch(
            "ai_security_monitor.application.services.telegram_chatops_service.SqlAlchemyUnitOfWork",
            return_value=mock_uow,
        ),
        patch(
            "ai_security_monitor.application.services.telegram_chatops_service.vault_feedback_service.refresh_profile",
            new_callable=AsyncMock,
        ) as mock_refresh,
    ):
        # 1. Action: Dismiss
        cb_dismiss = {
            "id": "cb_x_1",
            "from": {"id": 111},
            "data": f"x:{test_entry.id.hex}",
            "message": {"message_id": 202, "chat": {"id": -100123}},
        }
        res_x = await service.handle_callback_query(cb_dismiss)
        assert res_x["action"] == "dismiss"
        assert res_x["status"] == "success"
        mock_entry_repo.delete.assert_called_once_with(test_entry.id, hard_delete=False)
        mock_refresh.assert_called_once()

        # 2. Action: Undo Dismiss
        mock_refresh.reset_mock()
        cb_undismiss = {
            "id": "cb_ux_1",
            "from": {"id": 111},
            "data": f"ux:{test_entry.id.hex}",
            "message": {"message_id": 202, "chat": {"id": -100123}},
        }
        res_ux = await service.handle_callback_query(cb_undismiss)
        assert res_ux["action"] == "undismiss"
        assert res_ux["status"] == "success"
        mock_entry_repo.restore_entry.assert_called_once_with(test_entry.id)
        mock_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_telegram_mute_and_unmute_source():
    """Test Mute (m:) and Unmute (um:) source toggling."""
    mock_delivery = MagicMock(spec=TelegramDelivery)
    mock_delivery.answer_callback_query = AsyncMock(return_value=True)
    mock_delivery.edit_message_reply_markup = AsyncMock(return_value=True)

    service = TelegramChatOpsService(delivery=mock_delivery)

    mock_source_repo = MagicMock()
    mock_source_repo.toggle_enabled = AsyncMock(return_value=True)

    mock_uow = MagicMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)
    mock_uow.sources = mock_source_repo
    mock_uow.commit = AsyncMock()

    with patch(
        "ai_security_monitor.application.services.telegram_chatops_service.SqlAlchemyUnitOfWork",
        return_value=mock_uow,
    ):
        # Mute
        cb_mute = {
            "id": "cb_m_1",
            "from": {"id": 111},
            "data": "m:arxiv_daily_ai",
            "message": {"message_id": 203, "chat": {"id": -100123}},
        }
        res_m = await service.handle_callback_query(cb_mute)
        assert res_m["action"] == "mute"
        assert res_m["status"] == "success"
        mock_source_repo.toggle_enabled.assert_called_with(
            "arxiv_daily_ai", enabled=False
        )

        # Unmute
        cb_unmute = {
            "id": "cb_um_1",
            "from": {"id": 111},
            "data": "um:arxiv_daily_ai",
            "message": {"message_id": 203, "chat": {"id": -100123}},
        }
        res_um = await service.handle_callback_query(cb_unmute)
        assert res_um["action"] == "unmute"
        assert res_um["status"] == "success"
        mock_source_repo.toggle_enabled.assert_called_with(
            "arxiv_daily_ai", enabled=True
        )


@pytest.mark.asyncio
async def test_telegram_deep_triage_immediate_answer_and_background_worker(
    test_entry: Entry,
):
    """Verify d: triggers immediate callback answer and runs async in-place edit."""
    mock_delivery = MagicMock(spec=TelegramDelivery)
    mock_delivery.answer_callback_query = AsyncMock(return_value=True)
    mock_delivery.edit_message_reply_markup = AsyncMock(return_value=True)
    mock_delivery.edit_message_text = AsyncMock(return_value=True)

    service = TelegramChatOpsService(delivery=mock_delivery)

    mock_entry_repo = MagicMock()
    mock_entry_repo.get = AsyncMock(return_value=test_entry)

    mock_analysis_repo = MagicMock()
    mock_analysis_repo.get_by_entry = AsyncMock(return_value=None)
    mock_analysis_repo.add = AsyncMock(return_value=None)
    mock_analysis_repo.update = AsyncMock(return_value=None)

    mock_uow = MagicMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)
    mock_uow.entries = mock_entry_repo
    mock_uow.analysis = mock_analysis_repo
    mock_uow.commit = AsyncMock()

    analysis_res = Analysis(
        id=uuid4(),
        entry_id=test_entry.id,
        attack_vector="Open-source Frontier Reasoning",
        risk_assessment="High market disruption and zero-cost local inference viability",
        mitigation="Host locally via vLLM / Ollama",
        threat_velocity=88,
        severity_index=92,
    )

    mock_deep_service = MagicMock()
    mock_deep_service.analyze_entry = AsyncMock(return_value=analysis_res)

    with (
        patch(
            "ai_security_monitor.application.services.telegram_chatops_service.SqlAlchemyUnitOfWork",
            return_value=mock_uow,
        ),
        patch(
            "ai_security_monitor.infrastructure.analyzers.heuristic_analyzer.HeuristicAnalyzer.analyze",
            new_callable=AsyncMock,
            return_value=analysis_res,
        ),
    ):
        cb_deep = {
            "id": "cb_d_1",
            "from": {"id": 111},
            "data": f"d:{test_entry.id.hex}",
            "message": {
                "message_id": 204,
                "chat": {"id": -100123},
                "text": "<b>DeepSeek-R1 Architecture Open Weights Release</b>\nhttps://arxiv.org/abs/2501.12948",
            },
        }

        # Handle callback query
        res = await service.handle_callback_query(cb_deep)
        assert res["action"] == "deep_triage"
        assert res["status"] == "enqueued"

        # Immediate toast response
        mock_delivery.answer_callback_query.assert_called_with(
            "cb_d_1",
            text="🔍 Running Deep Analysis via Ollama...",
        )

        # Allow background task to complete
        await asyncio.sleep(0.05)

        # Verify in-place edit was called with epistemic verdict
        assert mock_delivery.edit_message_text.called
        call_kwargs = mock_delivery.edit_message_text.call_args[1]
        assert call_kwargs["chat_id"] == -100123
        assert call_kwargs["message_id"] == 204
        assert "Epistemic Analysis Verdict" in call_kwargs["text"]
        assert "High market disruption" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_telegram_polling_lifecycle_and_delete_webhook_conflict_guard():
    """Verify start_polling invokes delete_webhook first to prevent 409 Conflict, then processes updates."""
    mock_delivery = MagicMock(spec=TelegramDelivery)
    mock_delivery.delete_webhook = AsyncMock(return_value=True)
    # First call returns 1 update, subsequent call raises CancelledError
    updates = [
        {
            "update_id": 105,
            "callback_query": {
                "id": "q1",
                "from": {"id": 1},
                "data": "noop",
                "message": {"message_id": 1, "chat": {"id": 1}},
            },
        }
    ]
    mock_delivery.get_updates = AsyncMock(
        side_effect=[updates, asyncio.CancelledError()]
    )

    service = TelegramChatOpsService(delivery=mock_delivery)
    service.handle_update = AsyncMock(return_value={"ok": True})

    with patch.object(settings.delivery, "telegram_bot_token", "123456:ABC-DEF"):
        await service.start_polling()
        assert service._polling_active is True
        # Give loop a brief moment to cycle
        await asyncio.sleep(0.05)

        mock_delivery.delete_webhook.assert_called_once_with(drop_pending_updates=False)
        service.handle_update.assert_called_with(updates[0])
        assert service._last_update_id == 105

        await service.stop_polling()
        assert service._polling_active is False


def test_embedding_service_is_fallback_property():
    """Ensure is_fallback property correctly flags ONNX model availability."""
    emb_fallback = EmbeddingService(use_fallback_only=True)
    assert emb_fallback.is_fallback is True

    emb_default = EmbeddingService()
    assert hasattr(emb_default, "is_fallback")
    assert isinstance(emb_default.is_fallback, bool)
