"""Custom web search tool: scrapes Google's result page directly and pulls a short excerpt
from each of the top results, per the user's explicit request.

Caveat worth keeping visible rather than burying: scraping google.com/search without the
official Custom Search JSON API is against Google's Terms of Service for automated
querying, and the HTML structure below is unofficial and will break when Google changes
markup. It's included here because that's what was asked for. If reliability becomes a
problem, swap `_google_search` for a call to the Custom Search JSON API or a provider like
Tavily/SerpAPI -- everything downstream (the excerpt extraction, the tool registration,
the /api/search endpoint) stays the same since they only depend on the return shape.
"""
from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from app.tools.registry import tool

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


class WebSearchError(Exception):
    pass


class WebSearchBlockedError(WebSearchError):
    """Raised when Google served a CAPTCHA/consent interstitial instead of results, so
    callers can degrade gracefully instead of silently returning garbage."""


def _google_search(query: str, num_results: int, timeout_s: int) -> list[dict]:
    resp = requests.get(
        "https://www.google.com/search",
        params={"q": query, "num": max(num_results * 2, 10), "hl": "en"},
        headers=_HEADERS, timeout=timeout_s,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    if soup.find("form", {"action": re.compile("CaptchaRedirect|sorry")}) or "unusual traffic" in resp.text.lower():
        raise WebSearchBlockedError("Google returned a CAPTCHA/consent page instead of search results.")

    results = []
    # Best-effort selectors: Google wraps each organic result in a div with class "g" (or,
    # on newer markup, blocks identifiable by an <h3> heading inside an <a>). We don't rely
    # on exact class names beyond that since they change frequently.
    for block in soup.select("div.g, div[data-sokoban-container]"):
        link_tag = block.find("a", href=True)
        title_tag = block.find("h3")
        if not link_tag or not title_tag:
            continue
        href = link_tag["href"]
        if not href.startswith("http"):
            continue
        snippet_tag = block.find(["span", "div"], class_=re.compile("VwiC3b|IsZvec|st"))
        snippet = snippet_tag.get_text(" ", strip=True) if snippet_tag else ""
        results.append({"title": title_tag.get_text(" ", strip=True), "url": href, "snippet": snippet})
        if len(results) >= num_results:
            break

    if not results:
        raise WebSearchBlockedError(
            "No parseable results -- Google's markup may have changed, or the query was blocked."
        )
    return results


def _excerpt(url: str, lines: int, timeout_s: int) -> str:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout_s, stream=True)
        resp.raise_for_status()
        content = resp.raw.read(500_000, decode_content=True)  # cap page size we bother parsing
        soup = BeautifulSoup(content, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return " ".join(sentences[:lines]).strip()
    except requests.RequestException:
        return ""


def web_search(query: str, num_results: int = 3, lines_per_result: int = 6, timeout_s: int = 10) -> list[dict]:
    results = _google_search(query, num_results, timeout_s)
    for r in results:
        excerpt = _excerpt(r["url"], lines_per_result, timeout_s)
        r["excerpt"] = excerpt or r["snippet"]
    return results


tool("web.search", allowed_agents=["qa", "gst", "insight_reasoner"], timeout_s=30)(web_search)
