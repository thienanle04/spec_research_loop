"""Download and normalize public scholarly text before S3 persistence."""

import re
from collections.abc import Iterable
from html.parser import HTMLParser
from io import BytesIO

import httpx
from pypdf import PdfReader

from app.modules.research.ports import DocumentText, ScholarlyRecord


class HttpDocumentTextSource:
    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        max_bytes: int = 20_000_000,
    ) -> None:
        self._timeout = timeout_seconds
        self._max_bytes = max_bytes

    async def fetch_text(self, *, record: ScholarlyRecord) -> DocumentText | None:
        warnings: list[str] = []
        for url in _candidate_urls(record):
            try:
                document = await self._download(url)
            except Exception as exc:  # noqa: BLE001 - fall back to provider abstract
                warnings.append(f"Could not download full text from {url}: {type(exc).__name__}")
                continue
            if document and len(document.text.strip()) >= 200:
                document.warnings.extend(warnings)
                return document
        if record.abstract:
            return DocumentText(
                text=record.abstract.strip(),
                source_url=record.url,
                source_kind="abstract",
                original_content_type="text/plain",
                warnings=warnings,
            )
        return None

    async def _download(self, url: str) -> DocumentText | None:
        headers = {"User-Agent": "SpecResearchLoop/0.1 scholarly-text-retrieval"}
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            headers=headers,
        ) as client, client.stream("GET", url) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > self._max_bytes:
                    raise ValueError("Downloaded document exceeds configured size limit")
                chunks.append(chunk)
            data = b"".join(chunks)
            content_type = response.headers.get("content-type", "").split(";", 1)[0]
            source_url = str(response.url)
        if content_type == "application/pdf" or data.startswith(b"%PDF"):
            text = _pdf_text(data)
            kind = "full_text_pdf"
        elif content_type in {"text/html", "application/xhtml+xml"}:
            text = _html_text(data)
            kind = "full_text_html"
        elif content_type.startswith("text/") or content_type in {
            "application/xml",
            "application/json",
        }:
            text = data.decode("utf-8", errors="replace")
            kind = "full_text"
        else:
            return None
        return DocumentText(
            text=_normalize_text(text),
            source_url=source_url,
            source_kind=kind,
            original_content_type=content_type or None,
        )


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.focus_parts: list[str] = []
        self._suppressed = 0
        self._focus_depth = 0
        self._found_focus = False

    def _append(self, value: str) -> None:
        self.parts.append(value)
        if self._focus_depth:
            self.focus_parts.append(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {
            "script",
            "style",
            "noscript",
            "svg",
            "nav",
            "header",
            "footer",
            "aside",
            "form",
            "button",
            "select",
            "option",
            "dialog",
        }:
            self._suppressed += 1
            return
        if self._suppressed:
            return
        if tag in {"main", "article"}:
            self._focus_depth += 1
            self._found_focus = True
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._append("\n[Section] ")
        elif tag in {"p", "div", "section", "main", "article", "br", "li"}:
            self._append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {
            "script",
            "style",
            "noscript",
            "svg",
            "nav",
            "header",
            "footer",
            "aside",
            "form",
            "button",
            "select",
            "option",
            "dialog",
        } and self._suppressed:
            self._suppressed -= 1
            return
        if self._suppressed:
            return
        if tag in {
            "p",
            "div",
            "section",
            "main",
            "article",
            "li",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        }:
            self._append("\n")
        if tag in {"main", "article"} and self._focus_depth:
            self._focus_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._suppressed:
            self._append(data)

    def extracted_text(self) -> str:
        focused = "".join(self.focus_parts).strip()
        if self._found_focus and len(focused) >= 200:
            return focused
        return "".join(self.parts)


def _candidate_urls(record: ScholarlyRecord) -> list[str]:
    metadata = record.metadata
    external_ids = metadata.get("externalIds") or {}
    provider_ids = metadata.get("ids") or {}
    best_oa_location = metadata.get("best_oa_location") or {}
    primary_location = metadata.get("primary_location") or {}
    candidates: list[str | None] = [
        metadata.get("full_text_url"),
        metadata.get("open_access_pdf_url"),
        best_oa_location.get("pdf_url"),
        primary_location.get("pdf_url"),
        _arxiv_pdf_url(external_ids.get("ArXiv") or provider_ids.get("arxiv")),
        _pmc_full_text_url(external_ids.get("PubMedCentral")),
        _trusted_repository_url(best_oa_location.get("landing_page_url")),
        _trusted_repository_url(primary_location.get("landing_page_url")),
        best_oa_location.get("landing_page_url"),
        primary_location.get("landing_page_url"),
        record.url,
        _doi_url(record.doi),
    ]
    unique: list[str] = []
    for item in candidates:
        if isinstance(item, str) and item.startswith(("http://", "https://")) and item not in unique:
            unique.append(item)
    return unique


def _doi_url(value: object) -> str | None:
    doi = str(value or "").strip()
    if not doi:
        return None
    doi = re.sub(
        r"^https?://(?:dx\.)?doi\.org/",
        "",
        doi,
        flags=re.IGNORECASE,
    ).strip()
    return f"https://doi.org/{doi}" if doi else None


def _arxiv_pdf_url(identifier: object) -> str | None:
    value = str(identifier or "").strip()
    if not value:
        return None
    value = re.sub(
        r"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"^arxiv:\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\.pdf$", "", value, flags=re.IGNORECASE).strip("/")
    return f"https://arxiv.org/pdf/{value}" if value else None


def _pmc_full_text_url(identifier: object) -> str | None:
    value = str(identifier or "").strip()
    if not value:
        return None
    article_id = value if value.upper().startswith("PMC") else f"PMC{value}"
    return f"https://pmc.ncbi.nlm.nih.gov/articles/{article_id}/"


def _trusted_repository_url(value: object) -> str | None:
    url = str(value or "").strip()
    folded = url.casefold()
    if not url.startswith(("http://", "https://")):
        return None
    if "arxiv.org/abs/" in folded:
        return re.sub(r"/abs/", "/pdf/", url, flags=re.IGNORECASE)
    if "aclanthology.org/" in folded:
        return f"{url.rstrip('/').removesuffix('.pdf')}.pdf"
    if "openreview.net/forum" in folded:
        return re.sub(r"/forum", "/pdf", url, flags=re.IGNORECASE)
    if "proceedings.mlr.press/" in folded and folded.endswith(".html"):
        return f"{url[:-5]}.pdf"
    if any(
        host in folded
        for host in (
            "openreview.net/pdf",
            "pmc.ncbi.nlm.nih.gov/articles/",
        )
    ):
        return url
    return None


def _pdf_text(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        pages.append(f"\n\n[Page {number}]\n{page.extract_text() or ''}")
    return "".join(pages)


def _html_text(data: bytes) -> str:
    parser = _TextExtractor()
    parser.feed(data.decode("utf-8", errors="replace"))
    return parser.extracted_text()


def _normalize_text(text: str) -> str:
    lines: Iterable[str] = (re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())
    normalized: list[str] = []
    blank = False
    for line in lines:
        if not line:
            if normalized and not blank:
                normalized.append("")
            blank = True
            continue
        normalized.append(line)
        blank = False
    return "\n".join(normalized).strip()
