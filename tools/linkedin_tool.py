"""
LinkedIn tool via Playwright automation.

NOTE ON RELIABILITY:
LinkedIn actively detects headless browsers and changes their DOM frequently.
This implementation uses current (2024-2025) selectors and basic stealth settings,
but may require periodic manual cookie refresh when LinkedIn flags the account.

To refresh authentication:
  1. Run: python scripts/linkedin_auth.py
  2. Complete the login in the browser window that opens
  3. Cookies are saved to data/linkedin_cookies.json automatically

If you see CAPTCHA or 2FA errors, run the auth script above.
"""
import json
import asyncio
from pathlib import Path
import config

# Stealth init script injected into every page to hide automation signals
_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
window.chrome = {runtime: {}};
"""

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


async def _get_page():
    """Return an authenticated Playwright page with stealth settings."""
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    context = await browser.new_context(
        user_agent=_UA,
        viewport={"width": 1280, "height": 800},
        locale="en-US",
    )
    await context.add_init_script(_STEALTH_SCRIPT)

    cookies_file = config.LINKEDIN_COOKIES_FILE
    if Path(str(cookies_file)).exists():
        with open(str(cookies_file)) as f:
            try:
                await context.add_cookies(json.load(f))
            except Exception:
                pass  # Corrupt cookie file – proceed without cookies

    page = await context.new_page()
    return pw, browser, context, page


async def _check_logged_in(page) -> bool:
    """Return True if current page shows the LinkedIn feed (i.e. we're logged in)."""
    try:
        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(1)
        # Feed page has the global nav; login page has #username field
        is_login_page = await page.query_selector("#username")
        return is_login_page is None
    except Exception:
        return False


async def _login(page, context) -> bool:
    """Attempt credential-based login. Returns True on success."""
    if not config.LINKEDIN_EMAIL or not config.LINKEDIN_PASSWORD:
        return False
    try:
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=20000)
        await page.fill("#username", config.LINKEDIN_EMAIL)
        await page.fill("#password", config.LINKEDIN_PASSWORD)
        await page.click('[type=submit]')
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        await asyncio.sleep(2)

        if "checkpoint" in page.url or "challenge" in page.url:
            return False  # 2FA or CAPTCHA required

        if "feed" in page.url or "/in/" in page.url:
            cookies = await context.cookies()
            Path(str(config.LINKEDIN_COOKIES_FILE)).parent.mkdir(parents=True, exist_ok=True)
            with open(str(config.LINKEDIN_COOKIES_FILE), "w") as f:
                json.dump(cookies, f)
            return True
    except Exception:
        pass
    return False


async def _ensure_logged_in(page, context) -> tuple[bool, str]:
    """Ensure we're logged in. Returns (success, error_message)."""
    if await _check_logged_in(page):
        return True, ""
    if await _login(page, context):
        return True, ""
    return False, (
        "LinkedIn login failed. This usually means:\n"
        "• Saved cookies have expired\n"
        "• LinkedIn requires 2FA or CAPTCHA\n\n"
        "Fix: run 'python scripts/linkedin_auth.py' on the Mac mini to re-authenticate."
    )


async def create_post(content: str) -> dict:
    """Create a LinkedIn text post."""
    pw, browser, context, page = await _get_page()
    try:
        ok, err = await _ensure_logged_in(page, context)
        if not ok:
            return {"success": False, "error": err}

        # Navigate to feed for the post box
        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(2)

        # Try multiple selectors for "Start a post" button (LinkedIn changes these)
        post_btn_selectors = [
            "button.share-box-feed-entry__trigger",
            "[data-test-id='share-box']",
            "button[aria-label*='post']",
            "button[aria-label*='Post']",
        ]
        clicked = False
        for sel in post_btn_selectors:
            try:
                await page.click(sel, timeout=3000)
                clicked = True
                break
            except Exception:
                continue

        if not clicked:
            # Try clicking on the "Start a post" text area directly
            try:
                await page.click("div.share-box-feed-entry__closed-share-box", timeout=5000)
                clicked = True
            except Exception:
                pass

        if not clicked:
            return {"success": False, "error": "Could not find 'Start a post' button. LinkedIn DOM may have changed."}

        await asyncio.sleep(1)

        # Type content in the post editor
        editor_selectors = [
            "div.ql-editor",
            "div[role='textbox']",
            "div[data-placeholder*='post']",
        ]
        for sel in editor_selectors:
            try:
                editor = page.locator(sel).first
                await editor.click(timeout=3000)
                await editor.fill(content)
                break
            except Exception:
                continue
        else:
            return {"success": False, "error": "Could not find post editor. LinkedIn DOM may have changed."}

        await asyncio.sleep(0.5)

        # Click the Post button
        post_btn_selectors = [
            "button.share-creation-state__main-cta-button",
            "button[aria-label='Post']",
            "button.share-actions__primary-action",
        ]
        for sel in post_btn_selectors:
            try:
                await page.click(sel, timeout=3000)
                await asyncio.sleep(2)
                return {"success": True, "message": "Post published successfully"}
            except Exception:
                continue

        return {"success": False, "error": "Could not find 'Post' submit button. LinkedIn DOM may have changed."}

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
        ok, err = await _ensure_logged_in(page, context)
        if not ok:
            return {"success": False, "error": err}

        degree_code = "F" if connection_degree.startswith("1") else "S" if connection_degree.startswith("2") else "O"
        url = (
            f"https://www.linkedin.com/search/results/people/"
            f"?keywords={quote_plus(keywords)}&network=%5B%22{degree_code}%22%5D"
        )
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # Try multiple result container selectors
        results = await page.evaluate("""() => {
            // Try both old and new class names
            const selectors = [
                '.entity-result__item',
                '.reusable-search__result-container',
                '[data-view-name="search-entity-result-universal-template"]',
            ];
            let cards = [];
            for (const sel of selectors) {
                cards = Array.from(document.querySelectorAll(sel));
                if (cards.length > 0) break;
            }
            return cards.slice(0, 10).map(card => ({
                name: (
                    card.querySelector('.entity-result__title-text a span[aria-hidden="true"]') ||
                    card.querySelector('.entity-result__title-text') ||
                    card.querySelector('span[aria-hidden="true"]')
                )?.innerText?.trim() || '',
                headline: (
                    card.querySelector('.entity-result__primary-subtitle') ||
                    card.querySelector('.t-14.t-black.t-normal')
                )?.innerText?.trim() || '',
                location: card.querySelector('.entity-result__secondary-subtitle')?.innerText?.trim() || '',
                profile_url: (card.querySelector('a.app-aware-link') || card.querySelector('a[href*="/in/"]'))?.href || '',
            })).filter(r => r.name || r.profile_url);
        }""")
        return {"success": True, "results": results, "count": len(results)}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        await browser.close()
        await pw.stop()


async def get_profile_info(profile_url: str) -> dict:
    """Scrape a LinkedIn profile for name, headline, and about."""
    pw, browser, context, page = await _get_page()
    try:
        ok, err = await _ensure_logged_in(page, context)
        if not ok:
            return {"success": False, "error": err}

        await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        info = await page.evaluate("""() => ({
            name: (document.querySelector('h1.text-heading-xlarge') || document.querySelector('h1'))?.innerText?.trim() || '',
            headline: document.querySelector('.text-body-medium.break-words')?.innerText?.trim() || '',
            about: (
                document.querySelector('section[data-section="about"] .full-width') ||
                document.querySelector('#about ~ .pvs-list__outer-container span[aria-hidden="true"]')
            )?.innerText?.trim() || '',
            location: document.querySelector('.text-body-small.inline.t-black--light.break-words')?.innerText?.trim() || '',
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
        ok, err = await _ensure_logged_in(page, context)
        if not ok:
            return {"success": False, "error": err}

        await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        # Try direct Connect button first, then via More actions dropdown
        connected = False
        connect_selectors = [
            'button[aria-label*="Invite"][aria-label*="connect"]',
            'button[aria-label*="Connect with"]',
            'main button:has-text("Connect")',
        ]
        for sel in connect_selectors:
            try:
                await page.click(sel, timeout=4000)
                connected = True
                break
            except Exception:
                continue

        if not connected:
            # Try via "More" dropdown
            try:
                more_selectors = [
                    'button[aria-label*="More actions"]',
                    'button:has-text("More")',
                ]
                for sel in more_selectors:
                    try:
                        await page.click(sel, timeout=3000)
                        break
                    except Exception:
                        continue
                await asyncio.sleep(0.5)
                await page.click('div[aria-label*="Connect"]', timeout=3000)
                connected = True
            except Exception:
                pass

        if not connected:
            return {"success": False, "error": "Could not find Connect button. Profile may already be connected, or LinkedIn DOM changed."}

        await asyncio.sleep(1)

        if message:
            try:
                await page.click('[aria-label="Add a note"]', timeout=4000)
                await page.fill('textarea[name="message"]', message[:300])
                await asyncio.sleep(0.3)
            except Exception:
                pass  # Note field not available (e.g. profile requires follow first)

        # Send
        send_selectors = [
            'button[aria-label="Send now"]',
            'button[aria-label="Send invitation"]',
            'button:has-text("Send")',
        ]
        for sel in send_selectors:
            try:
                await page.click(sel, timeout=4000)
                await asyncio.sleep(1)
                return {"success": True, "message": "Connection request sent"}
            except Exception:
                continue

        return {"success": False, "error": "Could not click Send button. LinkedIn DOM may have changed."}

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        await browser.close()
        await pw.stop()
