"""
Web crawlers for Wireshark wiki and PAN-OS TechDocs.

Both crawlers:
  - Fetch pages with httpx (async, with rate-limiting)
  - Pass raw HTML to markitdown for HTML→Markdown conversion
  - Ingest each page via rag.ingest.ingest_url()
  - Follow same-origin <a href> links within the configured prefix
  - Accept a progress_callback(done, total, current_url) for task tracking

Public API:
  crawl_wireshark_wiki(max_pages, progress_callback) -> CrawlResult
  crawl_panos_techdocs(base_url, max_pages, progress_callback) -> CrawlResult
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable
from urllib.parse import urljoin, urlparse

import httpx

log = logging.getLogger(__name__)

# Wireshark pages to seed the crawl
WIRESHARK_SEED_URLS = [
    "https://wiki.wireshark.org/DisplayFilters",
    "https://wiki.wireshark.org/CaptureFilters",
    "https://wiki.wireshark.org/ProtocolReference",
    "https://wiki.wireshark.org/Modbus",
    "https://wiki.wireshark.org/TCP",
    "https://wiki.wireshark.org/TLS",
    "https://wiki.wireshark.org/DNS",
    "https://wiki.wireshark.org/HTTP",
    "https://wiki.wireshark.org/HTTPS",
    "https://wiki.wireshark.org/OPC-UA",
    "https://wiki.wireshark.org/DNP3",
    "https://wiki.wireshark.org/ICMP",
    "https://wiki.wireshark.org/SampleCaptures",
]

WIRESHARK_BASE = "https://wiki.wireshark.org"
WIRESHARK_SOURCE = "wireshark-wiki"

CRAWL_DELAY   = 0.5   # seconds between requests (polite crawling)
REQUEST_TIMEOUT = 15.0

# ── SSRF protection ───────────────────────────────────────────────────────────

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_safe_url(url: str) -> tuple[bool, str]:
    """
    Return (True, "") if the URL is safe to fetch, or (False, reason) if not.
    Blocks: non-http(s) schemes, private/loopback IPs.
    """
    try:
        parsed = urlparse(url)
    except Exception as exc:
        return False, f"URL parse error: {exc}"

    if parsed.scheme not in ("http", "https"):
        return False, f"Scheme '{parsed.scheme}' not allowed; only http/https."

    hostname = parsed.hostname or ""
    if not hostname:
        return False, "Missing hostname."

    # Resolve hostname to IP and check for private ranges
    try:
        resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for _fam, _type, _proto, _canon, sockaddr in resolved:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
                for net in _PRIVATE_NETS:
                    if ip in net:
                        return False, f"Host '{hostname}' resolves to private IP {ip}."
            except ValueError:
                pass
    except socket.gaierror:
        # If DNS fails let the HTTP client handle it (will also fail)
        pass

    return True, ""


@dataclass
class CrawlResult:
    source_name:  str
    pages_crawled: int
    total_chunks:  int
    errors:        int
    duration_s:    float
    error_details: list[str] = field(default_factory=list)
    cancelled:     bool      = False


# ── Link extraction ───────────────────────────────────────────────────────────

_HREF_RE = re.compile(r'href=["\']([^"\'#?]+)["\']', re.IGNORECASE)


def _extract_links(html: str, base_url: str, allowed_prefix: str) -> list[str]:
    """Extract all same-prefix absolute links from raw HTML."""
    links = set()
    for href in _HREF_RE.findall(html):
        absolute = urljoin(base_url, href)
        # Only follow links within the allowed prefix
        if absolute.startswith(allowed_prefix):
            # Strip fragments and query strings
            parsed = urlparse(absolute)
            clean  = parsed._replace(fragment="", query="").geturl()
            links.add(clean)
    return list(links)


# ── Core page fetcher ─────────────────────────────────────────────────────────

async def _fetch_and_ingest(
    client:      httpx.AsyncClient,
    url:         str,
    source_name: str,
) -> tuple[int, list[str], str]:
    """
    Fetch *url*, convert to markdown, ingest.
    Returns (chunks_added, new_links_found, error_str).
    """
    from rag.ingest import ingest_url

    try:
        resp = await client.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        html     = resp.text
        new_links = _extract_links(html, url, url.rsplit("/", 1)[0])
    except Exception as exc:
        return 0, [], str(exc)

    try:
        result = await ingest_url(url, source_name)
        if result.error:
            return 0, new_links, result.error
        return result.chunk_count, new_links, ""
    except Exception as exc:
        return 0, new_links, str(exc)


# ── Wireshark wiki crawler ────────────────────────────────────────────────────

async def crawl_wireshark_wiki(
    max_pages:         int = 50,
    progress_callback: Callable[[int, int, str], Awaitable[None]] | None = None,
    cancel_event=None,  # Optional[asyncio.Event]
) -> CrawlResult:
    """
    Crawl the Wireshark wiki starting from WIRESHARK_SEED_URLS.
    Follows links within wiki.wireshark.org up to *max_pages*.
    """
    start = time.monotonic()
    visited: set[str] = set()
    queue   = list(WIRESHARK_SEED_URLS)
    total_chunks = 0
    errors = 0
    error_details: list[str] = []

    headers = {
        "User-Agent": "WiresharkAIAgent/1.0 (educational research bot)",
        "Accept": "text/html",
    }

    cancelled = False
    async with httpx.AsyncClient(
        headers=headers,
        follow_redirects=True,
        timeout=REQUEST_TIMEOUT,
    ) as client:
        while queue and len(visited) < max_pages:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                log.info("[crawler] Wireshark crawl cancelled after %d pages.", len(visited))
                break

            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            if progress_callback:
                await progress_callback(len(visited), min(max_pages, len(visited) + len(queue)), url)

            log.info("[crawler] Wireshark: fetching %s", url)
            chunks, new_links, err = await _fetch_and_ingest(client, url, WIRESHARK_SOURCE)

            if err:
                errors += 1
                error_details.append(f"{url}: {err}")
                log.warning("[crawler] Wireshark error: %s — %s", url, err)
            else:
                total_chunks += chunks

            # Add new same-domain links to the queue
            for link in new_links:
                if link not in visited and link.startswith(WIRESHARK_BASE) and link not in queue:
                    queue.append(link)

            await asyncio.sleep(CRAWL_DELAY)

    return CrawlResult(
        source_name   = WIRESHARK_SOURCE,
        pages_crawled = len(visited),
        total_chunks  = total_chunks,
        errors        = errors,
        duration_s    = time.monotonic() - start,
        error_details = error_details,
        cancelled     = cancelled,
    )


# ── PAN-OS TechDocs crawler ───────────────────────────────────────────────────

async def crawl_panos_techdocs(
    base_url:          str,
    max_pages:         int = 100,
    source_name:       str = "panos-techdocs",
    progress_callback: Callable[[int, int, str], Awaitable[None]] | None = None,
    cancel_event=None,  # Optional[asyncio.Event]
) -> CrawlResult:
    """
    Crawl PAN-OS TechDocs starting from *base_url*.
    Only follows links that start with *base_url* (same-prefix constraint).

    Typical base_url:
      https://docs.paloaltonetworks.com/pan-os/11-1/pan-os-cli-quick-start
    """
    start = time.monotonic()

    # Normalise: strip trailing slash
    base_url = base_url.rstrip("/")

    # SSRF protection — validate before starting any network activity
    safe, reason = _is_safe_url(base_url)
    if not safe:
        return CrawlResult(
            source_name   = source_name,
            pages_crawled = 0,
            total_chunks  = 0,
            errors        = 1,
            duration_s    = 0.0,
            error_details = [f"URL rejected: {reason}"],
        )

    parsed   = urlparse(base_url)
    origin   = f"{parsed.scheme}://{parsed.netloc}"

    visited: set[str] = set()
    queue   = [base_url]
    total_chunks = 0
    errors = 0
    error_details: list[str] = []

    headers = {
        "User-Agent": "WiresharkAIAgent/1.0 (educational research bot)",
        "Accept": "text/html",
    }

    cancelled = False
    async with httpx.AsyncClient(
        headers=headers,
        follow_redirects=True,
        timeout=REQUEST_TIMEOUT,
    ) as client:
        while queue and len(visited) < max_pages:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                log.info("[crawler] PAN-OS crawl cancelled after %d pages.", len(visited))
                break

            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            if progress_callback:
                await progress_callback(len(visited), min(max_pages, len(visited) + len(queue)), url)

            log.info("[crawler] PAN-OS: fetching %s", url)
            chunks, new_links, err = await _fetch_and_ingest(client, url, source_name)

            if err:
                errors += 1
                error_details.append(f"{url}: {err}")
                log.warning("[crawler] PAN-OS error: %s — %s", url, err)
            else:
                total_chunks += chunks

            # Only follow links within the same base_url prefix
            for link in new_links:
                if (
                    link not in visited
                    and link.startswith(base_url)
                    and link not in queue
                ):
                    queue.append(link)

            await asyncio.sleep(CRAWL_DELAY)

    return CrawlResult(
        source_name   = source_name,
        pages_crawled = len(visited),
        total_chunks  = total_chunks,
        errors        = errors,
        duration_s    = time.monotonic() - start,
        error_details = error_details,
        cancelled     = cancelled,
    )
