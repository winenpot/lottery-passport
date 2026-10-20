"""``GET /legal/{version}``: the terms of use + privacy page (LG1').

The text lives in the database and is edited in /admin ("Terms & privacy");
this route renders it as a small right-to-left HTML page. ``TERMS_URL`` and
``PRIVACY_URL`` in each server's .env point here
(``https://<host>/legal/<version>`` and the same URL with ``#privacy``).

Rendering understands only what the text uses: ``#``/``##``/``###``
headings (an optional trailing ``{#id}`` becomes the heading's anchor),
paragraphs separated by blank lines, ``-`` list items (indented lines
continue the item) and ``---`` rules. Everything is HTML-escaped: an admin
typing markup into the panel can never inject script into a public page.
"""

import html
import re
from typing import Annotated

from fastapi import APIRouter, Depends, Path
from fastapi.responses import HTMLResponse

from app.api.deps import get_legal_document_service
from app.api.errors import ApiError, ErrorResponse
from app.application.legal import LegalDocumentService
from app.domain.legal import LegalDocument

router = APIRouter(tags=["legal"])

_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")
_ANCHOR = re.compile(r"\s*\{#([A-Za-z][A-Za-z0-9_-]{0,40})\}\s*$")
_LIST_ITEM = re.compile(r"^\s*-\s+(.*)$")

_STYLE = (
    "body{max-width:46rem;margin:0 auto;padding:1.25rem;"
    'font-family:Vazirmatn,Tahoma,"Noto Sans Arabic",sans-serif;'
    "line-height:1.9;color:#1a1a1a;background:#fff}"
    "h1{font-size:1.35rem}h2{font-size:1.15rem;margin-top:2rem}"
    "ul{padding-inline-start:1.25rem}"
    "hr{border:0;border-top:1px solid #ddd;margin:2rem 0}"
)


@router.get(
    "/legal/{version}",
    response_class=HTMLResponse,
    summary="Terms of use + privacy page",
    description=(
        "No sign-in needed. An HTML page (right to left) for the exact version "
        "`/config` names in `terms_version`; link to it via `terms_url` / "
        "`privacy_url`. Open it as a page or a new tab: it cannot be framed."
    ),
    responses={404: {"model": ErrorResponse, "description": "Unknown version"}},
)
async def legal_page(
    version: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,20}$")],
    service: Annotated[LegalDocumentService, Depends(get_legal_document_service)],
) -> HTMLResponse:
    document = await service.get(version)
    if document is None:
        raise ApiError(404, "NOT_FOUND", "unknown legal document version")
    return HTMLResponse(render_legal_page(document))


def render_legal_page(document: LegalDocument) -> str:
    blocks, title = _render_blocks(document.body)
    return (
        '<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title or 'TorshX')}</title>"
        f"<style>{_STYLE}</style></head><body>{''.join(blocks)}</body></html>"
    )


def _render_blocks(body: str) -> tuple[list[str], str | None]:
    blocks: list[str] = []
    paragraph: list[str] = []
    items: list[str] = []
    title: str | None = None

    def flush() -> None:
        if paragraph:
            blocks.append(f"<p>{html.escape(' '.join(paragraph))}</p>")
            paragraph.clear()
        if items:
            rendered = "".join(f"<li>{html.escape(item)}</li>" for item in items)
            blocks.append(f"<ul>{rendered}</ul>")
            items.clear()

    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            text = heading.group(2)
            anchor = _ANCHOR.search(text)
            attribute = ""
            if anchor:
                text = text[: anchor.start()]
                attribute = f' id="{anchor.group(1)}"'
            if level == 1 and title is None:
                title = text
            blocks.append(f"<h{level}{attribute}>{html.escape(text)}</h{level}>")
            continue
        if line == "---":
            flush()
            blocks.append("<hr>")
            continue
        item = _LIST_ITEM.match(raw)
        if item:
            if paragraph:
                blocks.append(f"<p>{html.escape(' '.join(paragraph))}</p>")
                paragraph.clear()
            items.append(item.group(1).strip())
            continue
        if items and raw[:1].isspace():
            items[-1] = f"{items[-1]} {line}"
            continue
        if items:
            flush()
        paragraph.append(line)
    flush()
    return blocks, title
