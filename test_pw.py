import asyncio
from playwright.async_api import async_playwright
import logging
import sys
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_pw():
    try:
        async with async_playwright() as p:
            print("Playwright launched.")
            browser = await p.chromium.launch(headless=True)
            print("Browser launched.")
            page = await browser.new_page()
            await page.goto("https://farside.co.uk/eth/", timeout=30000)
            print(f"Page title: {await page.title()}")
            content = await page.content()
            print(f"Content length: {len(content)}")
            await browser.close()
    except Exception as e:
        logger.error(f"Playwright failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_pw())
