"""
Newspaper API router for 5-hour autonomous intelligence broadsheets.
"""
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from ai_security_monitor.application.services.newspaper_service import NewspaperService
from ai_security_monitor.config.settings import settings
from ai_security_monitor.infrastructure.delivery.base import delivery_registry

newspaper_router = APIRouter(prefix="/newspaper", tags=["Newspaper"])

_newspaper_service = NewspaperService()


class GenerateEditionRequest(BaseModel):
    window_hours: int = 5


class EmailNewspaperRequest(BaseModel):
    to_email: str
    from_email: str | None = None
    smtp_server: str | None = None
    smtp_port: int | None = None
    username: str | None = None
    password: str | None = None


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
async def download_newspaper(format: str = Query(default="md", pattern="^(md|html|pdf)$")):
    """Download the latest 5-hour newspaper file as Markdown (.md), Web Newspaper (.html), or PDF (.pdf)."""
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
    elif format == "pdf":
        file_path = output_dir / f"{edition['edition_id']}.pdf"
        media_type = "application/pdf"
        filename = f"The_Cyber_Intelligence_Chronicle_Edition_{edition['edition_number']}.pdf"
        if not file_path.exists():
            fallback = output_dir / "latest.pdf"
            if fallback.exists():
                file_path = fallback
            else:
                # Generate if missing
                await _newspaper_service.generate_edition(window_hours=5)
                file_path = output_dir / f"{edition['edition_id']}.pdf"
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


@newspaper_router.post("/email")
async def email_newspaper_pdf(req: EmailNewspaperRequest):
    """Email the latest 5-hour newspaper PDF document to the specified recipient."""
    edition = _newspaper_service.get_latest_edition()
    if not edition:
        await _newspaper_service.generate_edition(window_hours=5)
        edition = _newspaper_service.get_latest_edition()

    if not edition:
        raise HTTPException(status_code=404, detail="No newspaper edition available.")

    pdf_path = _newspaper_service.get_latest_pdf_path()
    if not pdf_path or not pdf_path.exists():
        # Re-generate to produce PDF if missing
        await _newspaper_service.generate_edition(window_hours=5)
        pdf_path = _newspaper_service.get_latest_pdf_path()

    if not pdf_path or not pdf_path.exists():
        raise HTTPException(status_code=500, detail="Failed to locate or generate newspaper PDF.")

    # Build EmailDelivery config
    email_cfg = {
        "smtp_server": req.smtp_server or settings.delivery.email_smtp_server,
        "smtp_port": req.smtp_port or settings.delivery.email_smtp_port,
        "username": req.username or settings.delivery.email_username or "",
        "password": req.password or settings.delivery.email_password or "",
        "from_email": req.from_email or settings.delivery.email_from or settings.delivery.email_username or "noreply@aetherguard.ai",
        "to_email": req.to_email,
    }

    email_delivery = delivery_registry.create("email", email_cfg)

    result = await email_delivery.send_newspaper_pdf(
        pdf_path=pdf_path,
        edition_number=edition["edition_number"],
        to_email=req.to_email,
        lead_story=edition.get("lead_story", ""),
        total_threats=edition.get("total_threats", 0),
    )

    if result.success:
        return {
            "status": "success",
            "message": f"The Cyber Intelligence Chronicle Edition #{edition['edition_number']} (PDF) was sent successfully to {req.to_email}!",
            "details": result.message
        }
    else:
        raise HTTPException(
            status_code=400 if "missing" in (result.error or "") else 500,
            detail=f"Failed to email newspaper PDF: {result.error}"
        )
