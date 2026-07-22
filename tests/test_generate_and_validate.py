"""Tests for deterministic m3u generation and validation."""

from __future__ import annotations

from pathlib import Path

from scripts import generate_m3u, validate_m3u


def test_generate_m3u_output_and_validate(tmp_path: Path, monkeypatch) -> None:
    channels_csv = tmp_path / "channels.csv"
    canales_m3u = tmp_path / "canales.m3u"
    channels_csv.write_text(
        "name,url,group,tvg_id,tvg_name,tvg_logo,source,needs_review\n"
        "Canal A,https://a.test/live.m3u8,Noticias,id-a,Canal A,https://a.test/logo.png,https://source.test,false\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(generate_m3u, "CHANNELS_CSV", channels_csv)
    monkeypatch.setattr(generate_m3u, "OUTPUT_M3U", canales_m3u)
    monkeypatch.setattr(validate_m3u, "CHANNELS_CSV", channels_csv)
    monkeypatch.setattr(validate_m3u, "OUTPUT_M3U", canales_m3u)

    assert generate_m3u.run_generate() == 0
    assert validate_m3u.run_validation() == 0


def test_validate_fails_on_sensitive_url(tmp_path: Path, monkeypatch) -> None:
    channels_csv = tmp_path / "channels.csv"
    canales_m3u = tmp_path / "canales.m3u"
    channels_csv.write_text(
        "name,url,group,tvg_id,tvg_name,tvg_logo,source,needs_review\n"
        "Canal A,https://a.test/live.m3u8?token=abc,Noticias,,,,https://source.test,false\n",
        encoding="utf-8",
    )
    canales_m3u.write_text("#EXTM3U\n", encoding="utf-8")

    monkeypatch.setattr(validate_m3u, "CHANNELS_CSV", channels_csv)
    monkeypatch.setattr(validate_m3u, "OUTPUT_M3U", canales_m3u)

    assert validate_m3u.run_validation() == 1
