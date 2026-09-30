import pytest

from app.tools import web_search as ws

FIXTURE_HTML = """
<html><body>
<div class="g">
  <a href="https://example.com/one"><h3>Example One</h3></a>
  <span class="VwiC3b">This is the first snippet about example one.</span>
</div>
<div class="g">
  <a href="https://example.com/two"><h3>Example Two</h3></a>
  <span class="VwiC3b">This is the second snippet about example two.</span>
</div>
</body></html>
"""

CAPTCHA_HTML = "<html><body>Our systems have detected unusual traffic from your network.</body></html>"


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text
        self.raw = _FakeRaw(text.encode("utf-8"))

    def raise_for_status(self):
        pass


class _FakeRaw:
    def __init__(self, data: bytes):
        self._data = data

    def read(self, n, decode_content=True):
        return self._data[:n]


def test_google_search_parses_results(monkeypatch):
    monkeypatch.setattr(ws.requests, "get", lambda *a, **k: _FakeResponse(FIXTURE_HTML))
    results = ws._google_search("anything", num_results=2, timeout_s=5)
    assert len(results) == 2
    assert results[0]["title"] == "Example One"
    assert results[0]["url"] == "https://example.com/one"
    assert "first snippet" in results[0]["snippet"]


def test_google_search_raises_on_captcha(monkeypatch):
    monkeypatch.setattr(ws.requests, "get", lambda *a, **k: _FakeResponse(CAPTCHA_HTML))
    with pytest.raises(ws.WebSearchBlockedError):
        ws._google_search("anything", num_results=2, timeout_s=5)


def test_web_search_falls_back_to_snippet_when_excerpt_fetch_fails(monkeypatch):
    monkeypatch.setattr(ws.requests, "get", lambda *a, **k: _FakeResponse(FIXTURE_HTML))

    def _raise(*a, **k):
        raise ws.requests.RequestException("boom")

    monkeypatch.setattr(ws, "_excerpt", lambda url, lines, timeout_s: "")
    results = ws.web_search("anything", num_results=2, lines_per_result=6, timeout_s=5)
    assert results[0]["excerpt"] == results[0]["snippet"]
