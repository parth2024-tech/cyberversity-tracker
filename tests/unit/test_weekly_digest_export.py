"""
Unit tests for Weekly Digest Export Service (Workstream C2).
Tests explicit user bookmarks filtering, 14-day freshness clamp, explicit timezone rendering,
multi-format export (Markdown, HTML, PDF), REST API endpoints, and MCP server tool.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ai_security_monitor.application.services.weekly_digest_export_service import (
    MAX_DIGEST_AGE_DAYS,
    WeeklyDigestExportService,
)
from ai_security_monitor.infrastructure.database.models import (
    EntryModel,
    SourceModel,
)
from ai_security_monitor.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from ai_security_monitor.presentation.api.main import create_app
from ai_security_monitor.presentation.mcp.server import MCPServer


@pytest.mark.asyncio
async def test_explicit_user_saves_vs_automated_landmarks():
    """
    Verify that only explicitly saved entries (is_user_saved=True) appear in user_saves,
    while automatic landmark-tagged entries (is_important=True, is_user_saved=False) are excluded from bookmarks.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        svc = WeeklyDigestExportService(output_dir=Path(tmp_dir))

        source_id = uuid4()
        user_saved_id = uuid4()
        automated_landmark_id = uuid4()
        stale_id = uuid4()

        async with SqlAlchemyUnitOfWork() as uow:
            src = SourceModel(
                id=str(source_id),
                name="weekly_test_source",
                category="ai_research",
                type="arxiv",
                rate_limit_seconds=60,
            )
            uow.session.add(src)

            # 1. Explicit user bookmark
            user_saved = EntryModel(
                id=str(user_saved_id),
                source_id=str(source_id),
                title="DeepSeek-R1 Reasoning Architecture Checkpoint",
                url="https://arxiv.org/abs/2501.12948",
                content_hash="user_saved_hash_1234" * 4,
                summary="Full open-weights release of DeepSeek-R1 with GRPO reinforcement learning.",
                category="ai_research",
                published_at=datetime.now(UTC) - timedelta(days=2),
                is_user_saved=True,
                extra_metadata={
                    "is_important": True,
                    "is_user_saved": True,
                    "importance_reason": "Groundbreaking open reasoning weights",
                },
            )
            uow.session.add(user_saved)

            # 2. Automated landmark (simulating monitor_service automatic tagging: is_important=True, but NOT user saved)
            automated = EntryModel(
                id=str(automated_landmark_id),
                source_id=str(source_id),
                title="High Velocity Automatic Landmark Analysis",
                url="https://github.com/vllm-project/vllm",
                content_hash="automated_landmark_1234" * 4,
                summary="vLLM high throughput inference engine update.",
                category="cyber_tools",
                published_at=datetime.now(UTC) - timedelta(days=3),
                is_user_saved=False,
                extra_metadata={
                    "is_important": True,  # Automated landmark
                    "importance_reason": "High-velocity automated tag",
                },
            )
            uow.session.add(automated)

            # 3. Stale entry (> 14 days old) to verify freshness guard
            stale = EntryModel(
                id=str(stale_id),
                source_id=str(source_id),
                title="Stale Historical Research Paper From Last Month",
                url="https://arxiv.org/abs/2401.00001",
                content_hash="stale_history_hash_1234" * 4,
                summary="Historical research paper published well outside freshness window.",
                category="ai_research",
                published_at=datetime.now(UTC) - timedelta(days=25),
                is_user_saved=True,
            )
            uow.session.add(stale)
            await uow.commit()

        # Compile weekly digest
        digest = await svc.compile_weekly_digest(
            days=7, timezone_str="America/New_York"
        )

        user_saves = digest["sections"]["user_saves"]
        user_save_ids = [item["id"] for item in user_saves]

        # Explicit user save must be present in user_saves section
        assert str(user_saved_id) in user_save_ids
        # Automated landmark must NOT be in user_saves section
        assert str(automated_landmark_id) not in user_save_ids
        # Stale entry (>14 days) must NOT be present anywhere
        all_ids = [
            item["id"] for items in digest["sections"].values() for item in items
        ]
        assert str(stale_id) not in all_ids


@pytest.mark.asyncio
async def test_freshness_clamp_and_explicit_timezone():
    """Verify that days parameter is strictly clamped to 14 days and timezone is formatted cleanly."""
    svc = WeeklyDigestExportService()

    # 1. Freshness Clamp: request 30 days -> clamped to MAX_DIGEST_AGE_DAYS (14)
    digest_clamped = await svc.compile_weekly_digest(
        days=30, timezone_str="Asia/Kolkata"
    )
    assert digest_clamped["period_days"] == MAX_DIGEST_AGE_DAYS
    assert digest_clamped["timezone"] == "Asia/Kolkata"
    assert (
        "IST" in digest_clamped["generated_at_local"]
        or "+0530" in digest_clamped["generated_at_local"]
    )

    # 2. Invalid timezone fallback to UTC
    digest_invalid_tz = await svc.compile_weekly_digest(
        days=7, timezone_str="Invalid/Nonexistent_Zone"
    )
    assert digest_invalid_tz["timezone"] == "UTC"
    assert "UTC" in digest_invalid_tz["generated_at_local"]


@pytest.mark.asyncio
async def test_multi_format_export_and_archival():
    """Verify Markdown, HTML, and ReportLab PDF compilation and local disk archival."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        output_dir = Path(tmp_dir)
        svc = WeeklyDigestExportService(output_dir=output_dir)

        # Build sample data payload
        sample_data = {
            "title": "AETHERGUARD Worldwide AI Intelligence Digest",
            "period_days": 7,
            "timezone": "America/New_York",
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "generated_at_local": "November 01, 2026 • 12:00 EDT",
            "period_start_local": "October 25, 2026",
            "period_end_local": "November 01, 2026",
            "user_saved_count": 1,
            "total_breakthroughs": 2,
            "include_user_saves_only": False,
            "sections": {
                "user_saves": [
                    {
                        "id": str(uuid4()),
                        "title": "Qwen 2.5 Coder 32B Open Release",
                        "url": "https://github.com/QwenLM/Qwen2.5-Coder",
                        "category": "ai_models",
                        "summary": "State-of-the-art open coding model achieving 65.4% on SWE-bench.",
                        "published_at_local": "Oct 29, 2026",
                        "velocity": 92,
                        "tags": ["code", "qwen", "weights"],
                        "action_summary": "Deploy in sandbox runtime and evaluate code generation.",
                        "importance_reason": "Top open-weights code model",
                        "is_user_saved": True,
                    }
                ],
                "frontier_models": [
                    {
                        "id": str(uuid4()),
                        "title": "DeepSeek-V3 MoE Architecture Paper",
                        "url": "https://arxiv.org/abs/2412.19437",
                        "category": "ai_models",
                        "summary": "Multi-head latent attention (MLA) and DeepSeekMoE architecture benchmarks.",
                        "published_at_local": "Oct 28, 2026",
                        "velocity": 88,
                        "tags": ["moe", "deepseek"],
                        "action_summary": None,
                        "importance_reason": None,
                        "is_user_saved": False,
                    }
                ],
                "developer_infrastructure": [],
                "research_papers": [],
                "trending_repos": [],
                "sovereign_ai": [],
            },
            "top_entities": [
                {
                    "entity_type": "model",
                    "name": "qwen-2.5-coder",
                    "display_name": "Qwen 2.5 Coder",
                    "mentions": 12,
                }
            ],
        }

        # 1. Render Markdown
        md = svc.render_markdown(sample_data)
        assert "---" in md
        assert 'title: "AETHERGUARD Worldwide AI Intelligence Digest"' in md
        assert "## ⭐ User Bookmarks & Saved Intel (1)" in md
        assert "Qwen 2.5 Coder 32B Open Release" in md
        assert "https://github.com/QwenLM/Qwen2.5-Coder" in md
        assert "Top open-weights code model" in md

        # 2. Render HTML
        html = svc.render_html(sample_data)
        assert "<!DOCTYPE html>" in html
        assert "AETHERGUARD Worldwide AI Intelligence Digest" in html
        assert "user-save-card" in html
        assert "Qwen 2.5 Coder 32B Open Release" in html
        # Anti-vibe-coding: no purple-to-indigo gradient slop
        assert "gradient" not in html.lower() or "linear-gradient(#9333ea" not in html

        # 3. Render PDF
        pdf_bytes = svc.render_pdf(sample_data)
        assert len(pdf_bytes) > 500
        assert pdf_bytes.startswith(b"%PDF")

        # 4. Archival: export_and_archive
        result = await svc.export_and_archive(days=7, timezone_str="America/New_York")
        assert result["status"] == "success"
        assert Path(result["files"]["markdown"]).exists()
        assert Path(result["files"]["html"]).exists()
        assert Path(result["files"]["pdf"]).exists()


@pytest.mark.asyncio
async def test_weekly_digest_rest_api():
    """Verify REST API /api/digest/weekly/preview, /api/digest/weekly/export, and /api/digest/weekly/archive."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Preview
        res_prev = await client.get("/api/digest/weekly/preview?days=7")
        assert res_prev.status_code == 200
        prev_data = res_prev.json()
        assert "title" in prev_data
        assert "sections_summary" in prev_data

        # 2. Export Markdown
        res_md = await client.get("/api/digest/weekly/export?format=markdown&days=7")
        assert res_md.status_code == 200
        assert "text/markdown" in res_md.headers["content-type"]
        assert "# AETHERGUARD" in res_md.text

        # 3. Export HTML
        res_html = await client.get("/api/digest/weekly/export?format=html&days=7")
        assert res_html.status_code == 200
        assert "text/html" in res_html.headers["content-type"]
        assert "<!DOCTYPE html>" in res_html.text

        # 4. Export PDF
        res_pdf = await client.get("/api/digest/weekly/export?format=pdf&days=7")
        assert res_pdf.status_code == 200
        assert "application/pdf" in res_pdf.headers["content-type"]
        assert res_pdf.content.startswith(b"%PDF")

        # 5. Archive
        res_arch = await client.post("/api/digest/weekly/archive?days=7")
        assert res_arch.status_code == 200
        arch_data = res_arch.json()
        assert arch_data["status"] == "success"
        assert "files" in arch_data


@pytest.mark.asyncio
async def test_mcp_export_weekly_digest_tool():
    """Verify that MCP server exposes and executes export_weekly_digest."""
    server = MCPServer()

    # 1. Verify tool exists in tools/list
    list_req = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    list_res = await server.handle_request(list_req)
    assert list_res is not None
    tool_names = [t["name"] for t in list_res["result"]["tools"]]
    assert "export_weekly_digest" in tool_names

    # 2. Call export_weekly_digest
    call_req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "export_weekly_digest",
            "arguments": {
                "days": 7,
                "format": "markdown",
                "timezone": "America/New_York",
            },
        },
    }
    call_res = await server.handle_request(call_req)
    assert call_res is not None
    assert "result" in call_res
    text_content = call_res["result"]["content"][0]["text"]
    assert "AETHERGUARD" in text_content
    assert "Coverage Window" in text_content
