from search import _http_url, parse_images, parse_news, parse_reverse, parse_videos, parse_web
from utils import AntiSpam, split_message


def test_http_url_rejects_non_http_schemes_and_malformed_values():
    assert _http_url("https://example.com/a") == "https://example.com/a"
    assert _http_url("javascript:alert(1)") == ""
    assert _http_url("data:text/html,hello") == ""
    assert _http_url(None) == ""


def test_web_parser_ignores_untrusted_non_http_links():
    items, answer = parse_web({
        "answer_box": {"answer": "A short answer"},
        "organic_results": [
            {"title": "bad", "link": "javascript:alert(1)"},
            {"title": "good", "link": "https://example.com", "snippet": "safe"},
        ],
    }, 5)
    assert answer == "A short answer"
    assert len(items) == 1
    assert items[0].url == "https://example.com"


def test_image_video_news_parsers_only_keep_http_links():
    images = parse_images({"images_results": [
        {"link": "javascript:alert(1)", "original": "data:image/png;base64,abc"},
        {"link": "https://example.com/image"},
    ]}, 5)
    videos = parse_videos({"video_results": [
        {"link": "file:///etc/passwd"},
        {"link": "https://example.com/video"},
    ]}, 5)
    news = parse_news({"news_results": [
        {"link": "javascript:alert(1)"},
        {"link": "https://example.com/news"},
    ]}, 5)
    assert [x.url for x in images] == ["https://example.com/image"]
    assert [x.url for x in videos] == ["https://example.com/video"]
    assert [x.url for x in news] == ["https://example.com/news"]


def test_reverse_parser_deduplicates_urls():
    items = parse_reverse({"organic_results": [
        {"link": "https://example.com/a", "title": "one"},
        {"link": "https://example.com/a", "title": "duplicate"},
        {"link": "javascript:alert(1)", "title": "bad"},
    ]}, 5)
    assert len(items) == 1
    assert items[0].title == "one"


def test_split_message_respects_telegram_safe_limit():
    parts = split_message(("word " * 3000), limit=4000)
    assert len(parts) > 1
    assert all(len(part) <= 4000 for part in parts)


def test_antispam_enforces_interval_and_cooldown():
    guard = AntiSpam(min_interval=2, burst_max=2, burst_window=10, cooldown=5)
    assert guard.check(1, now=0).allowed
    assert guard.check(1, now=1).reason == "too_fast"
    assert guard.check(1, now=3).allowed
    verdict = guard.check(1, now=6)
    assert not verdict.allowed
    assert verdict.reason == "blocked_now"
