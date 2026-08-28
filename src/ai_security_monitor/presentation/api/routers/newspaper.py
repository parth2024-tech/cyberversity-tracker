"""
Newspaper API router for 5-hour autonomous intelligence broadsheets.
"""
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from ai_security_monitor.application.services.newspaper_service import NewspaperService

newspaper_router = APIRouter(prefix="/newspaper", tags=["Newspaper"])

_newspaper_service = NewspaperService()


class GenerateEditionRequest(BaseModel):
    window_hours: int = 5


@newspaper_router.get("/latest")
async def get_latest_newspaper():
    """Get metadata and markdown content of the latest 5-hour newspaper edition."""
    edition = _newspaper_service.get_latest_edition()
    if not edition:
        # If no edition exists yet on disk, generate one immediately
        edition = await _newspaper_service.generate_edition(window_hours=5)
        edition = _newspaper_service.get_latest_edition()

    if not edition:
        raise HTTPException(status_code=404, detail="No newspaper edition available.")

    return edition


@newspaper_router.get("/latest/html", response_class=HTMLResponse)
async def view_latest_newspaper_html():
    """Render the latest 5-hour newspaper edition directly in browser as print-ready HTML."""
    html_content = _newspaper_service.get_latest_html()
    if not html_content:
        # Generate on-demand if first request
        await _newspaper_service.generate_edition(window_hours=5)
        html_content = _newspaper_service.get_latest_html()

    if not html_content:
        raise HTTPException(status_code=404, detail="No newspaper HTML available.")

    return HTMLResponse(content=html_content, status_code=200)


@newspaper_router.get("/download")
async def download_newspaper(format: str = Query(default="md", pattern="^(md|html)$")):
    """Download the latest 5-hour newspaper file as Markdown (.md) or Web Newspaper (.html)."""
    edition = _newspaper_service.get_latest_edition()
    if not edition:
        await _newspaper_service.generate_edition(window_hours=5)
        edition = _newspaper_service.get_latest_edition()

    if not edition:
        raise HTTPException(status_code=404, detail="No newspaper edition to download.")

    output_dir = Path("data/newspapers")
    if format == "html":
        file_path = output_dir / f"{edition['edition_id']}.html"
        media_type = "text/html"
        filename = f"{edition['edition_id']}.html"
    else:
        file_path = output_dir / f"{edition['edition_id']}.md"
        media_type = "text/markdown"
        filename = f"{edition['edition_id']}.md"

    if not file_path.exists():
        fallback = output_dir / f"latest.{format}"
        if fallback.exists():
            file_path = fallback
        else:
            raise HTTPException(status_code=404, detail=f"File {filename} not found.")

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename,
    )


@newspaper_router.get("/editions")
async def list_newspaper_editions(limit: int = 15):
    """List historical archived newspaper editions."""
    editions = _newspaper_service.list_editions(limit=limit)
    return {"editions": editions, "count": len(editions)}


@newspaper_router.post("/generate")
async def trigger_newspaper_generation(req: GenerateEditionRequest = GenerateEditionRequest()):
    """Manually compile and publish a fresh 5-hour newspaper edition."""
    meta = await _newspaper_service.generate_edition(window_hours=req.window_hours)
    return {
        "status": "success",
        "message": f"Successfully published Newspaper Edition #{meta['edition_number']} ({meta['total_threats']} threats compiled).",
        "edition": meta,
    }
