#!/usr/bin/env python3
"""Dependency-free smoke tests for the static portfolio."""
from html.parser import HTMLParser
from pathlib import Path
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
        self.headings = []
        self.in_title = False
        self.title = ""

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

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data

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
if not re.search(r'<meta\s+name=["\\']description["\\']\s+content=["\\'][^"\\']{40,}', source, re.I):
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

for href in re.findall(r'href=["\\']#([^"\\']+)', source):
    if href not in parser.ids:
        fail(f"Anchor target does not exist: #{href}")

# Validate external and inline JavaScript syntax using Node.js when available.
if subprocess.run(["node", "--version"], capture_output=True, text=True).returncode == 0:
    js = ROOT / "assets/js/portfolio-enhancements.js"
    result = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
    if result.returncode:
        fail("External JavaScript syntax error: " + result.stderr.strip())
    inline_scripts = re.findall(r"<script(?:\\s[^>]*)?>([\\s\\S]*?)</script>", source, re.I)
    for index, script in enumerate(inline_scripts):
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

if ERRORS:
    print("Portfolio checks failed:")
    for error in ERRORS:
        print(" - " + error)
    sys.exit(1)

print(f"Portfolio smoke tests passed: {len(parser.references)} local/external references inspected; {len(parser.ids)} IDs checked.")
