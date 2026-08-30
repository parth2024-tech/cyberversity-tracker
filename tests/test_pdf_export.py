"""
Test suite for PDF Export Service and Entries PDF Export Endpoints.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from ai_security_monitor.application.services.pdf_export_service import PdfExportService
from ai_security_monitor.presentation.api.main import create_app


def test_pdf_export_service_dossier():
    sample_entries = [
        {
            "id": "test-id-1",
            "title": "Critical RAG Poisoning Vulnerability in LangChain",
            "source_name": "NVD Vulnerabilities",
            "category": "vulnerabilities",
            "published_at": "2026-08-30T10:00:00",
            "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-9999",
            "analysis": {
                "threat_velocity": 92,
                "severity_index": 88,
                "blast_radius_score": 85,
                "attack_vector": "Prompt injection payload in document embeddings",
                "risk_assessment": "Complete integrity loss of agent outputs",
                "mitigation": "Upgrade LangChain to >= 0.3.15 and enable embedding verification",
                "affected_ecosystem": ["LangChain", "ChromaDB", "OpenAI"],
                "is_pre_cve_warning": True,
            }
        },
        {
            "id": "test-id-2",
            "title": "Model Inversion Attack on Local Ollama GPU Endpoints",
            "source_name": "arXiv Pre-CVE",
            "category": "ai_research",
            "published_at": "2026-08-30T11:00:00",
            "url": "https://arxiv.org/abs/2608.12345",
            "analysis": {
                "threat_velocity": 75,
                "severity_index": 65,
                "blast_radius_score": 60,
                "attack_vector": "Logit gradient reconstruction",
                "risk_assessment": "Training data reconstruction from weights",
                "mitigation": "Enable differential privacy in training loop",
                "affected_ecosystem": ["Ollama", "PyTorch"],
                "is_pre_cve_warning": False,
            }
        }
    ]

    pdf_bytes = PdfExportService.generate_dossier_pdf(
        entries=sample_entries,
        title="Test Threat Dossier",
        subtitle="Unit Test Dossier"
    )

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 2000
    assert pdf_bytes.startswith(b"%PDF-")


@pytest.mark.asyncio
async def test_api_entries_export_pdf_get():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/entries/export/pdf?limit=5")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert "Content-Disposition" in resp.headers
        assert resp.content.startswith(b"%PDF-")
        assert len(resp.content) > 1000


@pytest.mark.asyncio
async def test_api_entries_export_pdf_post():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "ids": ["dummy-id-1", "dummy-id-2"],
            "title": "Custom Investigation Pinboard Dossier",
            "subtitle": "Test Scoped Export"
        }
        resp = await client.post("/api/entries/export/pdf", json=payload)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content.startswith(b"%PDF-")
        assert len(resp.content) > 1000
