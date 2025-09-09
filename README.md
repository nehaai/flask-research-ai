<<<<<<< HEAD
# flask-research-ai
Deep Reseach AI Project
=======
# Deep Research App

A Flask-based research assistant that:

* Scrapes and extracts text from blogs, news, and academic sites using **Firecrawl** (with fallback to **Trafilatura**).
* Synthesizes structured research reports with inline citations using **OpenAI GPT models**.
* Provides a simple web interface to enter a topic and seed URLs.

---

## Features

* **Firecrawl integration** → batch extract and per-URL scrape.
* **Local fallback with Trafilatura** → ensures robust scraping.
* **OpenAI synthesis** → generates research reports with citations and references.
* **Markdown + HTML output** → reports are saved in Markdown and rendered as HTML.
* **Flask UI** → simple form to input topic, number of URLs, character limits, and optional seed URLs.

---

## Requirements

* Python 3.10+
* Install dependencies:

  ```bash
  pip install flask python-dotenv firecrawl openai markdown httpx trafilatura
  ```
* Create a `.env` file in the project root:

  ```env
  OPENAI_API_KEY=your-openai-key
  FIRECRAWL_API_KEY=your-firecrawl-key
  FLASK_SECRET_KEY=dev-secret
  ```

---

## Usage

Start the Flask app:

```bash
python app.py
```

Then open [http://localhost:5001](http://localhost:5001) in your browser.

1. Enter a research topic (e.g., *Latest developments in AI*).
2. Optionally add seed URLs (full article links, not just blog homepages).
3. Adjust max URLs and per-page character limit if needed.
4. Click **Run research** to generate a structured report with citations.

---

## Request Lifecycle

Here’s how a request flows through the app:

```
Browser form → /research (POST)
      │
      ├─ Normalize user inputs (topic, URLs)
      │
      ├─ FirecrawlApp.extract(urls)   # batch extract
      │       └─ If missing text → FirecrawlApp.scrape(url)
      │
      ├─ If Firecrawl returns nothing:
      │       └─ Trafilatura.fetch_url + extract()  # local fallback
      │
      ├─ If still empty → flash error (“Could not scrape any content”)
      │
      ├─ If pages found:
      │       └─ Build corpus of sources → send to OpenAI Responses API
      │
      ├─ OpenAI synthesizes report with inline citations
      │
      ├─ Markdown report saved + converted to HTML
      │
      └─ Rendered in browser with references
```

---

## Project Structure

```
deep-research/
├── app.py               # Flask app
├── templates/
│   ├── index.html       # Form UI
│   └── result.html      # Report view
├── .env                 # API keys
└── README.md            # This file
```

---

## Example Prompt to OpenAI

```text
You are an expert research writer.

TOPIC:
Latest developments in AI

CORPUS (numbered sources follow the format "[n] title — url"):
[1] Example Blog — https://example.com/article
Article content here...

TASK:
1) Produce a clear, well-structured research report.
2) Include: overview, key findings, concepts, case studies, trends, risks, and outlook.
3) Use inline citations like [1], [2].
4) End with a References section.
```

---

## Notes

* For best results, provide **full article URLs**, not just `/blog` homepages.
* Firecrawl API behavior depends on your plan — if `extract()` fails, the app will automatically fall back to `scrape()` or Trafilatura.
* Some sites may block scraping or require headers → you can enhance with `httpx` headers if needed.
>>>>>>> e252da5 (Initial commit: Flask research app)
