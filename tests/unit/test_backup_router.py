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


@pytest.mark.asyncio
async def test_backup_export_large_vault_over_250_entries():
    """Verify that export does not truncate when vault exceeds 250 entries."""
    from datetime import UTC, datetime

    import httpx

    from ai_security_monitor.domain.entities import Category, Entry, Source, SourceType
    from ai_security_monitor.infrastructure.database.unit_of_work import (
        SqlAlchemyUnitOfWork,
    )

    src_id = uuid.uuid4()
    async with SqlAlchemyUnitOfWork() as uow:
        src = Source(
            id=src_id,
            name=f"Vault Scale Source {src_id}",
            url=f"https://test.scale.org/feed-{src_id}",
            type=SourceType.RSS,
            category=Category.AI_RESEARCH,
        )
        await uow.sources.add(src)

        for i in range(260):
            entry = Entry(
                id=uuid.uuid4(),
                source_id=src_id,
                title=f"Large Vault Entry #{i:03d}",
                url=f"https://test.scale.org/item-{src_id}-{i:03d}",
                content_hash=f"hash_scale_{src_id}_{i:03d}",
                summary=f"Technical summary for scale test #{i}",
                category=Category.AI_RESEARCH,
                published_at=datetime.now(UTC),
                metadata={
                    "is_important": True,
                    "vaulted_at": datetime.now(UTC).isoformat(),
                },
            )
            await uow.entries.add(entry)
        await uow.commit()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/backup/export")
        assert response.status_code == 200
        data = response.json()
        assert len(data["vault_entries"]) >= 260
        assert data["summary"]["total_vaulted"] >= 260
