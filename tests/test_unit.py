"""
Unit tests — no database, no Redis, no network.

Covers:
- normalize_alias: case folding, separator equivalence
- parse_device: mobile / tablet / bot / desktop classification
"""
import pytest

from app.routers.helpers import normalize_alias
from app.routers.redirect import parse_device


# ---------------------------------------------------------------------------
# normalize_alias
# ---------------------------------------------------------------------------

class TestNormalizeAlias:
    """All case/separator variants must produce the same canonical form."""

    def test_lowercase_passthrough(self):
        assert normalize_alias("test") == "test"

    def test_uppercase_folded(self):
        assert normalize_alias("TEST") == "test"

    def test_mixed_case_folded(self):
        assert normalize_alias("Test") == "test"

    def test_hyphen_preserved(self):
        assert normalize_alias("test-alias") == "test-alias"

    def test_underscore_converted_to_hyphen(self):
        assert normalize_alias("test_alias") == "test-alias"

    def test_hyphen_and_underscore_are_equivalent(self):
        assert normalize_alias("test-alias") == normalize_alias("test_alias")

    def test_leading_trailing_whitespace_stripped(self):
        assert normalize_alias("  hello  ") == "hello"

    def test_mixed_case_and_separator(self):
        assert normalize_alias("My_Link") == normalize_alias("my-link")

    def test_all_caps_with_underscore(self):
        assert normalize_alias("MY_ALIAS") == "my-alias"

    def test_numbers_preserved(self):
        assert normalize_alias("abc123") == "abc123"

    def test_already_canonical(self):
        assert normalize_alias("already-fine") == "already-fine"


# ---------------------------------------------------------------------------
# parse_device
# ---------------------------------------------------------------------------

class TestParseDevice:
    """User-Agent string → device category."""

    # --- mobile ---
    def test_iphone_is_mobile(self):
        assert parse_device("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)") == "mobile"

    def test_android_phone_is_mobile(self):
        assert parse_device(
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit"
        ) == "mobile"

    def test_mobi_substring_is_mobile(self):
        assert parse_device("Opera/9.80 (J2ME/MIDP; Opera Mini/9.80; Mobi)") == "mobile"

    # --- tablet ---
    def test_ipad_is_tablet(self):
        assert parse_device(
            "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)"
        ) == "tablet"

    def test_tablet_substring_is_tablet(self):
        assert parse_device("Mozilla/5.0 (Linux; Android 13; Tablet)") == "tablet"

    # --- bot ---
    def test_googlebot_is_bot(self):
        assert parse_device("Googlebot/2.1 (+http://www.google.com/bot.html)") == "bot"

    def test_spider_is_bot(self):
        assert parse_device("AhrefsBot spider crawler") == "bot"

    def test_crawl_is_bot(self):
        assert parse_device("DuckDuckBot Crawler/1.0") == "bot"

    # --- desktop ---
    def test_chrome_desktop_is_desktop(self):
        assert parse_device(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        ) == "desktop"

    def test_firefox_mac_is_desktop(self):
        assert parse_device(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15) "
            "Gecko/20100101 Firefox/121.0"
        ) == "desktop"

    def test_none_ua_is_desktop(self):
        assert parse_device(None) == "desktop"

    def test_empty_ua_is_desktop(self):
        assert parse_device("") == "desktop"

    # --- bot takes priority over mobile substring ---
    def test_bot_priority_over_other_substrings(self):
        # A UA that contains both "mobi" and "bot" → bot wins (checked first)
        assert parse_device("MobileBot/1.0 bot crawler") == "bot"

    # --- tablet takes priority over android/mobi ---
    def test_ipad_not_classified_as_mobile(self):
        # iPad UA does NOT contain "mobi"/"iphone"/"android", only "ipad"
        ua = "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit"
        assert parse_device(ua) == "tablet"
        assert parse_device(ua) != "mobile"
