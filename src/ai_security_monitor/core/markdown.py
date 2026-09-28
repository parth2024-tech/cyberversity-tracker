"""
HTML to clean Markdown converter inspired by Scrapling's RAG markdown pipeline.

Strips layout boilerplate, scripts, navigation, and noise tags, converting
arbitrary HTML articles, paper abstracts, and RSS feeds into structured,
LLM-ready Markdown.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag


class HTMLToMarkdownConverter:
    """Converts HTML to clean, standardized Markdown without heavy external dependencies."""

    NOISE_TAGS = frozenset(
        {
            "script",
            "style",
            "noscript",
            "svg",
            "iframe",
            "nav",
            "footer",
            "header",
            "aside",
            "button",
            "form",
            "input",
            "select",
            "textarea",
            "template",
        }
    )

    @classmethod
    def convert(
        cls,
        html_content: str | None,
        base_url: str = "",
        max_length: int = 25000,
    ) -> str:
        """Convert HTML string to clean Markdown."""
        if not html_content or not html_content.strip():
            return ""

        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # 1. Drop noise tags completely
            for tag in soup(list(cls.NOISE_TAGS)):
                tag.decompose()

            # 2. Extract body or container if available
            root = soup.body or soup

            # 3. Recursively convert DOM tree
            md_lines: list[str] = []
            cls._node_to_markdown(root, md_lines, base_url=base_url)

            # 4. Normalize spacing
            text = "\n".join(md_lines)
            # Remove more than 2 consecutive newlines
            text = re.sub(r"\n{3,}", "\n\n", text).strip()

            if len(text) > max_length:
                text = text[:max_length] + "\n\n… [content truncated for length]"

            return text

        except Exception:
            # Fallback to plain text with HTML tags stripped via regex
            cleaned = re.sub(r"<[^>]+>", " ", str(html_content))
            return html.unescape(re.sub(r"\s+", " ", cleaned).strip())

    @classmethod
    def _node_to_markdown(
        cls,
        node: Tag | NavigableString,
        output: list[str],
        base_url: str = "",
        list_prefix: str = "",
    ) -> None:
        if isinstance(node, NavigableString):
            content = str(node).strip()
            if content:
                output.append(html.unescape(content))
            return

        if not isinstance(node, Tag):
            return

        tag_name = node.name.lower()

        # Headings
        if tag_name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag_name[1])
            heading_text = cls._get_inline_text(node, base_url).strip()
            if heading_text:
                output.append(f"\n{'#' * level} {heading_text}\n")
            return

        # Paragraphs
        if tag_name == "p":
            p_text = cls._get_inline_text(node, base_url).strip()
            if p_text:
                output.append(f"\n{p_text}\n")
            return

        # Container tags: if they only have inline text, output as paragraph, else recurse
        if tag_name in ("div", "section", "article", "main", "body", "html"):
            has_block_children = any(
                isinstance(child, Tag)
                and child.name.lower()
                in (
                    "p",
                    "h1",
                    "h2",
                    "h3",
                    "h4",
                    "h5",
                    "h6",
                    "ul",
                    "ol",
                    "table",
                    "pre",
                    "blockquote",
                    "div",
                    "section",
                    "article",
                )
                for child in node.children
            )
            if not has_block_children:
                p_text = cls._get_inline_text(node, base_url).strip()
                if p_text:
                    output.append(f"\n{p_text}\n")
                return

        # Blockquotes
        if tag_name == "blockquote":
            quote_text = cls._get_inline_text(node, base_url).strip()
            if quote_text:
                lines = quote_text.split("\n")
                quoted = "\n".join(f"> {line}" for line in lines if line.strip())
                output.append(f"\n{quoted}\n")
            return

        # Code blocks
        if tag_name == "pre":
            code_tag = node.find("code")
            code_text = (code_tag or node).get_text()
            output.append(f"\n```\n{code_text.strip()}\n```\n")
            return

        # Unordered / Ordered Lists
        if tag_name in ("ul", "ol"):
            output.append("\n")
            is_ordered = tag_name == "ol"
            idx = 1
            for child in node.children:
                if isinstance(child, Tag) and child.name == "li":
                    prefix = f"{idx}. " if is_ordered else "- "
                    item_text = cls._get_inline_text(child, base_url).strip()
                    if item_text:
                        output.append(f"{prefix}{item_text}")
                        idx += 1
            output.append("\n")
            return

        # Tables
        if tag_name == "table":
            table_md = cls._table_to_markdown(node)
            if table_md:
                output.append(f"\n{table_md}\n")
            return

        # Horizontal Rule
        if tag_name == "hr":
            output.append("\n---\n")
            return

        # Fallback: recurse into children
        for child in node.children:
            cls._node_to_markdown(
                child, output, base_url=base_url, list_prefix=list_prefix
            )

    @classmethod
    def _get_inline_text(cls, tag: Tag, base_url: str = "") -> str:
        """Process inline formatting like bold, italics, links, and code."""
        parts: list[str] = []
        for child in tag.children:
            if isinstance(child, NavigableString):
                parts.append(html.unescape(str(child)))
            elif isinstance(child, Tag):
                c_name = child.name.lower()
                c_text = cls._get_inline_text(child, base_url)
                if c_name in ("strong", "b"):
                    parts.append(f"**{c_text.strip()}**" if c_text.strip() else "")
                elif c_name in ("em", "i"):
                    parts.append(f"*{c_text.strip()}*" if c_text.strip() else "")
                elif c_name == "code":
                    parts.append(f"`{c_text.strip()}`" if c_text.strip() else "")
                elif c_name == "a":
                    href = child.get("href", "")
                    if href:
                        if base_url and not href.startswith(("http://", "https://")):
                            href = urljoin(base_url, href)
                        parts.append(f"[{c_text.strip()}]({href})")
                    else:
                        parts.append(c_text)
                elif c_name == "br":
                    parts.append("\n")
                else:
                    parts.append(c_text)
        return "".join(parts)

    @classmethod
    def _table_to_markdown(cls, table: Tag) -> str:
        """Convert an HTML table into a standard Markdown table."""
        rows = table.find_all("tr")
        if not rows:
            return ""

        matrix: list[list[str]] = []
        for row in rows:
            cells = row.find_all(["th", "td"])
            if cells:
                matrix.append(
                    [cell.get_text(separator=" ", strip=True) for cell in cells]
                )

        if not matrix:
            return ""

        col_count = max(len(r) for r in matrix)
        # Pad shorter rows
        for r in matrix:
            while len(r) < col_count:
                r.append("")

        header = matrix[0]
        separator = ["---"] * col_count
        lines = [
            f"| {' | '.join(header)} |",
            f"| {' | '.join(separator)} |",
        ]
        for row in matrix[1:]:
            lines.append(f"| {' | '.join(row)} |")

        return "\n".join(lines)


# Global singleton instance
markdown_converter = HTMLToMarkdownConverter()
