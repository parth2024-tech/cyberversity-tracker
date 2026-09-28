"""
Model Context Protocol (MCP) server for Cyberversity AI Monitor.

Provides a standard JSON-RPC 2.0 stdio server enabling AI coding assistants
and chatbots (Claude, Cursor, Antigravity, VS Code) to query worldwide AI
intelligence, research dossiers, source health, and perform sanitized scraping.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from ai_security_monitor.application.services.source_health_service import (
    source_health_service,
)
from ai_security_monitor.core.logging import get_logger
from ai_security_monitor.core.markdown import markdown_converter
from ai_security_monitor.core.sanitizer import sanitizer
from ai_security_monitor.infrastructure.database.connection import db_manager
from ai_security_monitor.infrastructure.fetchers.throttle import domain_throttle

logger = get_logger(__name__)

SERVER_NAME = "cyberversity-ai-monitor"
SERVER_VERSION = "2.0.0"

TOOLS_REGISTRY: list[dict[str, Any]] = [
    {
        "name": "get_worldwide_ai_news",
        "description": "Fetch fresh (< 14 days old) curated worldwide AI intelligence, releases, and models.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of entries to return (default: 15)",
                    "default": 15,
                },
                "category": {
                    "type": "string",
                    "description": "Optional category filter: 'github_trending', 'arxiv_research', 'frontier_models', 'sovereign_ai', 'developer_tools'",
                },
            },
        },
    },
    {
        "name": "get_source_health_telemetry",
        "description": "Retrieve operational health, latency metrics, and AutoThrottle crawl delay stats across all monitored intelligence sources.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "convert_html_to_markdown",
        "description": "Convert messy or raw HTML web content into clean, sanitized, LLM-ready Markdown, stripping scripts, navigation, and noise tags.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "html_content": {
                    "type": "string",
                    "description": "Raw HTML string to convert",
                },
                "base_url": {
                    "type": "string",
                    "description": "Optional base URL to resolve relative hyperlinks",
                    "default": "",
                },
            },
            "required": ["html_content"],
        },
    },
    {
        "name": "sanitize_ai_prompt",
        "description": "Defuse indirect prompt injections, strip zero-width unicode characters, and clean low-level control characters from untrusted web text before passing it to LLMs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Untrusted text to sanitize",
                },
            },
            "required": ["text"],
        },
    },
]


class MCPServer:
    """Standard JSON-RPC 2.0 stdio Model Context Protocol (MCP) server."""

    def __init__(self) -> None:
        self.running = False

    async def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Dispatch a single JSON-RPC 2.0 request."""
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        # Handle notifications (no id)
        if req_id is None:
            if method == "notifications/initialized":
                logger.info("MCP client acknowledged initialization")
            return None

        # Standard MCP Methods
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION,
                    },
                    "capabilities": {
                        "tools": {"listChanged": False},
                    },
                },
            }

        elif method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": TOOLS_REGISTRY},
            }

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            result_text = await self._execute_tool(tool_name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": result_text}],
                },
            }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}",
                },
            }

    async def _execute_tool(self, name: str | None, args: dict[str, Any]) -> str:
        """Execute the requested tool and return formatted text."""
        try:
            if name == "convert_html_to_markdown":
                html_input = args.get("html_content", "")
                base_url = args.get("base_url", "")
                return markdown_converter.convert(html_input, base_url=base_url)

            elif name == "sanitize_ai_prompt":
                text_input = args.get("text", "")
                return sanitizer.sanitize_text(text_input)

            elif name == "get_source_health_telemetry":
                report = source_health_service.get_health_report()
                report["domain_throttle_live"] = domain_throttle.get_stats()
                return json.dumps(report, indent=2, default=str)

            elif name == "get_worldwide_ai_news":
                limit = min(int(args.get("limit", 15)), 50)
                category = args.get("category")
                async with db_manager.session() as session:
                    from sqlalchemy import select

                    from ai_security_monitor.infrastructure.database.models import (
                        EntryModel,
                    )

                    query = select(EntryModel).order_by(EntryModel.published_at.desc()).limit(limit)
                    if category:
                        query = query.where(EntryModel.category == category)

                    rows = (await session.execute(query)).scalars().all()
                    entries = [
                        {
                            "id": str(r.id),
                            "title": r.title,
                            "url": r.url,
                            "summary": r.summary,
                            "category": str(r.category),
                            "published_at": r.published_at.isoformat() if r.published_at else None,
                            "tags": r.tags,
                        }
                        for r in rows
                    ]
                    return json.dumps(entries, indent=2)

            else:
                return f"Error: Unknown tool {name!r}"

        except Exception as e:
            return f"Error executing tool {name!r}: {e}"

    async def run_stdio(self) -> None:
        """Run standard I/O listener loop."""
        self.running = True
        logger.info(f"Starting {SERVER_NAME} v{SERVER_VERSION} MCP stdio server")

        import asyncio

        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        loop = asyncio.get_running_loop()
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while self.running:
            line_bytes = await reader.readline()
            if not line_bytes:
                break

            line = line_bytes.decode("utf-8").strip()
            if not line:
                continue

            try:
                request = json.loads(line)
                response = await self.handle_request(request)
                if response is not None:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
            except Exception as e:
                logger.error(f"Error processing MCP JSON-RPC message: {e}")
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()


async def run_stdio_server() -> None:
    """Entrypoint function to run MCP server."""
    server = MCPServer()
    await server.run_stdio()


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_stdio_server())
