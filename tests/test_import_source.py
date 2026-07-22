"""Tests for secure untrusted source import."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from scripts import import_source


class FakeResponse:
    """Simple mocked requests response."""

    def __init__(self, payload: bytes, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def iter_content(self, chunk_size: int = 8192):
        for i in range(0, len(self._payload), chunk_size):
            yield self._payload[i : i + chunk_size]

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")


def test_parse_valid_extm3u_and_extinf_blocks() -> None:
    text = """#EXTM3U
#EXTINF:-1 tvg-id="tv1" tvg-name="Canal Uno" tvg-logo="https://img/logo.png" group-title="Noticias",Canal Uno
https://stream.example.com/live1.m3u8
"""
    result = import_source.parse_source_lines(text, import_source.SOURCE_URL)
    assert len(result.entries) == 1
    entry = result.entries[0]
    assert entry.name == "Canal Uno"
    assert entry.group == "Noticias"
    assert entry.tvg_id == "tv1"


def test_parse_plain_public_urls_generates_neutral_names() -> None:
    text = "https://public.example.com/one.m3u8\nhttps://public.example.com/two.m3u8\n"
    result = import_source.parse_source_lines(text, import_source.SOURCE_URL)
    assert [e.name for e in result.entries] == [
        "Unidentified public stream 001",
        "Unidentified public stream 002",
    ]
    assert all(e.group == "Unclassified" for e in result.entries)
    assert all(e.needs_review == "true" for e in result.entries)


def test_removes_duplicate_urls() -> None:
    text = "https://public.example.com/a.m3u8\nhttps://public.example.com/a.m3u8\n"
    result = import_source.parse_source_lines(text, import_source.SOURCE_URL)
    assert len(result.entries) == 1
    assert result.duplicates_removed == 1


@pytest.mark.parametrize(
    "url,reason",
    [
        ("https://x.test/live.m3u8?username=a&******", "sensitive_query_parameter"),
        ("https://x.test/live.m3u8?token=abc", "sensitive_query_parameter"),
        ("https://x.test/live.m3u8?api_key=abc", "sensitive_query_parameter"),
        ("http://192.168.1.5/stream", "private_ipv4"),
        ("http://localhost/live", "localhost_host"),
        ("not-a-url", "malformed_url"),
        ("javascript:alert(1)", "unsupported_scheme"),
    ],
)
def test_rejects_unsafe_and_malformed_urls(url: str, reason: str) -> None:
    accepted, detected = import_source.classify_url_safety(url)
    assert not accepted
    assert detected == reason


def test_rejects_embedded_credentials() -> None:
    url = "https://" + "user" + ":" + "pass" + "@x.test/live.m3u8"
    accepted, detected = import_source.classify_url_safety(url)
    assert not accepted
    assert detected == "embedded_credentials"


def test_utf8_channel_names_are_preserved() -> None:
    text = """#EXTINF:-1 group-title="Música",Canal Ñandú
https://public.example.com/utf8.m3u8
"""
    result = import_source.parse_source_lines(text, import_source.SOURCE_URL)
    assert result.entries[0].name == "Canal Ñandú"
    assert result.entries[0].group == "Música"


def test_download_connection_failure() -> None:
    with patch("scripts.import_source.requests.get", side_effect=requests.ConnectionError):
        with pytest.raises(import_source.ImportErrorSafe):
            import_source.download_source(import_source.SOURCE_URL)


def test_download_invalid_utf8() -> None:
    with patch("scripts.import_source.requests.get", return_value=FakeResponse(b"\xff\xff")):
        with pytest.raises(import_source.ImportErrorSafe):
            import_source.download_source(import_source.SOURCE_URL)


def test_download_empty_response() -> None:
    with patch("scripts.import_source.requests.get", return_value=FakeResponse(b"")):
        with pytest.raises(import_source.ImportErrorSafe):
            import_source.download_source(import_source.SOURCE_URL)


def test_report_sanitisation_and_no_secret_leak(tmp_path: Path) -> None:
    report_path = tmp_path / "import-summary.json"
    domains_path = tmp_path / "rejected-domains.txt"
    with_userinfo = "https://" + "user" + ":" + "pass" + "@bad.example.com/live"
    source_text = (
        "https://public.example.com/a.m3u8\n"
        "https://private.example.com/live?token=secret-token\n"
        f"{with_userinfo}\n"
    )
    result = import_source.parse_source_lines(source_text, import_source.SOURCE_URL)
    import_source.write_summary_report(report_path, import_source.SOURCE_URL, result)
    import_source.write_rejected_domains(domains_path, result.rejected_domains)

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)
    assert "secret-token" not in serialized
    assert "user:pass" not in serialized
    assert payload["unsafe_entries_rejected"] == 2

    domains = domains_path.read_text(encoding="utf-8")
    assert "private.example.com" in domains
    assert "bad.example.com" in domains
    assert "?" not in domains
    assert "/" not in domains


def test_run_import_writes_channels_csv_with_expected_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv_path = tmp_path / "channels.csv"
    summary_path = tmp_path / "reports" / "import-summary.json"
    domains_path = tmp_path / "reports" / "rejected-domains.txt"

    monkeypatch.setattr(import_source, "OUTPUT_CSV", csv_path)
    monkeypatch.setattr(import_source, "SUMMARY_REPORT", summary_path)
    monkeypatch.setattr(import_source, "REJECTED_DOMAINS_REPORT", domains_path)

    payload = b"#EXTINF:-1 group-title=\"Noticias\",Canal Publico\nhttps://public.example.com/live.m3u8\n"
    with patch("scripts.import_source.requests.get", return_value=FakeResponse(payload)):
        rc = import_source.run_import(import_source.SOURCE_URL)

    assert rc == 0
    content = csv_path.read_text(encoding="utf-8")
    assert content.splitlines()[0] == ",".join(import_source.CSV_HEADERS)
    assert "Canal Publico" in content


def test_secrets_never_appear_in_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("scripts.import_source.requests.get", side_effect=requests.ConnectionError("username=demo")):
        rc = import_source.run_import(import_source.SOURCE_URL)
    captured = capsys.readouterr()
    assert rc == 1
    assert "username=demo" not in captured.err
    assert "***" in captured.err
