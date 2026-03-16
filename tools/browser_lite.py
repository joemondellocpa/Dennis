"""
Lightweight web browsing without Playwright.
Used when LIGHTWEIGHT_MODE=true (e.g. Raspberry Pi).
Uses httpx + BeautifulSoup4 – ~5MB RAM vs ~400MB for Chromium.
"""
import asyncio
from urllib.parse import quote_plus

import httpx

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


async def web_search(query: str, num_results: int = 5) -> dict:
    """Search via DuckDuckGo lite (no JS required)."""
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    return await fetch_page(url)


async def fetch_page(url: str, **_kwargs) -> dict:
    """Fetch a URL and extract readable text using BeautifulSoup4."""
    try:
        async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True, timeout=20) as client:
            r = await client.get(url)
            if r.status_code >= 400:
                return {"success": False, "error": f"HTTP {r.status_code}"}

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            title = soup.title.string.strip() if soup.title else ""
        except ImportError:
            # bs4 not installed – return raw text trimmed
            text = r.text
            title = ""

        return {
            "success": True,
            "url": url,
            "title": title,
            "content": text[:6000],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
