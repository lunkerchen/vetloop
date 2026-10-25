"""Render proposal/deck.html to a 16:9 PDF with the system Chrome.

Run: python3 proposal/render_pdf.py
"""
import os

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(HERE, "deck.html")
OUT = os.path.join(HERE, "vetloop-proposal.pdf")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME, headless=True, timeout=60000)
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    page.goto("file://" + HTML, wait_until="load", timeout=60000)
    page.emulate_media(media="print")
    page.pdf(path=OUT, width="1280px", height="720px", print_background=True,
             margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
    browser.close()

print("saved", OUT)
