import asyncio
import time
import re
from typing import List, Dict, Any
import aiohttp
from bs4 import BeautifulSoup

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

DEFAULT_OOS_KEYWORDS = [
    "out of stock",
    "currently unavailable",
    "sold out",
    "no longer available",
    "item discontinued",
    "temporarily out of stock",
    "this item is unavailable",
]


def parse_keywords(global_keywords: str, custom_keywords: str = "") -> List[str]:
    """Merge and deduplicate global and link-specific out-of-stock keywords."""
    combined = f"{global_keywords},{custom_keywords}"
    items = [kw.strip().lower() for kw in combined.split(",") if kw.strip()]
    seen = set()
    deduped = []
    for kw in items:
        if kw not in seen:
            seen.add(kw)
            deduped.append(kw)
    return deduped if deduped else DEFAULT_OOS_KEYWORDS


def extract_visible_text(html_content: str) -> str:
    """Extract readable body text from HTML while stripping scripts and styles."""
    soup = BeautifulSoup(html_content, "html.parser")
    for element in soup(["script", "style", "noscript", "svg", "head"]):
        element.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).lower()


async def check_single_url_async(
    session: aiohttp.ClientSession,
    url: str,
    keywords: List[str],
    timeout_seconds: int = 10,
) -> Dict[str, Any]:
    """
    Asynchronously check a single affiliate URL for HTTP status errors,
    redirect loops, and out-of-stock text markers in the rendered HTML.
    """
    start_time = time.perf_counter()
    try:
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with session.get(
            url,
            headers=DEFAULT_HEADERS,
            timeout=timeout,
            allow_redirects=True,
            max_redirects=6,
        ) as response:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            http_code = response.status
            final_url = str(response.url)

            if http_code >= 400:
                return {
                    "url": url,
                    "final_url": final_url,
                    "status": "Broken",
                    "http_code": http_code,
                    "response_time_ms": elapsed_ms,
                    "detected_marker": f"HTTP {http_code} Error",
                }

            raw_bytes = await response.content.read(256_000)
            html_text = raw_bytes.decode("utf-8", errors="ignore")
            visible_text = extract_visible_text(html_text)

            for keyword in keywords:
                if keyword and keyword in visible_text:
                    return {
                        "url": url,
                        "final_url": final_url,
                        "status": "Out of Stock",
                        "http_code": http_code,
                        "response_time_ms": elapsed_ms,
                        "detected_marker": f'Matched "{keyword}"',
                    }

            return {
                "url": url,
                "final_url": final_url,
                "status": "Healthy",
                "http_code": http_code,
                "response_time_ms": elapsed_ms,
                "detected_marker": "",
            }

    except aiohttp.TooManyRedirects:
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        return {
            "url": url,
            "final_url": url,
            "status": "Broken",
            "http_code": 310,
            "response_time_ms": elapsed_ms,
            "detected_marker": "Redirect Loop Detected",
        }
    except asyncio.TimeoutError:
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        return {
            "url": url,
            "final_url": url,
            "status": "Broken",
            "http_code": 408,
            "response_time_ms": elapsed_ms,
            "detected_marker": f"Timeout (> {timeout_seconds}s)",
        }
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        return {
            "url": url,
            "final_url": url,
            "status": "Broken",
            "http_code": 0,
            "response_time_ms": elapsed_ms,
            "detected_marker": f"Connection Error: {type(exc).__name__}",
        }


async def run_batch_scan_async(
    links: List[Dict[str, Any]],
    global_keywords: str,
    timeout_seconds: int = 10,
) -> List[Dict[str, Any]]:
    """
    Run concurrent asynchronous HTTP and keyword scans across all registered affiliate links.
    """
    connector = aiohttp.TCPConnector(limit=10, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []
        for link in links:
            target_url = link.get("active_link") or link.get("primary_link")
            keywords = parse_keywords(
                global_keywords, link.get("custom_keywords", "")
            )
            tasks.append(
                check_single_url_async(
                    session=session,
                    url=target_url,
                    keywords=keywords,
                    timeout_seconds=timeout_seconds,
                )
            )

        raw_results = await asyncio.gather(*tasks, return_exceptions=False)
        enriched_results = []
        for link, check_res in zip(links, raw_results):
            enriched_results.append(
                {
                    "link_id": link["id"],
                    "content_title": link["content_title"],
                    "checked_url": check_res["url"],
                    "final_url": check_res["final_url"],
                    "status": check_res["status"],
                    "http_code": check_res["http_code"],
                    "response_time_ms": check_res["response_time_ms"],
                    "detected_marker": check_res["detected_marker"],
                }
            )
        return enriched_results


def run_batch_scan(
    links: List[Dict[str, Any]],
    global_keywords: str,
    timeout_seconds: int = 10,
) -> List[Dict[str, Any]]:
    """Synchronous wrapper around run_batch_scan_async for Streamlit execution."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            new_loop = asyncio.new_event_loop()
            try:
                return new_loop.run_until_complete(
                    run_batch_scan_async(links, global_keywords, timeout_seconds)
                )
            finally:
                new_loop.close()
        return loop.run_until_complete(
            run_batch_scan_async(links, global_keywords, timeout_seconds)
        )
    except RuntimeError:
        return asyncio.run(
            run_batch_scan_async(links, global_keywords, timeout_seconds)
        )


def check_single_url(
    url: str,
    global_keywords: str = "",
    custom_keywords: str = "",
    timeout_seconds: int = 10,
) -> Dict[str, Any]:
    """Synchronous helper to check a single URL immediately."""
    keywords = parse_keywords(global_keywords, custom_keywords)

    async def _runner() -> Dict[str, Any]:
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            return await check_single_url_async(
                session, url, keywords, timeout_seconds
            )

    try:
        return asyncio.run(_runner())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_runner())
        finally:
            loop.close()
