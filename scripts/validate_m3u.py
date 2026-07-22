"""Validate channels.csv schema and canales.m3u consistency."""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from scripts.generate_m3u import CHANNELS_CSV, CSV_HEADERS, OUTPUT_M3U, generate_m3u, load_rows

SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(?:^|[?&])(username|password|user|pass|token|api_key|apikey|auth|authorization|access_token|secret|signature|session|cookie)="),
    re.compile(r"://[^\s/@:]+:[^\s/@]+@"),
]


def contains_sensitive_content(text: str) -> bool:
    """Return True when text appears to contain credentials."""
    decoded = unquote(text)
    return any(pattern.search(decoded) for pattern in SENSITIVE_PATTERNS)


def validate_csv_schema(path: Path) -> None:
    """Validate CSV header and no obvious credential leaks."""
    if not path.exists():
        raise ValueError(f"Missing required file: {path}")

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != CSV_HEADERS:
            raise ValueError("Invalid channels.csv schema")
        for idx, row in enumerate(reader, start=2):
            url = (row.get("url") or "").strip()
            if not url:
                raise ValueError(f"Empty URL at CSV row {idx}")
            parsed = urlparse(url)
            if parsed.scheme.lower() not in {"http", "https"}:
                raise ValueError(f"Unsupported scheme at CSV row {idx}")
            if contains_sensitive_content(url):
                raise ValueError(f"Sensitive URL pattern at CSV row {idx}")


def validate_m3u_match(csv_path: Path, m3u_path: Path) -> None:
    """Validate M3U file is deterministic from CSV source of truth."""
    if not m3u_path.exists():
        raise ValueError(f"Missing required file: {m3u_path}")
    expected = generate_m3u(load_rows(csv_path))
    current = m3u_path.read_text(encoding="utf-8")
    if current != expected:
        raise ValueError("canales.m3u does not match deterministic output generated from channels.csv")
    if contains_sensitive_content(current):
        raise ValueError("Sensitive URL pattern detected in canales.m3u")


def run_validation() -> int:
    """Run all validations and return exit code."""
    try:
        validate_csv_schema(CHANNELS_CSV)
        validate_m3u_match(CHANNELS_CSV, OUTPUT_M3U)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def main() -> None:
    """CLI entry point."""
    raise SystemExit(run_validation())


if __name__ == "__main__":
    main()
