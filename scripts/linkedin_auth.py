"""
LinkedIn authentication helper.

Run this when LinkedIn cookies expire or when 2FA / CAPTCHA is triggered.
Opens a visible (non-headless) browser so you can log in manually, then
saves the cookies for Dennis to use.

Usage:
    python scripts/linkedin_auth.py
"""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

import config


async def main():
    from playwright.async_api import async_playwright

    print("Opening a visible browser for LinkedIn login...")
    print("Log in manually, complete any 2FA/CAPTCHA, then press Enter here.\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)  # Visible!
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()
        await page.goto("https://www.linkedin.com/login")

        print("Browser is open. Log in to LinkedIn now.")
        print("Once you see the LinkedIn feed, come back here and press Enter.")
        input("\nPress Enter when logged in...")

        cookies = await context.cookies()
        config.LINKEDIN_COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(str(config.LINKEDIN_COOKIES_FILE), "w") as f:
            json.dump(cookies, f)

        await browser.close()

    print(f"\n✅ Cookies saved to: {config.LINKEDIN_COOKIES_FILE}")
    print("Dennis will use these cookies for LinkedIn automation.")
    print("They typically last several weeks before needing a refresh.")


if __name__ == "__main__":
    asyncio.run(main())
