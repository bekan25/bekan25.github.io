#!/usr/bin/env python3
"""Dependency-free smoke tests for the static portfolio."""
from html.parser import HTMLParser
from pathlib import Path
import json
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ERRORS = []

class PortfolioParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.references = []
        self.images_without_alt = []
        self.in_title = False
        self.title = ""
        self.inline_scripts = []
        self.in_script = False
        self.script_type = ""
        self.script_buffer = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag in {"a", "link", "script", "img"}:
            key = "src" if tag in {"script", "img"} else "href"
            value = attrs.get(key)
            if value:
                self.references.append((tag, value))
        if tag == "img" and "alt" not in attrs:
            self.images_without_alt.append(attrs.get("src", "(unknown image)"))
        if tag == "title":
            self.in_title = True
        if tag == "script":
            self.in_script = True
            self.script_type = attrs.get("type", "").lower()
            self.script_buffer = []

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag == "script" and self.in_script:
            if self.script_type != "application/ld+json":
                self.inline_scripts.append("".join(self.script_buffer))
            self.in_script = False
            self.script_type = ""

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.in_script:
            self.script_buffer.append(data)

def fail(message):
    ERRORS.append(message)

main = ROOT / "index.html"
if not main.is_file():
    fail("index.html is missing")
    sys.exit(1)

source = main.read_text(encoding="utf-8")
parser = PortfolioParser()
parser.feed(source)
parser.close()

if not parser.title.strip():
    fail("The page title is empty")
if not re.search(r"<meta\s+name=['\"]description['\"]\s+content=['\"][^'\"]{40,}", source, re.I):
    fail("A meaningful meta description is missing")
if 'rel="canonical"' not in source:
    fail("Canonical URL is missing")
if len(parser.ids) != len(set(parser.ids)):
    fail("Duplicate HTML id attributes found")
if parser.images_without_alt:
    fail("Images missing alt text: " + ", ".join(parser.images_without_alt))

for tag, raw in parser.references:
    value = raw.split("#", 1)[0].split("?", 1)[0]
    if not value or value.startswith(("http://", "https://", "mailto:", "tel:", "data:", "javascript:")):
        continue
    if value.startswith("//"):
        continue
    target = (ROOT / value.lstrip("/")) if value.startswith("/") else (ROOT / value)
    if not target.is_file():
        fail(f"Broken local {tag} reference: {raw}")

for href in re.findall(r"href=['\"]#([^'\"]+)", source):
    if href not in parser.ids:
        fail(f"Anchor target does not exist: #{href}")

if subprocess.run(["node", "--version"], capture_output=True, text=True).returncode == 0:
    js = ROOT / "assets/js/portfolio-enhancements.js"
    result = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
    if result.returncode:
        fail("External JavaScript syntax error: " + result.stderr.strip())
    for index, script in enumerate(parser.inline_scripts):
        if not script.strip():
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8") as handle:
            handle.write(script)
            handle.flush()
            check = subprocess.run(["node", "--check", handle.name], capture_output=True, text=True)
        if check.returncode:
            fail(f"Inline JavaScript block {index + 1} syntax error: {check.stderr.strip()}")
else:
    print("NOTE: Node.js unavailable; JavaScript syntax checks skipped.")


# Cross-page integrity checks: every published HTML page, sitemap entry,
# manifest icon, and service-worker precache asset must resolve in this repo.
html_pages = sorted(ROOT.rglob("*.html"))
for page in html_pages:
    page_parser = PortfolioParser()
    try:
        page_parser.feed(page.read_text(encoding="utf-8"))
        page_parser.close()
    except (OSError, UnicodeError) as exc:
        fail(f"Could not parse {page.relative_to(ROOT)}: {exc}")
        continue
    if len(page_parser.ids) != len(set(page_parser.ids)):
        fail(f"Duplicate HTML id attributes in {page.relative_to(ROOT)}")
    if page_parser.images_without_alt:
        fail(f"Images missing alt text in {page.relative_to(ROOT)}: " + ", ".join(page_parser.images_without_alt))
    for href in re.findall(r"href=['\\\"]#([^'\\\"]+)", page.read_text(encoding="utf-8"), re.I):
        if href not in page_parser.ids:
            fail(f"Anchor target does not exist in {page.relative_to(ROOT)}: #{href}")
    for tag, raw in page_parser.references:
        value = raw.split("#", 1)[0].split("?", 1)[0]
        if not value or value.startswith(("http://", "https://", "mailto:", "tel:", "data:", "javascript:")) or value.startswith("//"):
            continue
        target = (ROOT / value.lstrip("/")) if value.startswith("/") else (page.parent / value)
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            fail(f"Broken local {tag} reference in {page.relative_to(ROOT)}: {raw}")

manifest_path = ROOT / "manifest.webmanifest"
try:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for icon in manifest.get("icons", []):
        icon_path = icon.get("src", "")
        target = ROOT / icon_path.lstrip("/")
        if not icon_path or not target.is_file():
            fail(f"Manifest icon is missing: {icon_path or '(empty src)'}")
except (OSError, json.JSONDecodeError) as exc:
    fail(f"Invalid web app manifest: {exc}")

sitemap_path = ROOT / "sitemap.xml"
try:
    sitemap = ET.parse(sitemap_path).getroot()
    for loc in sitemap.findall(".//{*}loc"):
        parsed = urlparse(loc.text or "")
        if parsed.netloc and parsed.netloc != "bekan25.github.io":
            fail(f"Unexpected external sitemap host: {parsed.netloc}")
            continue
        target_path = parsed.path.strip("/") or "index.html"
        if not (ROOT / target_path).is_file():
            fail(f"Sitemap URL does not resolve to a local page: {loc.text}")
except (OSError, ET.ParseError) as exc:
    fail(f"Invalid sitemap.xml: {exc}")

worker_path = ROOT / "service-worker.js"
if worker_path.is_file():
    worker = worker_path.read_text(encoding="utf-8")
    core = re.search(r"const\\s+CORE_ASSETS\\s*=\\s*\\[(.*?)\\]", worker, re.S)
    if not core:
        fail("Service worker CORE_ASSETS list is missing")
    else:
        for asset in re.findall(r"['\\\"](/[^'\\\"]+)['\\\"]", core.group(1)):
            if not (ROOT / asset.lstrip("/")).is_file():
                fail(f"Service worker precache asset is missing: {asset}")

for css_name in ("assets/css/portfolio.css", "assets/css/premium.css"):
    css_path = ROOT / css_name
    if css_path.is_file():
        css = re.sub(r"/\\*[\\s\\S]*?\\*/", "", css_path.read_text(encoding="utf-8"))
        css = re.sub(r"""(['\\\"]).*?\\1""", "", css)
        if css.count("{") != css.count("}"):
            fail(f"Unbalanced CSS braces in {css_name}")

# The contact flow must remain honest and client-side validated.
if 'id="contact-form"' not in source or 'id="contact-email"' not in source or 'required' not in source:
    fail("Contact form or required-field validation markup is missing")

if ERRORS:
    print("Portfolio checks failed:")
    for error in ERRORS:
        print(" - " + error)
    sys.exit(1)

print(f"Portfolio smoke tests passed: {len(parser.references)} references inspected; {len(parser.ids)} IDs checked.")
