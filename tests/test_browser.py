"""Native browser behavior without launching or reading the user's browser."""

from __future__ import annotations

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from jarvis import browser
from jarvis.browser import BrowserController


class Runner:
    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        assert kwargs == {"capture_output": True, "text": True, "timeout": 7, "check": True}
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return SimpleNamespace(stdout=output)


@pytest.fixture(autouse=True)
def macos(monkeypatch):
    monkeypatch.setattr(browser.sys, "platform", "darwin")


def test_context_reads_only_foreground_visible_text_and_caps_output():
    runner = Runner(
        "Safari",
        "https://example.com/\nExample",
        json.dumps({"url": "https://example.com/", "visible_text": "x" * 9000}),
    )
    result = json.loads(BrowserController(runner=runner).context())
    assert result["title"] == "Example"
    assert len(result["visible_text"]) == 8000
    assert result["untrusted_page_data"] is True
    assert "current tab of targetWindow" in runner.commands[2][2]


def test_context_preserves_title_url_when_javascript_permission_is_denied():
    error = subprocess.CalledProcessError(1, "osascript", stderr="JavaScript from Apple Events off")
    runner = Runner("Google Chrome", "https://example.com/\nExample", error)
    result = json.loads(BrowserController(runner=runner).context("chrome"))
    assert result["url"] == "https://example.com/"
    assert "Allow JavaScript from Apple Events" in result["page_text_unavailable"]
    assert "visible_text" not in result


def test_context_rejects_text_when_user_changes_tabs():
    runner = Runner(
        "Safari",
        "https://example.com/\nExample",
        '{"url":"https://other.example/","visible_text":"secret"}',
    )
    result = json.loads(BrowserController(runner=runner).context())
    assert "active page changed" in result["page_text_unavailable"]
    assert "secret" not in json.dumps(result)


def test_context_does_not_inspect_browser_internal_pages():
    runner = Runner("Google Chrome", "chrome://settings/\nSettings")
    result = json.loads(BrowserController(runner=runner).context())
    assert "not an http(s) webpage" in result["page_text_unavailable"]
    assert len(runner.commands) == 2


@pytest.mark.parametrize("name", [None, "Safari"])
def test_hidden_browser_is_not_read(name):
    runner = Runner("Notes")
    with pytest.raises(RuntimeError, match="foreground"):
        BrowserController(runner=runner).context(name)
    assert len(runner.commands) == 1


def test_unknown_browser_is_rejected_without_commands():
    runner = Runner()
    with pytest.raises(ValueError, match="Safari or Google Chrome"):
        BrowserController(runner=runner).context('Safari"\ndo shell script "oops')
    assert not runner.commands


def test_open_url_uses_argv_not_script_interpolation():
    url = 'https://example.com/?q="quoted"&path=$HOME'
    runner = Runner(url)
    result = json.loads(BrowserController(runner=runner).open_url(url, "safari"))
    assert runner.commands[0][-1] == url
    assert url not in runner.commands[0][2]
    assert "activate" in runner.commands[0][2]
    assert result["navigation_sent"] is True


@pytest.mark.parametrize("frontmost", ["Notes", "Python", "", "Safari", "Google Chrome"])
def test_open_youtube_without_browser_name_never_requires_it_to_be_in_front(frontmost):
    url = "https://www.youtube.com"
    runner = Runner(frontmost, url)
    result = json.loads(BrowserController(runner=runner).open_url(url))
    expected = "Google Chrome" if frontmost == "Google Chrome" else "Safari"
    assert result["browser"] == expected
    assert result["navigation_sent"] is True
    assert "if not frontmost" not in runner.commands[-1][2]


@pytest.mark.parametrize(
    "active, target", [("Notes", "Safari"), ("Google Chrome", "Google Chrome")]
)
def test_search_opens_a_visible_browser_from_any_app(active, target):
    url = "https://www.youtube.com/results?search_query=hello+world"
    runner = Runner(active, url)
    result = json.loads(BrowserController(runner=runner).search("youtube", "hello world"))
    assert result["browser"] == target
    assert runner.commands[-1][-1] == url
    assert "activate" in runner.commands[-1][2]


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///tmp/a",
        "data:text/html,x",
        "https://user:pass@example.com/",
        "https://example.com/\ncommand",
        "https://",
        "https://example.com:bad/",
        "https://example.com/" + "x" * 4096,
    ],
)
def test_unsafe_urls_are_rejected_without_browser_actions(url):
    runner = Runner()
    with pytest.raises(ValueError):
        BrowserController(runner=runner).open_url(url, "chrome")
    assert not runner.commands


def test_scroll_reports_verified_movement_or_a_boundary():
    runner = Runner("Safari", '{"moved":true,"at_boundary":false}')
    result = json.loads(BrowserController(runner=runner).scroll("down", 5))
    assert result["moved"] is True
    assert 'const direction = "down"' in runner.commands[-1][-1]
    runner = Runner("Safari", '{"moved":false,"at_boundary":true}')
    result = json.loads(BrowserController(runner=runner).scroll("down", 5, "bottom"))
    assert "already" in result["detail"]


def test_no_scroll_movement_is_not_reported_as_success():
    runner = Runner("Safari", '{"moved":false,"at_boundary":false}')
    with pytest.raises(RuntimeError, match="no scroll movement"):
        BrowserController(runner=runner).scroll("down")


@pytest.mark.parametrize(
    "direction, edge, before, expected",
    [
        ("down", None, 0, 400),
        ("down", "bottom", 0, 1500),
        ("down", None, 1500, 1500),
        ("up", "top", 700, 0),
    ],
)
def test_scroll_script_changes_position_and_detects_boundaries(direction, edge, before, expected):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is optional; needed for the headless DOM contract test")
    fixture = (
        "globalThis.innerHeight=500; globalThis.innerWidth=1000;"
        "const target={scrollHeight:2000,clientHeight:500,style:{scrollBehavior:'smooth'},"
        f"scrollTop:{before}}};"
        "globalThis.document={scrollingElement:target,elementFromPoint:()=>null};"
    )
    source = (
        browser._SCROLL_JS.replace("__DIRECTION__", json.dumps(direction))
        .replace("__AMOUNT__", "5")
        .replace("__EDGE__", json.dumps(edge))
    )
    completed = subprocess.run(
        [
            node,
            "-e",
            fixture + "process.stdout.write(" + source + ");"
            "if (target.style.scrollBehavior !== 'smooth') throw Error('CSS not restored');",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    result = json.loads(completed.stdout)
    assert result["after"] == expected
    assert result["moved"] is (before != expected)
    assert result["at_boundary"] is (expected in {0, 1500})


def test_ad_skip_targets_fixed_dom_button_not_spotify():
    runner = Runner("Safari", '{"sent":true,"detail":"Clicked the visible Skip Ad button."}')
    result = json.loads(BrowserController(runner=runner).control_video("skip_ad"))
    assert result["sent"] is True
    assert "ytp-ad-skip-button" in runner.commands[-1][-1]
    assert "Spotify" not in str(runner.commands)


def test_chrome_navigation_is_native_without_javascript_permission():
    runner = Runner("Google Chrome", "")
    result = json.loads(BrowserController(runner=runner).navigate("back"))
    assert "go back active tab of front window" in runner.commands[1][2]
    assert result["direction"] == "back"


def test_navigation_rejects_unrecognized_commands():
    runner = Runner()
    with pytest.raises(ValueError):
        BrowserController(runner=runner).navigate("close all tabs")
    assert not runner.commands


def test_safari_navigation_uses_only_fixed_script():
    runner = Runner("Safari", '{"sent":true}')
    BrowserController(runner=runner).navigate("reload")
    assert "location.reload()" in runner.commands[1][-1]


def _videos():
    return "4\x1f2\x1f" + json.dumps(
        {
            "url": "https://www.youtube.com/results?search_query=cats",
            "videos": [
                {"url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "First"},
                {"url": "https://www.youtube.com/watch?v=1234567890_", "title": "Second"},
            ],
        }
    )


def test_selects_second_observed_video_in_same_visible_tab_and_verifies_playing():
    target = "https://www.youtube.com/watch?v=1234567890_"
    runner = Runner("Safari", _videos(), target, json.dumps({"url": target, "playing": True}))
    result = json.loads(BrowserController(runner=runner).play_visible_video(2))
    assert result["title"] == "Second"
    assert result["playback_verified"] is True
    open_command = runner.commands[2]
    assert open_command[-4] == target
    assert open_command[-3] == "https://www.youtube.com/results?search_query=cats"
    assert open_command[-2:] == ["4", "2"]
    assert '"The active page changed; please ask again."' in open_command[2]
    assert "if not frontmost" in open_command[2]
    playback_command = runner.commands[3]
    assert playback_command[-3:] == [target, "4", "2"]
    assert playback_command[2].index("active browser tab changed") < (
        playback_command[2].index("do JavaScript")
    )


def test_chrome_guards_native_tab_id_not_position_across_video_actions():
    target = "https://www.youtube.com/watch?v=abcdefghijk"
    runner = Runner(
        "Google Chrome", _videos(), target, json.dumps({"url": target, "playing": True})
    )
    BrowserController(runner=runner).play_visible_video(1)
    assert "id of targetTab as text" in runner.commands[1][2]
    assert "id of targetTab as text" in runner.commands[2][2]
    assert "id of targetTab as text" in runner.commands[3][2]


def test_missing_native_tab_identity_prevents_video_navigation():
    runner = Runner("Safari", '{"url":"https://www.youtube.com/","videos":[]}')
    with pytest.raises(RuntimeError, match="identify the observed tab"):
        BrowserController(runner=runner).play_visible_video(1)
    assert len(runner.commands) == 2


def test_video_navigation_does_not_claim_playback_when_loading_or_blocked():
    target = "https://www.youtube.com/watch?v=abcdefghijk"
    probe = json.dumps({"url": target, "playing": False})
    runner = Runner("Safari", _videos(), target, probe, probe, probe)
    sleeps = []
    result = json.loads(BrowserController(runner=runner, sleep=sleeps.append).play_visible_video(1))
    assert result["navigation_sent"] is True
    assert result["playback_verified"] is False
    assert "not verified" in result["detail"]
    assert sleeps == [0.2, 0.2]


def test_unrelated_video_playback_is_not_accepted_as_verification():
    runner = Runner(
        "Safari",
        _videos(),
        "https://www.youtube.com/watch?v=abcdefghijk",
        *['{"url":"https://www.youtube.com/watch?v=ZZZZZZZZZZZ","playing":true}'] * 3,
    )
    controller = BrowserController(runner=runner, sleep=lambda _: None)
    result = json.loads(controller.play_visible_video(1))
    assert result["playback_verified"] is False


def test_missing_ordinal_fails_before_navigation():
    runner = Runner("Safari", _videos())
    with pytest.raises(RuntimeError, match="found 2 visible"):
        BrowserController(runner=runner).play_visible_video(3)
    assert len(runner.commands) == 2


def test_untrusted_video_url_cannot_navigate_off_youtube():
    runner = Runner(
        "Safari",
        "4\x1f2\x1f"
        + json.dumps(
            {
                "url": "https://www.youtube.com/",
                "videos": [{"url": "https://evil.example/watch?v=abcdefghijk", "title": "Fake"}],
            }
        ),
    )
    with pytest.raises(RuntimeError, match="not a valid YouTube"):
        BrowserController(runner=runner).play_visible_video(1)
    assert len(runner.commands) == 2


@pytest.mark.parametrize("index", [0, -1, 51, True, 1.5, "2"])
def test_invalid_video_number_does_not_call_browser(index):
    runner = Runner()
    with pytest.raises(ValueError, match="between 1 and 50"):
        BrowserController(runner=runner).play_visible_video(index)
    assert not runner.commands


def test_timeout_has_actionable_error():
    runner = Runner(subprocess.TimeoutExpired("osascript", 7))
    with pytest.raises(RuntimeError, match="timed out"):
        BrowserController(runner=runner).context()


def test_video_dom_selection_uses_viewport_reading_order_and_excludes_ads():
    """Exercise the actual fixed selector code in a tiny headless DOM fixture."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is optional; needed only for the headless DOM contract test")
    fixture = r"""
      globalThis.location = new URL('https://www.youtube.com/results?search_query=cats');
      globalThis.innerHeight = 500; globalThis.innerWidth = 1000;
      globalThis.getComputedStyle = card => ({visibility: 'visible', display: 'block',
        opacity: card.hidden ? '0' : '1'});
      const card = (title, id, top, left, extra = {}) => ({...extra,
        getBoundingClientRect: () => ({top, left, bottom: top + 100, right: left + 100,
          width: 100, height: 100}),
        closest: () => extra.ad || null,
        querySelector: selector => selector.includes('ytd-ad-slot') ? null : {
          href: 'https://www.youtube.com/watch?v=' + id,
          getAttribute: () => title, textContent: title
        }
      });
      globalThis.document = {querySelectorAll: () => [
        card('Second', '1234567890_', 100, 400),
        card('First', 'abcdefghijk', 100, 0),
        card('Advertisement', 'AAAAAAAAAAA', 10, 0, {ad: true}),
        card('Offscreen', 'BBBBBBBBBBB', 700, 0),
        card('Hidden', 'CCCCCCCCCCC', 0, 0, {hidden: true}),
        card('First duplicate thumbnail', 'abcdefghijk', 100, 0)
      ]};
    """
    script = fixture + "process.stdout.write(" + browser._VIDEOS_JS + ");"
    completed = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, timeout=5, check=True
    )
    videos = json.loads(completed.stdout)["videos"]
    assert [item["title"] for item in videos] == ["First", "Second"]


@pytest.mark.parametrize("ad_class", ["", "ad-showing", "ad-interrupting"])
def test_playback_probe_never_verifies_a_preroll_ad_as_requested_content(ad_class):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is optional; needed only for the headless DOM contract test")
    fixture = (
        "globalThis.location = {href: 'https://www.youtube.com/watch?v=abcdefghijk'};"
        f"const adClass = {json.dumps(ad_class)};"
        "globalThis.document = {querySelector: selector => {"
        "if (selector === 'video') return {paused: false, ended: false, readyState: 4};"
        "return adClass && selector.includes('.html5-video-player.' + adClass) ? {} : null;"
        "}};"
    )
    script = fixture + "process.stdout.write(" + browser._PLAYBACK_JS + ");"
    completed = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, timeout=5, check=True
    )
    playback = json.loads(completed.stdout)
    assert playback["playing"] is (not bool(ad_class))
    assert playback["ad_playing"] is bool(ad_class)
