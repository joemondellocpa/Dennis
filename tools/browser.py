"""
Browser tool using Playwright (headless Chromium).
Supports: web search, page content extraction, form filling.
"""
import asyncio
from typing import Optional
from urllib.parse import quote_plus


async def _get_browser():
    """Lazily import playwright to avoid startup cost if not used."""
    from playwright.async_api import async_playwright
    return async_playwright


async def web_search(query: str, num_results: int = 5) -> dict:
    """Search the web via DuckDuckGo and return top results."""
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    result = await fetch_page(url)
    if not result["success"]:
        return result

    # Parse basic results from the HTML
    content = result["content"]
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    # Return raw content – the LLM will extract what it needs
    return {
        "success": True,
        "query": query,
        "url": url,
        "content": "\n".join(lines[:200]),  # First 200 non-empty lines
    }


async def fetch_page(url: str, wait_for: str = "domcontentloaded") -> dict:
    """Fetch a web page and return its text content."""
    playwright_cm = await _get_browser()
    async with playwright_cm() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_extra_http_headers({
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            })
            response = await page.goto(url, wait_until=wait_for, timeout=30000)
            if not response or response.status >= 400:
                return {"success": False, "error": f"HTTP {response.status if response else 'no response'}"}

            # Extract readable text (strip scripts/styles)
            content = await page.evaluate("""() => {
                const clone = document.cloneNode(true);
                clone.querySelectorAll('script,style,nav,footer,header,aside').forEach(e => e.remove());
                return clone.body ? clone.body.innerText : document.body.innerText;
            }""")
            title = await page.title()
            return {
                "success": True,
                "url": url,
                "title": title,
                "content": content[:8000],  # Cap at 8k chars
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            await browser.close()


async def fill_and_submit_form(url: str, selectors_values: dict, submit_selector: str) -> dict:
    """Fill a form on a page and submit it."""
    playwright_cm = await _get_browser()
    async with playwright_cm() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            for selector, value in selectors_values.items():
                await page.fill(selector, value)
            await page.click(submit_selector)
            await page.wait_for_load_state("networkidle", timeout=15000)
            content = await page.evaluate("document.body.innerText")
            return {"success": True, "content": content[:4000]}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            await browser.close()
