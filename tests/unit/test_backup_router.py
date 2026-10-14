"""Unit tests for Backup and Portability router."""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_security_monitor.infrastructure.database.connection import db_manager
from ai_security_monitor.presentation.api.routers.backup import backup_router

app = FastAPI()
app.include_router(backup_router, prefix="/api")
client = TestClient(app)


@pytest.fixture(autouse=True)
async def init_test_db():
    await db_manager.init_db()
    yield
    await db_manager.close()


def test_backup_export():
    response = client.get("/api/backup/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    data = response.json()
    assert data["format"] == "aetherguard-intelligence-backup"
    assert "vault_entries" in data
    assert "sources" in data


def test_backup_import():
    uid = str(uuid.uuid4())
    payload = {
        "version": "2.0.0",
        "vault_entries": [
            {
                "id": uid,
                "title": f"Imported Test Intelligence: DeepSeek R1 {uid}",
                "url": f"https://example.com/deepseek-r1-deploy-{uid}",
                "summary": "Deployment guide for DeepSeek R1 reasoning model.",
                "category": "ai_research",
                "tags": ["deepseek", "reasoning"],
            }
        ],
    }

    response = client.post("/api/backup/import", json=payload)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "success"
    assert res_data["imported"] >= 1
