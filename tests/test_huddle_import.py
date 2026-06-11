"""Regression tests for huddle canvas title parsing.

The critical case: Slack HTML-escapes file titles in API responses, so
files.list returns "Huddle notes: 5/15/26 in &lt;#C07Q5784258&gt;" — the
import must unescape before matching or every canvas is skipped.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.huddle_import import _parse_huddle_title


def test_entity_encoded_title_from_files_list():
    # Exact format observed in production files.list responses
    title = ":headphones: Huddle notes: 5/15/26 in &lt;#C07Q5784258&gt;"
    assert _parse_huddle_title(title) == ("2026-05-15", "C07Q5784258")


def test_raw_mrkdwn_title():
    assert _parse_huddle_title("Huddle notes: 6/6/26 in <#C0AA65K626B>") == (
        "2026-06-06",
        "C0AA65K626B",
    )


def test_mrkdwn_title_with_pipe_name():
    assert _parse_huddle_title("Huddle notes: 6/6/26 in <#C0AA65K626B|case-management>") == (
        "2026-06-06",
        "C0AA65K626B",
    )


def test_plain_channel_name_format():
    date_str, channel = _parse_huddle_title("Huddle notes: 6/6/26 in #case-management")
    assert date_str == "2026-06-06"
    assert channel == "C0AA65K626B"  # resolved via reverse map


def test_sanitized_underscore_name():
    name = "_headphones__Huddle_notes__6_8_26_in___C09GT3XBKD0_"
    assert _parse_huddle_title(name) == ("2026-06-08", "C09GT3XBKD0")


def test_four_digit_year():
    assert _parse_huddle_title("Huddle notes: 5/15/2026 in <#C07Q5784258>") == (
        "2026-05-15",
        "C07Q5784258",
    )


def test_non_huddle_title_returns_none():
    assert _parse_huddle_title("Q4 Financial Report.pdf") is None


def test_invalid_date_returns_none():
    assert _parse_huddle_title("Huddle notes: 13/45/26 in <#C07Q5784258>") is None
