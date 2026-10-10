"""
Tests for the .env loader.

These exist because a hand-written .env on Windows can arrive with a UTF-8 BOM,
CRLF endings, an `export ` prefix, or quoted values — and any of those silently
breaking the key would look like "the key isn't working" to the user.
"""

from pathlib import Path

import pytest

from backend import apply_env, load_dotenv, parse_env_text


def test_plain_line():
    assert parse_env_text("SARVAM_API_KEY=sk_abc123") == {"SARVAM_API_KEY": "sk_abc123"}


def test_utf8_bom_is_stripped():
    # Exactly what Notepad can write: a BOM before the first key.
    text = "\ufeffSARVAM_API_KEY=sk_bomkey\n"
    assert parse_env_text(text) == {"SARVAM_API_KEY": "sk_bomkey"}


def test_export_prefix_is_tolerated():
    assert parse_env_text("export SARVAM_API_KEY=sk_exported") == {
        "SARVAM_API_KEY": "sk_exported"
    }


def test_quoted_values():
    assert parse_env_text('SARVAM_API_KEY="sk_dq"')["SARVAM_API_KEY"] == "sk_dq"
    assert parse_env_text("SARVAM_API_KEY='sk_sq'")["SARVAM_API_KEY"] == "sk_sq"


def test_crlf_line_endings():
    assert parse_env_text("A=1\r\nB=2\r\n") == {"A": "1", "B": "2"}


def test_spaces_around_equals():
    assert parse_env_text("SARVAM_API_KEY = sk_spaced ") == {"SARVAM_API_KEY": "sk_spaced"}


def test_comments_and_blank_lines_ignored():
    text = "# a comment\n\n   \nSARVAM_API_KEY=sk_x\n# another\n"
    assert parse_env_text(text) == {"SARVAM_API_KEY": "sk_x"}


def test_garbage_lines_do_not_raise():
    assert parse_env_text("this is not a pair\nKEY=1\n") == {"KEY": "1"}


def test_load_dotenv_reads_a_file(tmp_path):
    p = tmp_path / ".env"
    p.write_text("\ufeffSARVAM_API_KEY=sk_fromfile\r\nOTHER=1\n", encoding="utf-8")
    pairs = load_dotenv(p)
    assert pairs["SARVAM_API_KEY"] == "sk_fromfile"
    assert pairs["OTHER"] == "1"


def test_load_dotenv_missing_file_returns_empty(tmp_path):
    assert load_dotenv(tmp_path / "nope.env") == {}


def test_apply_env_does_not_overwrite_existing():
    fake = {"SARVAM_API_KEY": "already_set"}
    apply_env({"SARVAM_API_KEY": "from_file", "NEW_KEY": "v"}, environ=fake)
    assert fake["SARVAM_API_KEY"] == "already_set"
    assert fake["NEW_KEY"] == "v"


def test_bom_file_end_to_end_enables_configuration(tmp_path, monkeypatch):
    """The exact failure a Notepad user hits: BOM -> key must still load."""
    p = tmp_path / ".env"
    p.write_bytes(b"\xef\xbb\xbfSARVAM_API_KEY=sk_endtoend\n")
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    apply_env(load_dotenv(p))
    import os
    assert os.environ.get("SARVAM_API_KEY") == "sk_endtoend"
