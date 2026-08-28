"""
Unit and integration tests for the 5-Hour Autonomous Newspaper Document Service.
"""
from datetime import datetime, timedelta
from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

from ai_security_monitor.application.services.newspaper_service import NewspaperService
from ai_security_monitor.domain.entities import Analysis, AnalysisModel, Category, Entry
from ai_security_monitor.presentation.api.main import app


@pytest.fixture
def temp_output_dir(tmp_path: Path) -> Path:
    newspaper_dir = tmp_path / "newspapers"
    newspaper_dir.mkdir(parents=True, exist_ok=True)
    return newspaper_dir


@pytest.mark.asyncio
async def test_newspaper_generation_creates_files(temp_output_dir: Path):
    """Test that generate_edition produces .md, .html, and .json files."""
    service = NewspaperService(output_dir=temp_output_dir)
    meta = await service.generate_edition(window_hours=5)

    assert meta["edition_number"] >= 100
    assert "The Cyber Intelligence Chronicle" in meta["title"]
    assert meta["total_threats"] >= 0

    edition_id = meta["edition_id"]
    md_file = temp_output_dir / f"{edition_id}.md"
    html_file = temp_output_dir / f"{edition_id}.html"
    json_file = temp_output_dir / f"{edition_id}.json"
    latest_md = temp_output_dir / "latest.md"
    latest_html = temp_output_dir / "latest.html"
    latest_json = temp_output_dir / "latest.json"

    assert md_file.exists()
    assert html_file.exists()
    assert json_file.exists()
    assert latest_md.exists()
    assert latest_html.exists()
    assert latest_json.exists()

    md_content = md_file.read_text(encoding="utf-8")
    assert "THE CYBER INTELLIGENCE CHRONICLE" in md_content
    assert "CISO EXECUTIVE INTELLIGENCE BRIEF" in md_content

    html_content = html_file.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html_content
    assert "The Cyber Intelligence Chronicle" in html_content
    assert "DEFCON 3 (ELEVATED)" in html_content


@pytest.mark.asyncio
async def test_newspaper_service_getters_and_listing(temp_output_dir: Path):
    """Test get_latest_edition, get_latest_html, and list_editions."""
    service = NewspaperService(output_dir=temp_output_dir)
    await service.generate_edition(window_hours=5)

    latest = service.get_latest_edition()
    assert latest is not None
    assert "edition_number" in latest
    assert "markdown" in latest
    assert latest["has_html"] is True

    html = service.get_latest_html()
    assert html is not None
    assert "AETHERGUARD" in html

    editions = service.list_editions()
    assert len(editions) >= 1
    assert editions[0]["edition_id"] == latest["edition_id"]


@pytest.mark.asyncio
async def test_newspaper_api_endpoints():
    """Test all /api/newspaper REST endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. GET latest metadata & markdown
        res_latest = await client.get("/api/newspaper/latest")
        assert res_latest.status_code == 200
        data = res_latest.json()
        assert "edition_number" in data
        assert "markdown" in data

        # 2. GET latest HTML document
        res_html = await client.get("/api/newspaper/latest/html")
        assert res_html.status_code == 200
        assert "text/html" in res_html.headers.get("content-type", "")
        assert "<!DOCTYPE html>" in res_html.text

        # 3. GET download as markdown
        res_dl_md = await client.get("/api/newspaper/download?format=md")
        assert res_dl_md.status_code == 200
        assert "THE CYBER INTELLIGENCE CHRONICLE" in res_dl_md.text

        # 4. GET download as HTML
        res_dl_html = await client.get("/api/newspaper/download?format=html")
        assert res_dl_html.status_code == 200
        assert "<!DOCTYPE html>" in res_dl_html.text

        # 5. GET download as PDF
        res_dl_pdf = await client.get("/api/newspaper/download?format=pdf")
        assert res_dl_pdf.status_code == 200
        assert "application/pdf" in res_dl_pdf.headers.get("content-type", "")

        # 6. GET editions list
        res_editions = await client.get("/api/newspaper/editions")
        assert res_editions.status_code == 200
        assert "editions" in res_editions.json()

        # 7. POST manual trigger generation
        res_gen = await client.post("/api/newspaper/generate", json={"window_hours": 5})
        assert res_gen.status_code == 200
        assert res_gen.json()["status"] == "success"
