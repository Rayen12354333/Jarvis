"""Public web-tool behavior without external network calls."""
from __future__ import annotations

import pytest

from jarvis import web


@pytest.fixture(autouse=True)
def clear_web_caches():
    web._search_web_cached.cache_clear()
    web._read_webpage_cached.cache_clear()
    yield
    web._search_web_cached.cache_clear()
    web._read_webpage_cached.cache_clear()


def test_search_formats_bounded_untrusted_results(monkeypatch, capsys) -> None:
    class FakeDDGS:
        def text(self, query: str, *, max_results: int):
            assert query == "current test fact"
            assert max_results == web.SEARCH_RESULTS
            return [
                {
                    "title": "Official source",
                    "href": "https://example.com/fact",
                    "body": "The current verified fact.",
                }
            ]

    web._search_web_cached.cache_clear()
    monkeypatch.setattr(web, "DDGS", FakeDDGS)

    result = web.search_web("current test fact")

    assert "untrusted excerpts" in result
    assert "Official source" in result
    assert "https://example.com/fact" in result
    assert "[web] source 1" in capsys.readouterr().out


def test_private_page_addresses_are_rejected() -> None:
    with pytest.raises(ValueError, match="private"):
        web._validate_public_url("http://127.0.0.1/private")


def test_html_extraction_drops_scripts_and_navigation() -> None:
    title, text = web._extract_readable_text(
        """
        <html><head><title>Useful Page</title><script>ignore me</script></head>
        <body><nav>menu text</nav><main>The researched answer.</main></body></html>
        """,
        "text/html",
    )

    assert title == "Useful Page"
    assert text == "The researched answer."
    assert "ignore me" not in text
    assert "menu text" not in text


def test_search_cache_expires_after_one_minute(monkeypatch) -> None:
    clock = [0.0]
    calls: list[str] = []

    class FakeDDGS:
        def text(self, query: str, *, max_results: int):
            calls.append(query)
            return [{
                "title": f"Update {len(calls)}",
                "href": "https://example.com/current",
                "body": "Changing information",
            }]

    monkeypatch.setattr(web, "DDGS", FakeDDGS)
    monkeypatch.setattr(web, "monotonic", lambda: clock[0])

    first = web.search_web("current information")
    clock[0] = 59.9
    assert web.search_web("current information") == first
    assert calls == ["current information"]
    clock[0] = 60.0
    assert "Update 2" in web.search_web("current information")
    assert len(calls) == 2


def test_page_cache_expires_after_five_minutes(monkeypatch) -> None:
    clock = [0.0]
    calls: list[str] = []

    def download(url):
        calls.append(url)
        return f"Fresh page version {len(calls)}", "text/plain", url

    monkeypatch.setattr(web, "_download_public_page", download)
    monkeypatch.setattr(web, "monotonic", lambda: clock[0])
    url = "https://example.com/current"

    first = web.read_webpage(url)
    clock[0] = 299.9
    assert web.read_webpage(url) == first
    assert calls == [url]
    clock[0] = 300.0
    assert "version 2" in web.read_webpage(url)
    assert len(calls) == 2


def test_expired_time_buckets_remain_memory_bounded(monkeypatch) -> None:
    clock = [0.0]
    monkeypatch.setattr(web, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        web, "_download_public_page", lambda url: ("A page", "text/plain", url)
    )

    for index in range(100):
        clock[0] = index * web.PAGE_CACHE_TTL_SECONDS
        web.read_webpage("https://example.com/current")

    assert web._read_webpage_cached.cache_info().currsize == 64
