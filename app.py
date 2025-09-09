import os
import re
from pathlib import Path
from typing import Dict, Any, List
from urllib.parse import urlparse

from flask import Flask, render_template, request, redirect, url_for, flash
from dotenv import load_dotenv
from firecrawl import FirecrawlApp
from openai import OpenAI
import markdown as md

import httpx
import trafilatura

# ---------- ENV ----------
load_dotenv(dotenv_path=Path.cwd()/".env")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret")


# ---------- Helpers ----------
def sanitize_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name.strip()) or "report"

def origin(url: str) -> str:
    try:
        u = urlparse(url)
        return u.netloc or url
    except Exception:
        return url

def parse_urls_csv(s: str) -> List[str]:
    # Split by comma, newline, or whitespace
    parts = re.split(r"[,\s]+", s.strip())
    return [p for p in parts if p]

# ---------- Firecrawl via extract ----------
def firecrawl_fetch_pages_with_extract(
    topic: str,
    urls: List[str],
    per_page_char_limit: int = 8000,
) -> List[Dict[str, str]]:
    """
    Firecrawl v3.4.0 compatible:
      1) try extract(urls=urls)
      2) if a row has no text, fall back to scrape(url)
    Returns [{url, title, text}, ...]
    """
    fc_key = os.getenv("FIRECRAWL_API_KEY")
    if not fc_key:
        raise RuntimeError("FIRECRAWL_API_KEY missing in .env")

    app_fc = FirecrawlApp(api_key=fc_key)
    if not urls:
        return []

    # ---- 1) batch extract ----
    try:
        res = app_fc.extract(urls=urls)  # <-- no 'formats' kwarg on your version
    except Exception as e:
        print("extract() failed:", e)
        res = None

    # normalize rows from extract
    rows: List[Dict[str, Any]] = []
    if isinstance(res, list):
        rows = [r if isinstance(r, dict) else {"url": str(r)} for r in res]
    elif isinstance(res, dict):
        if isinstance(res.get("data"), list):
            rows = [r if isinstance(r, dict) else {} for r in res["data"]]
        elif isinstance(res.get("results"), list):
            rows = [r if isinstance(r, dict) else {} for r in res["results"]]
        elif isinstance(res.get("result"), list):
            rows = [r if isinstance(r, dict) else {} for r in res["result"]]

    items: List[Dict[str, str]] = []

    def _append_if_text(url: str, title: str, text: str):
        text = (text or "").strip()
        if url and text:
            items.append({
                "url": url,
                "title": (title or "").strip() or origin(url),
                "text": text[: per_page_char_limit] + ("…" if len(text) > per_page_char_limit else "")
            })
            return True
        return False

    # ---- collect from extract; fall back to scrape when needed ----
    for row in rows:
        url = (row.get("url") or row.get("sourceUrl") or row.get("link") or row.get("pageUrl") or "").strip()
        title = (row.get("title") or "").strip()

        text = (
            row.get("markdown")
            or row.get("content")
            or row.get("text")
            or row.get("html")
            or ""
        )

        if _append_if_text(url, title, text):
            continue

        # Fallback to per-URL scrape
        if url:
            try:
                s = app_fc.scrape(url)
                d = s if isinstance(s, dict) else {}
                data = d.get("data") if isinstance(d.get("data"), dict) else d
                title2 = (data.get("title") or title or "").strip() if isinstance(data, dict) else title
                text2 = ""
                if isinstance(data, dict):
                    text2 = (
                        data.get("content")
                        or data.get("markdown")
                        or data.get("text")
                        or data.get("html")
                        or ""
                    )
                if _append_if_text(url, title2, text2):
                    continue
                else:
                    print(f"[skip] No text from extract/scrape for {url}")
            except Exception as e:
                print(f"[skip] scrape failed for {url}: {e}")
        else:
            print("[skip] row without URL in extract response")

    return items


# ---------- OpenAI synth ----------
def enhance_with_openai(topic: str, items: List[Dict[str, str]]) -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing in .env")

    client = OpenAI(api_key=key)

    corpus_lines = []
    for i, it in enumerate(items, 1):
        url = it.get("url",""); title = it.get("title","") or origin(url); text = it.get("text","")
        if url and text:
            corpus_lines.append(f"[{i}] {title} — {url}\n{text}\n")
    corpus = "\n".join(corpus_lines) if corpus_lines else "No pages scraped."

    prompt = f"""
You are an expert research writer.

TOPIC:
{topic}

CORPUS (numbered sources follow the format "[n] title — url"):
{corpus}

TASK:
1) Produce a clear, well-structured research report on the topic.
2) Include: overview, key findings, important concepts, examples/case studies, current trends, risks/limitations, and a short future outlook.
3) Use inline citations like [1], [2] that refer to the numbered sources above.
4) End with a "References" section listing the source number, title (or domain), and URL.

Keep it factual, concise, and readable. If any claims are speculative, mark them as such.
"""
    resp = client.responses.create(model="gpt-4.1-mini", input=prompt)
    return resp.output_text

# ---------- Direct fetch + trafilatura (not used in main flow) ----------
def direct_fetch_pages_with_trafilatura(
    urls: List[str],
    per_page_char_limit: int = 8000,
) -> List[Dict[str, str]]:
    """
    Fetch pages directly (no Firecrawl) and extract main content with trafilatura.
    Uses trafilatura.fetch_url() which handles redirects, headers, gzip, etc.
    """
    items: List[Dict[str, str]] = []

    for url in urls:
        try:
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                print(f"[direct] fetch failed or empty for {url}")
                continue

            text = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=False,
                with_metadata=True,
                url=url,  # help trafilatura with canonical/metadata
                no_fallback=False,
            )
            if not text:
                print(f"[direct] extract returned no text for {url}")
                continue

            # Try to get a title from metadata
            # Try to get a title from metadata
            meta = trafilatura.extract_metadata(downloaded)
            title = ""

            if meta:
                if isinstance(meta, dict):
                    title = meta.get("title", "").strip()
                else:
                    # Metadata object, use getattr safely
                    title = getattr(meta, "title", "") or ""
                    title = title.strip()

            if text:
                items.append({
                    "url": url,
                    "title": title or origin(url),
                    "text": text[:per_page_char_limit] + ("…" if len(text) > per_page_char_limit else ""),
                })
        except Exception as e:
            print(f"[direct] failed for {url}: {e}")

    return items



# ---------- Routes ----------
@app.get("/")
def index():
    return render_template("index.html")

@app.post("/research")
def research():
    topic = request.form.get("topic","").strip()
    urls_csv = request.form.get("urls","").strip()
    max_urls = int(request.form.get("max_urls","8") or "8")
    per_page_limit = int(request.form.get("per_page_limit","8000") or "8000")

    if not topic:
        flash("Please enter a topic.")
        return redirect(url_for("index"))

    urls_override = parse_urls_csv(urls_csv)
    urls_override = [normalize_url(u) for u in parse_urls_csv(urls_csv)]

    # If user gave no URLs, fallback to defaults
    urls = urls_override[:max_urls] if urls_override else [
        "https://openai.com/blog",
        "https://huggingface.co/blog",
        "https://ai.googleblog.com/",
        "https://www.deeplearning.ai/the-batch/",
        "https://arxiv.org/list/cs.AI/recent",
        "https://www.anthropic.com/news",
    ][:max_urls]

    print("Normalized URLs:", urls)

    # Fetch pages (Firecrawl first)
    items = firecrawl_fetch_pages_with_extract(topic, urls, per_page_char_limit=per_page_limit)

    # Fallback to local extractor if Firecrawl returns nothing
    if not items:
        print("→ Firecrawl returned no content; falling back to local extractor (trafilatura)…")
        items = direct_fetch_pages_with_trafilatura(urls, per_page_char_limit=per_page_limit)

    if not items:
        flash("Could not scrape any content. Try different article URLs.")
        return redirect(url_for("index"))


    report_md = "## Enhanced Research Report\n\n" + enhance_with_openai(topic, items)
    report_html = md.markdown(report_md, extensions=["extra","sane_lists"])
    return render_template("result.html", topic=topic, report_html=report_html, report_md=report_md)

def normalize_url(u: str) -> str:
    # trim whitespace + smart quotes
    s = u.strip().strip("‘’“”\"'")
    # replace common unicode dashes with ASCII hyphen
    s = (s
         .replace("\u2013", "-")   # en dash
         .replace("\u2014", "-")   # em dash
         .replace("\u2212", "-")   # minus sign
        )
    return s


if __name__ == "__main__":
    app.run(debug=True, port=5001)
