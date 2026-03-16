"""
LinkedIn tool via Playwright automation.
Handles: posting, searching for people/companies, connection requests, messaging.
"""
import json
import asyncio
from pathlib import Path
import config


async def _get_page():
    """Return an authenticated Playwright page. Reuses saved cookies."""
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    context = await browser.new_context()

    cookies_file = config.LINKEDIN_COOKIES_FILE
    if cookies_file.exists():
        with open(str(cookies_file)) as f:
            await context.add_cookies(json.load(f))

    page = await context.new_page()
    return pw, browser, context, page


async def _login_if_needed(page, context) -> bool:
    """Check if logged in; if not, attempt login."""
    await page.goto("https://www.linkedin.com/feed/", wait_until="networkidle", timeout=30000)
    if "feed" in page.url:
        return True  # Already logged in via cookies

    # Need to log in
    await page.goto("https://www.linkedin.com/login", wait_until="networkidle")
    await page.fill("#username", config.LINKEDIN_EMAIL)
    await page.fill("#password", config.LINKEDIN_PASSWORD)
    await page.click('[type=submit]')
    await page.wait_for_load_state("networkidle", timeout=15000)

    if "feed" in page.url or "checkpoint" not in page.url:
        # Save cookies for next time
        cookies = await context.cookies()
        with open(str(config.LINKEDIN_COOKIES_FILE), "w") as f:
            json.dump(cookies, f)
        return True
    return False  # Login failed or requires 2FA


async def create_post(content: str) -> dict:
    """Create a LinkedIn text post."""
    pw, browser, context, page = await _get_page()
    try:
        if not await _login_if_needed(page, context):
            return {"success": False, "error": "LinkedIn login failed – may need 2FA. Check your cookies file."}

        # Click "Start a post"
        await page.click('[data-control-name="share.share_box_feed_create"]', timeout=10000)
        await asyncio.sleep(1)
        # Type content
        editor = page.locator('.ql-editor').first
        await editor.click()
        await editor.fill(content)
        await asyncio.sleep(0.5)
        # Post
        await page.click('[data-control-name="share.post"]', timeout=10000)
        await page.wait_for_load_state("networkidle", timeout=15000)
        return {"success": True, "message": "Post published successfully"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        await browser.close()
        await pw.stop()


async def search_people(keywords: str, connection_degree: str = "2nd") -> dict:
    """Search LinkedIn for people matching keywords."""
    from urllib.parse import quote_plus
    pw, browser, context, page = await _get_page()
    try:
        if not await _login_if_needed(page, context):
            return {"success": False, "error": "LinkedIn login failed"}

        url = (
            f"https://www.linkedin.com/search/results/people/"
            f"?keywords={quote_plus(keywords)}&network=%5B%22{connection_degree[0]}%22%5D"
        )
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        # Extract results
        results = await page.evaluate("""() => {
            const cards = Array.from(document.querySelectorAll('.entity-result__item'));
            return cards.slice(0, 10).map(card => ({
                name: card.querySelector('.entity-result__title-text')?.innerText?.trim() || '',
                headline: card.querySelector('.entity-result__primary-subtitle')?.innerText?.trim() || '',
                location: card.querySelector('.entity-result__secondary-subtitle')?.innerText?.trim() || '',
                profile_url: card.querySelector('a.app-aware-link')?.href || '',
            }));
        }""")
        return {"success": True, "results": results}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        await browser.close()
        await pw.stop()


async def get_profile_info(profile_url: str) -> dict:
    """Scrape a LinkedIn profile for name, headline, about, and recent activity."""
    pw, browser, context, page = await _get_page()
    try:
        if not await _login_if_needed(page, context):
            return {"success": False, "error": "LinkedIn login failed"}

        await page.goto(profile_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)
        info = await page.evaluate("""() => ({
            name: document.querySelector('h1')?.innerText?.trim() || '',
            headline: document.querySelector('.text-body-medium.break-words')?.innerText?.trim() || '',
            about: document.querySelector('#about ~ .pvs-list__outer-container .visually-hidden')?.innerText?.trim() || '',
        })""")
        return {"success": True, **info}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        await browser.close()
        await pw.stop()


async def send_connection_request(profile_url: str, message: str = "") -> dict:
    """Send a LinkedIn connection request with an optional note."""
    pw, browser, context, page = await _get_page()
    try:
        if not await _login_if_needed(page, context):
            return {"success": False, "error": "LinkedIn login failed"}

        await page.goto(profile_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(1)

        # Click Connect button
        try:
            await page.click('[aria-label*="Connect"]', timeout=5000)
        except Exception:
            # Try via "More" dropdown
            await page.click('[aria-label*="More actions"]', timeout=5000)
            await page.click('[aria-label*="Connect"]', timeout=5000)

        if message:
            await page.click('[aria-label="Add a note"]', timeout=5000)
            await page.fill('textarea[name="message"]', message)

        await page.click('[aria-label="Send now"]', timeout=5000)
        await asyncio.sleep(1)
        return {"success": True, "message": "Connection request sent"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        await browser.close()
        await pw.stop()
