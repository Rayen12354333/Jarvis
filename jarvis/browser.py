"""Bounded, visible browser actions; never execute model-provided scripts.

Page content is evidence, not instructions. This controller reads only a browser
the user has in front and never enables browser or macOS permissions itself.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlsplit

_BROWSERS = {"safari": "Safari", "chrome": "Google Chrome", "google chrome": "Google Chrome"}
_MAX_PAGE_TEXT = 8_000
_FRONTMOST = """use framework "AppKit"
return (current application's NSWorkspace's sharedWorkspace()'s ¬
frontmostApplication()'s localizedName()) as text"""

# No form values, password inputs, cookies, storage, or off-screen DOM text.
_CONTEXT_JS = r"""(() => {
  const visible = el => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 &&
      r.top < innerHeight && r.left < innerWidth && s.visibility !== 'hidden' &&
      s.display !== 'none' && s.opacity !== '0';
  };
  const parts = []; let length = 0, visited = 0;
  const walker = document.createTreeWalker(document.body || document.documentElement,
    NodeFilter.SHOW_TEXT);
  while (walker.nextNode() && length < 8000 && visited++ < 12000) {
    const node = walker.currentNode, el = node.parentElement;
    if (!el || el.closest('script,style,noscript,input,textarea,select,[contenteditable]') ||
        !visible(el)) continue;
    const range = document.createRange(); range.selectNodeContents(node);
    const r = range.getBoundingClientRect();
    if (r.bottom <= 0 || r.right <= 0 || r.top >= innerHeight || r.left >= innerWidth) continue;
    const text = node.textContent.replace(/\s+/g, ' ').trim();
    if (text) { parts.push(text); length += text.length + 1; }
  }
  return JSON.stringify({url: location.href, title: document.title,
    visible_text: parts.join('\n').slice(0, 8000)});
})()"""

_VIDEOS_JS = r"""(() => {
  const allowedHosts = ['youtube.com', 'www.youtube.com', 'm.youtube.com'];
  if (!allowedHosts.includes(location.hostname))
    return JSON.stringify({error: 'This foreground tab is not YouTube.'});
  const selectors = 'ytd-video-renderer, ytd-rich-item-renderer, ' +
    'ytd-compact-video-renderer, yt-lockup-view-model';
  const seen = new Set(), videos = [];
  for (const card of Array.from(document.querySelectorAll(selectors)).slice(0, 300)) {
    if (card.closest('ytd-ad-slot-renderer,ytd-promoted-video-renderer,' +
      'ytd-promoted-sparkles-web-renderer,[is-ad]') ||
      card.querySelector('ytd-ad-slot-renderer,ytd-ad-badge-renderer')) continue;
    const r = card.getBoundingClientRect(), s = getComputedStyle(card);
    if (r.width <= 0 || r.height <= 0 || r.bottom <= 0 || r.right <= 0 ||
      r.top >= innerHeight || r.left >= innerWidth ||
      s.visibility === 'hidden' || s.display === 'none' || s.opacity === '0') continue;
    const a = card.querySelector('a#video-title, a#video-title-link, ' +
      'a.yt-lockup-metadata-view-model__title');
    if (!a) continue;
    let u; try { u = new URL(a.href, location.href); } catch (_) { continue; }
    const id = u.searchParams.get('v');
    if (u.protocol !== 'https:' || !allowedHosts.includes(u.hostname) ||
      u.pathname !== '/watch' || !/^[A-Za-z0-9_-]{11}$/.test(id || '') || seen.has(id)) continue;
    seen.add(id);
    videos.push({url: 'https://www.youtube.com/watch?v=' + id,
      title: (a.getAttribute('title') || a.textContent || 'YouTube video').trim().slice(0, 300),
      top: r.top, left: r.left});
  }
  videos.sort((a, b) => Math.abs(a.top - b.top) < 15 ? a.left - b.left : a.top - b.top);
  return JSON.stringify({url: location.href, videos: videos.slice(0, 50)});
})()"""

_PLAYBACK_JS = r"""(() => {
  const video = document.querySelector('video');
  const adPlaying = Boolean(document.querySelector(
    '.html5-video-player.ad-showing, .html5-video-player.ad-interrupting'));
  if (video && video.paused) {
    try { const p = video.play(); if (p) p.catch(() => {}); } catch (_) {}
  }
  return JSON.stringify({url: location.href,
    playing: Boolean(!adPlaying && video && !video.paused && !video.ended && video.readyState >= 2),
    ad_playing: adPlaying});
})()"""

_SCROLL_JS = r"""(() => {
  const direction = __DIRECTION__, amount = __AMOUNT__, edge = __EDGE__;
  const vertical = direction === 'up' || direction === 'down';
  let target = document.scrollingElement || document.documentElement;
  for (let el = document.elementFromPoint(innerWidth / 2, innerHeight / 2);
       el && el !== document.body; el = el.parentElement) {
    const css = getComputedStyle(el);
    if (vertical && /(auto|scroll)/.test(css.overflowY) && el.scrollHeight > el.clientHeight + 2 ||
        !vertical && /(auto|scroll)/.test(css.overflowX) && el.scrollWidth > el.clientWidth + 2) {
      target = el; break;
    }
  }
  const prop = vertical ? 'scrollTop' : 'scrollLeft';
  const extent = vertical ? target.scrollHeight - target.clientHeight :
    target.scrollWidth - target.clientWidth;
  const before = target[prop], sign = direction === 'up' || direction === 'left' ? -1 : 1;
  const distance = Math.max(80, (vertical ? innerHeight : innerWidth) * 0.16 * amount);
  const goal = edge === 'top' ? 0 : edge === 'bottom' ? extent : before + sign * distance;
  const old = target.style.scrollBehavior; target.style.scrollBehavior = 'auto';
  target[prop] = Math.max(0, Math.min(extent, goal));
  const after = target[prop]; target.style.scrollBehavior = old;
  const boundary = sign > 0 ? after >= extent - 1 : after <= 1;
  return JSON.stringify({before, after, moved: Math.abs(after - before) > 1,
    at_boundary: boundary, direction, edge});
})()"""

_VIDEO_CONTROL_JS = r"""(() => {
  const command = __COMMAND__;
  const hosts = ['youtube.com', 'www.youtube.com', 'm.youtube.com'];
  if (!hosts.includes(location.hostname)) return JSON.stringify({error: 'Use this on YouTube.'});
  if (command === 'skip_ad') {
    const button = Array.from(document.querySelectorAll(
      '.ytp-ad-skip-button, .ytp-skip-ad-button, .ytp-ad-skip-button-modern')).find(el => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && !el.disabled &&
          getComputedStyle(el).visibility !== 'hidden';
      });
    if (!button) return JSON.stringify({sent: false, detail: 'No enabled Skip Ad button yet.'});
    button.click();
    return JSON.stringify({sent: true, detail: 'Clicked the visible Skip Ad button.'});
  }
  const video = document.querySelector('video');
  if (!video) return JSON.stringify({sent: false, detail: 'No video player found.'});
  if (command === 'pause') video.pause();
  else { try { const p = video.play(); if (p) p.catch(() => {}); } catch (_) {} }
  return JSON.stringify({sent: true, paused: video.paused,
    verified: command === 'pause' ? video.paused : !video.paused && video.readyState >= 2});
})()"""


def _web_url(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError("A web URL of at most 4096 characters is required.")
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("The web URL cannot contain spaces or control characters.")
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("The web URL is invalid.") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only complete http or https web URLs are allowed.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Web URLs containing credentials are not allowed.")
    return value


def _youtube_id(value: str) -> str | None:
    try:
        parsed = urlsplit(_web_url(value))
    except ValueError:
        return None
    video_id = parse_qs(parsed.query).get("v", [""])[0]
    if (
        parsed.scheme == "https"
        and parsed.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}
        and parsed.path == "/watch"
        and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id)
    ):
        return video_id
    return None


def _evidence(**data: Any) -> str:
    return json.dumps(
        {"source": "foreground_browser", "untrusted_page_data": True, **data}, ensure_ascii=False
    )


class BrowserController:
    """Deterministic Safari/Chrome actions with bounded subprocess calls.

    ``runner`` follows subprocess.run's signature, allowing tests to avoid all GUI
    side effects. Each AppleScript source is fixed; URLs travel only in argv.
    """

    def __init__(
        self, runner: Callable[..., Any] | None = None, sleep: Callable[[float], None] = time.sleep
    ) -> None:
        self._runner = runner or subprocess.run
        self._sleep = sleep

    def _frontmost(self) -> str:
        # Use a fresh, short-lived query. The voice worker has no AppKit event
        # loop to keep NSWorkspace's application-state notifications current.
        return self._run(_FRONTMOST)

    def _run(self, source: str, *args: str) -> str:
        if sys.platform != "darwin":
            raise RuntimeError("Native browser control is only available on macOS.")
        try:
            completed = self._runner(
                ["osascript", "-e", source, *args],
                capture_output=True,
                text=True,
                timeout=7,
                check=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "Browser control timed out; check the browser or permission prompt."
            ) from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "Browser did not accept the command.").strip()[:600]
            raise RuntimeError(f"Browser command failed: {detail}") from exc
        return completed.stdout.strip()[:24_000]

    def _browser(self, app_name: str | None, *, foreground: bool = True) -> str:
        browser = None
        if app_name:
            browser = _BROWSERS.get(app_name.casefold().strip().removesuffix(".app"))
            if browser is None:
                raise ValueError("Browser control supports Safari or Google Chrome.")
        if foreground or browser is None:
            active = self._frontmost()
            if not foreground:
                return browser or (active if active in set(_BROWSERS.values()) else "Safari")
            if active not in set(_BROWSERS.values()) or (browser and active != browser):
                raise RuntimeError(
                    f"Bring {browser or 'Safari or Google Chrome'} to the foreground, "
                    "then ask again. Jarvis does not read a hidden browser tab."
                )
            browser = active
        return browser

    @staticmethod
    def _script(browser: str, body: str, *, foreground: bool = True, window: bool = True) -> str:
        # browser and body are internal constants, never user/page-provided code.
        guard = (
            'if not frontmost then error "The browser is no longer in front."\n'
            if foreground
            else ""
        )
        if window:
            guard += 'if (count windows) is 0 then error "The browser has no open window."\n'
        return f'on run argv\ntell application "{browser}"\n{guard}{body}\nend tell\nend run'

    def _metadata(self, browser: str) -> tuple[str, str]:
        tab = "current tab" if browser == "Safari" else "active tab"
        title = "name" if browser == "Safari" else "title"
        output = self._run(
            self._script(
                browser,
                f"set targetTab to {tab} of front window\n"
                f"return (URL of targetTab) & linefeed & ({title} of targetTab)",
            )
        )
        url, separator, name = output.partition("\n")
        if not separator or not url:
            raise RuntimeError("The browser did not return a readable active tab.")
        return url[:4096], name[:1000]

    def _javascript(
        self,
        browser: str,
        source: str,
        *,
        expected_url: str | None = None,
        expected_target: tuple[str, str] | None = None,
        capture_target: bool = False,
    ) -> dict[str, Any]:
        tab = "current tab" if browser == "Safari" else "active tab"
        tab_key = "index" if browser == "Safari" else "id"
        body = "set targetWindow to front window\n"
        body += f"set targetTab to {tab} of targetWindow\n"
        args = [source]
        if expected_url is not None:
            args.append(expected_url)
            body += (
                "if (URL of targetTab) is not (item 2 of argv) then error "
                '"The active page changed; please ask again."\n'
            )
        if expected_target is not None:
            position = len(args) + 1
            args.extend(expected_target)
            body += (
                f"if (id of targetWindow as text) is not (item {position} of argv) "
                'then error "The active browser window changed."\n'
                f"if ({tab_key} of targetTab as text) is not (item {position + 1} of argv) "
                'then error "The active browser tab changed."\n'
            )
        body += (
            "set pageResult to do JavaScript (item 1 of argv) in targetTab\n"
            if browser == "Safari"
            else ("set pageResult to execute targetTab javascript (item 1 of argv)\n")
        )
        if capture_target:
            body += (
                "return (id of targetWindow as text) & (character id 31) & "
                f"({tab_key} of targetTab as text) & (character id 31) & pageResult"
            )
        else:
            body += "return pageResult"
        try:
            output = self._run(self._script(browser, body), *args)
        except RuntimeError as exc:
            raise RuntimeError(
                f"Could not inspect the visible {browser} page. Check macOS Automation "
                "permission and the browser's 'Allow JavaScript from Apple Events' setting; "
                f"Jarvis will not change permissions automatically. {exc}"
            ) from exc
        target = None
        if capture_target:
            pieces = output.split("\x1f", 2)
            if len(pieces) != 3 or not all(re.fullmatch(r"-?\d+", p) for p in pieces[:2]):
                raise RuntimeError("The browser did not identify the observed tab.")
            target = (pieces[0], pieces[1])
            output = pieces[2]
        try:
            data = json.loads(output)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("The browser returned unreadable page evidence.") from exc
        if not isinstance(data, dict):
            raise RuntimeError("The browser returned unexpected page evidence.")
        if target is not None:
            data["_native_target"] = target  # Native metadata overrides any forged page key.
        return data

    def context(self, app_name: str | None = None) -> str:
        """Read current title/URL plus capped visible text, only on user request."""
        browser = self._browser(app_name)
        url, title = self._metadata(browser)
        data: dict[str, Any] = {"browser": browser, "url": url, "title": title}
        # Internal browser pages are not application/work content to inspect.
        try:
            _web_url(url)
        except ValueError:
            return _evidence(**data, page_text_unavailable="This is not an http(s) webpage.")
        try:
            page = self._javascript(browser, _CONTEXT_JS, expected_url=url)
            # If the user changes tabs mid-action, never mix another page's text in.
            if page.get("url") != url:
                raise RuntimeError("The active page changed; ask again on the intended page.")
            data["visible_text"] = str(page.get("visible_text", ""))[:_MAX_PAGE_TEXT]
        except RuntimeError as exc:
            data["page_text_unavailable"] = str(exc)
        return _evidence(**data)

    def _open_current(
        self,
        browser: str,
        url: str,
        *,
        expected_url: str | None = None,
        expected_target: tuple[str, str] | None = None,
    ) -> str:
        tab = "current tab" if browser == "Safari" else "active tab"
        if expected_url is not None:
            body = (
                f"set targetTab to {tab} of front window\n"
                "if (URL of targetTab) is not (item 2 of argv) then error "
                '"The active page changed; please ask again."\n'
            )
            args = [url, expected_url]
            if expected_target is not None:
                tab_key = "index" if browser == "Safari" else "id"
                args.extend(expected_target)
                body += (
                    "if (id of front window as text) is not (item 3 of argv) "
                    'then error "The active browser window changed."\n'
                    f"if ({tab_key} of targetTab as text) is not (item 4 of argv) "
                    'then error "The active browser tab changed."\n'
                )
            body += "set URL of targetTab to item 1 of argv\nreturn URL of targetTab"
            return self._run(self._script(browser, body), *args)
        create = "make new document" if browser == "Safari" else "make new window"
        body = (
            f"activate\nif (count windows) is 0 then {create}\n"
            f"set targetTab to {tab} of front window\n"
            "set URL of targetTab to item 1 of argv\nreturn URL of targetTab"
        )
        return self._run(self._script(browser, body, foreground=False, window=False), url)

    def open_url(self, url: str, app_name: str | None = None) -> str:
        """Visibly navigate the named browser's active tab; no arbitrary URL schemes."""
        url = _web_url(url)
        browser = self._browser(app_name, foreground=False)
        observed = self._open_current(browser, url)
        return _evidence(
            action="open_url",
            browser=browser,
            requested_url=url,
            observed_url=observed[:4096],
            navigation_sent=True,
            detail="Opened the URL in the visible current tab; loading may continue.",
        )

    def search(self, destination: str, query: str, app_name: str | None = None) -> str:
        clean = " ".join(query.split())[:300]
        if not clean:
            raise ValueError("A search query is required.")
        base = (
            "https://www.youtube.com/results?search_query="
            if destination == "youtube"
            else "https://www.google.com/search?q="
        )
        return self.open_url(base + quote_plus(clean), app_name)

    def navigate(self, direction: str, app_name: str | None = None) -> str:
        if direction not in {"back", "forward", "reload"}:
            raise ValueError("Browser navigation supports back, forward, or reload.")
        browser = self._browser(app_name)
        if browser == "Google Chrome":
            command = {"back": "go back", "forward": "go forward", "reload": "reload"}[direction]
            self._run(self._script(browser, f"{command} active tab of front window"))
        else:
            command = {
                "back": "history.back()",
                "forward": "history.forward()",
                "reload": "location.reload()",
            }[direction]
            # The three commands are fixed constants; no model-provided script.
            self._javascript(
                browser, f"(() => {{ {command}; return JSON.stringify({{sent:true}}); }})()"
            )
        return _evidence(
            action="navigate",
            browser=browser,
            direction=direction,
            navigation_sent=True,
            detail="Navigation requested; destination/loading is not yet verified.",
        )

    def scroll(
        self, direction: str, amount: int = 5, edge: str | None = None, app_name: str | None = None
    ) -> str:
        if direction not in {"up", "down", "left", "right"} or not 1 <= amount <= 10:
            raise ValueError("Use a scroll direction and amount from 1 to 10.")
        if edge not in {None, "top", "bottom"}:
            raise ValueError("Scroll edge must be top or bottom.")
        if edge is not None and direction != {"top": "up", "bottom": "down"}[edge]:
            raise ValueError("Use up for the top or down for the bottom.")
        browser = self._browser(app_name)
        source = (
            _SCROLL_JS.replace("__DIRECTION__", json.dumps(direction))
            .replace("__AMOUNT__", str(amount))
            .replace("__EDGE__", json.dumps(edge))
        )
        result = self._javascript(browser, source)
        moved = result.get("moved") is True
        boundary = result.get("at_boundary") is True
        if not moved and not boundary:
            raise RuntimeError("The browser reported no scroll movement; nothing was confirmed.")
        return _evidence(
            action="browser_scroll",
            browser=browser,
            moved=moved,
            at_boundary=boundary,
            direction=direction,
            edge=edge,
            detail="Page scroll position changed."
            if moved
            else "The visible scroll area is already at its boundary.",
        )

    def control_video(self, command: str, app_name: str | None = None) -> str:
        if command not in {"play", "pause", "skip_ad"}:
            raise ValueError("Video control supports play, pause, or skip_ad.")
        browser = self._browser(app_name)
        data = self._javascript(
            browser, _VIDEO_CONTROL_JS.replace("__COMMAND__", json.dumps(command))
        )
        if data.get("error"):
            raise RuntimeError(str(data["error"]))
        return _evidence(
            action="control_browser_video",
            browser=browser,
            command=command,
            sent=data.get("sent") is True,
            verified=data.get("verified") is True,
            detail=str(data.get("detail", "Video command sent.")),
        )

    def play_visible_video(self, index: int, app_name: str | None = None) -> str:
        """Select an organic YouTube video in viewport reading order (1-based)."""
        if isinstance(index, bool) or not isinstance(index, int) or not 1 <= index <= 50:
            raise ValueError("The visible video number must be between 1 and 50.")
        browser = self._browser(app_name)
        page = self._javascript(browser, _VIDEOS_JS, capture_target=True)
        target = page["_native_target"]
        if page.get("error"):
            raise RuntimeError(str(page["error"])[:300])
        origin = page.get("url")
        if not isinstance(origin, str):
            raise RuntimeError("The video list did not identify its source page.")
        parsed = urlsplit(_web_url(origin))
        if parsed.hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            raise RuntimeError("Visible-video selection currently supports YouTube only.")
        videos = page.get("videos")
        if not isinstance(videos, list) or len(videos) > 50:
            raise RuntimeError("The visible video list was unreadable.")
        if index > len(videos):
            raise RuntimeError(
                f"I found {len(videos)} visible standard YouTube videos, not {index}. "
                "Scroll to show that video or ask for it by name. Ads and Shorts are excluded."
            )
        selected = videos[index - 1]
        if not isinstance(selected, dict) or not isinstance(selected.get("url"), str):
            raise RuntimeError("The selected video did not contain a valid link.")
        url = selected["url"]
        video_id = _youtube_id(url)
        if video_id is None:
            raise RuntimeError("The selected link was not a valid YouTube video URL.")
        self._open_current(browser, url, expected_url=origin, expected_target=target)
        playing = False
        for attempt in range(3):
            if attempt:
                self._sleep(0.2)
            try:
                playback = self._javascript(
                    browser, _PLAYBACK_JS, expected_url=url, expected_target=target
                )
            except RuntimeError:
                break  # Navigation succeeded; do not turn a verification miss into a retry.
            if _youtube_id(str(playback.get("url", ""))) == video_id:
                playing = playback.get("playing") is True
                if playing:
                    break
        return _evidence(
            action="play_visible_video",
            browser=browser,
            index=index,
            title=str(selected.get("title", "YouTube video"))[:300],
            url=url,
            navigation_sent=True,
            playback_verified=playing,
            detail="Video playback verified."
            if playing
            else "Opened the selected video, but playback is not verified yet. "
            "The page may still be loading or require a Play click.",
        )
