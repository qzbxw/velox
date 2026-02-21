import os
import asyncio
from jinja2 import Template
from playwright.async_api import async_playwright
import io
import logging

logger = logging.getLogger(__name__)

# Path to templates
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")

_playwright = None
_browser = None
_browser_lock = asyncio.Lock()
_render_semaphore = asyncio.Semaphore(3)


async def _get_browser():
    global _playwright, _browser
    async with _browser_lock:
        if _browser is not None and _browser.is_connected():
            return _browser
        if _playwright is None:
            _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        return _browser

async def render_html_to_image(template_name: str, data: dict, width: int = 800, height: int = 800) -> io.BytesIO:
    """
    Renders an HTML template with Jinja2 and takes a screenshot using Playwright.
    """
    template_path = os.path.join(TEMPLATE_DIR, template_name)
    with open(template_path, "r", encoding="utf-8") as f:
        template_html = f.read()
    
    # Render HTML with data
    template = Template(template_html)
    template.globals.update(abs=abs, min=min, max=max)
    rendered_html = template.render(**data)
    
    last_error = None
    for attempt in range(2):
        context = None
        try:
            async with _render_semaphore:
                browser = await _get_browser()
                context = await browser.new_context(
                    viewport={"width": width, "height": height},
                    device_scale_factor=2,  # Higher quality (Retina)
                )
                page = await context.new_page()

                # Set content and wait until styles/assets are applied.
                await page.set_content(rendered_html, wait_until="domcontentloaded", timeout=15000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    # networkidle is best-effort due to CDN/font calls.
                    pass
                await page.wait_for_timeout(250)

                image_bytes = await page.screenshot(type="png", full_page=False)
                return io.BytesIO(image_bytes)
        except Exception as e:
            last_error = e
            logger.warning("Image render attempt %s failed: %s", attempt + 1, e)
            # Force browser recreation on retry.
            async with _browser_lock:
                global _browser
                if _browser is not None:
                    try:
                        await _browser.close()
                    except Exception:
                        pass
                _browser = None
            await asyncio.sleep(0.2)
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass
    raise RuntimeError(f"Failed to render image {template_name}: {last_error}")
