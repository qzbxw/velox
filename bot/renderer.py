import os
import asyncio
from jinja2 import Template
from playwright.async_api import async_playwright
import io

# Path to templates
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")

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
    
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=2, # Higher quality (Retina)
        )
        page = await context.new_page()
        
        # Set content
        await page.set_content(rendered_html)
        
        # Wait for any network calls (like Tailwind CDN) or fonts
        await page.wait_for_load_state("networkidle")
        
        # Take screenshot
        image_bytes = await page.screenshot(type="png", full_page=False)
        
        await browser.close()
        
        return io.BytesIO(image_bytes)