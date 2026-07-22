"""Import and sanitise public stream entries from an untrusted external source."""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, unquote, urlparse

import requests

SOURCE_URL = "https://raw.githubusercontent.com/Duartegame/TV-TDT/refs/heads/main/m3.txt"
OUTPUT_CSV = Path("channels.csv")
SUMMARY_REPORT = Path("reports/import-summary.json")
REJECTED_DOMAINS_REPORT = Path("reports/rejected-domains.txt")

CSV_HEADERS = ["name", "url", "group", "tvg_id", "tvg_name", "tvg_logo", "source", "needs_review"]
SENSITIVE_PARAM_KEYS = {
    "username",
    "password",
    "user",
    "pass",
    "token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "access_token",
    "secret",
    "signature",
    "session",
    "cookie",
}
UNSAFE_SCHEMES = {"data", "file", "javascript", "vbscript", "ftp", "ws", "wss"}
PUBLIC_ONLY_BLOCKLIST = {
    "register",
    "registro",
    "suscripcion",
    "subscription",
    "premium",
    "vip",
    "private",
    "cliente",
    "members",
    "login",
    "signin",
    "pay",
    "payment",
}
PRIVATE_IPV4_RE = re.compile(
    r"^(?:"
    r"10\."
    r"|127\."
    r"|169\.254\."
    r"|172\.(?:1[6-9]|2\d|3[0-1])\."
    r"|192\.168\."
    r"|0\."
    r")"
)
MAX_DOWNLOAD_SIZE = 10 * 1024 * 1024
MAX_LINE_LENGTH = 8192
MAX_IMPORTED_ENTRIES = 10_000
USER_AGENT = "iptv-listado-libre-importer/1.0 (+https://github.com/pnarvaez-code/iptv-listado-libre)"
REQUEST_TIMEOUT = 20


class ImportErrorSafe(Exception):
    """Raised when the untrusted source cannot be safely imported."""


@dataclass(frozen=True)
class ChannelEntry:
    """A validated channel row ready for CSV export."""

    name: str
    url: str
    group: str
    tvg_id: str
    tvg_name: str
    tvg_logo: str
    source: str
    needs_review: str


@dataclass
class ImportResult:
    """Aggregate import result data."""

    entries: list[ChannelEntry]
    lines_inspected: int
    duplicates_removed: int
    unsafe_rejected: int
    malformed_rejected: int
    rejection_reasons: Counter[str]
    rejected_domains: set[str]


def normalize_text(value: str) -> str:
    """Normalise whitespace and line endings inside metadata fields."""
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def parse_extinf_line(line: str) -> tuple[dict[str, str], str]:
    """Extract M3U #EXTINF metadata attributes and channel display name."""
    attrs: dict[str, str] = {}
    name = ""
    if "," in line:
        _, name_part = line.split(",", 1)
        name = normalize_text(name_part)
    for key, val in re.findall(r'([A-Za-z0-9_-]+)="([^"]*)"', line):
        attrs[key.lower()] = normalize_text(val)
    return attrs, name


def mask_url(url: str) -> str:
    """Return a safe representation without path, credentials or query values."""
    parsed = urlparse(url)
    host = parsed.hostname or "unknown-host"
    scheme = parsed.scheme or "unknown"
    return f"{scheme}://{host}/***"


def _contains_private_account_pattern(path: str) -> bool:
    """Detect common account-specific IPTV URL structures."""
    lowered = unquote(path).lower()
    return bool(re.search(r"/(live|movie|series)/[^/\s]{1,128}/[^/\s]{1,128}/", lowered))


def classify_url_safety(url: str) -> tuple[bool, str]:
    """Classify URL safety and return acceptance decision and reason."""
    if len(url) > MAX_LINE_LENGTH:
        return False, "line_too_long"

    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()

    if not scheme:
        return False, "malformed_url"
    if scheme in UNSAFE_SCHEMES or scheme not in {"http", "https"}:
        return False, "unsupported_scheme"

    if parsed.username or parsed.password:
        return False, "embedded_credentials"

    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        return False, "malformed_url"

    if host == "localhost" or host.endswith(".localhost"):
        return False, "localhost_host"

    if PRIVATE_IPV4_RE.match(host):
        return False, "private_ipv4"

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    for key, _ in query_pairs:
        if key.lower() in SENSITIVE_PARAM_KEYS:
            return False, "sensitive_query_parameter"

    decoded_url = unquote(url).lower()
    if any(f"{key}=" in decoded_url for key in SENSITIVE_PARAM_KEYS):
        return False, "sensitive_query_parameter"

    if _contains_private_account_pattern(parsed.path):
        return False, "private_account_pattern"

    for term in PUBLIC_ONLY_BLOCKLIST:
        if term in decoded_url:
            return False, "private_access_indicator"

    return True, "accepted"


def _normalize_url(url: str) -> str:
    """Trim and normalise URL line endings without exposing query values."""
    return url.strip().replace("\r", "")


def parse_source_lines(source_text: str, source_url: str) -> ImportResult:
    """Parse untrusted lines into validated channel entries."""
    entries: list[ChannelEntry] = []
    seen_urls: set[str] = set()
    duplicates_removed = 0
    unsafe_rejected = 0
    malformed_rejected = 0
    rejection_reasons: Counter[str] = Counter()
    rejected_domains: set[str] = set()
    pending_metadata: dict[str, str] | None = None
    unidentified_counter = 0

    lines = source_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for index, raw_line in enumerate(lines, start=1):
        if index > 2_000_000:
            break
        line = raw_line.strip()
        if not line:
            continue

        if len(raw_line) > MAX_LINE_LENGTH:
            malformed_rejected += 1
            rejection_reasons["line_too_long"] += 1
            pending_metadata = None
            continue

        if line.startswith("#EXTINF"):
            attrs, name = parse_extinf_line(line)
            pending_metadata = {
                "name": name,
                "tvg_id": attrs.get("tvg-id", ""),
                "tvg_name": attrs.get("tvg-name", ""),
                "tvg_logo": attrs.get("tvg-logo", ""),
                "group": attrs.get("group-title", ""),
            }
            continue

        if line.startswith("#"):
            continue

        lines_inspected = index
        url = _normalize_url(line)
        safe, reason = classify_url_safety(url)

        parsed = urlparse(url)
        hostname = (parsed.hostname or "").strip().lower()
        if not safe:
            if hostname:
                rejected_domains.add(hostname)
            if reason in {"malformed_url", "line_too_long"}:
                malformed_rejected += 1
            else:
                unsafe_rejected += 1
            rejection_reasons[reason] += 1
            pending_metadata = None
            continue

        if url in seen_urls:
            duplicates_removed += 1
            pending_metadata = None
            continue
        seen_urls.add(url)

        metadata = pending_metadata or {"name": "", "group": "", "tvg_id": "", "tvg_name": "", "tvg_logo": ""}
        pending_metadata = None

        name = normalize_text(metadata.get("name", ""))
        group = normalize_text(metadata.get("group", ""))
        tvg_id = normalize_text(metadata.get("tvg_id", ""))
        tvg_name = normalize_text(metadata.get("tvg_name", ""))
        tvg_logo = normalize_text(metadata.get("tvg_logo", ""))

        needs_review = "false"
        if not name:
            unidentified_counter += 1
            name = f"Unidentified public stream {unidentified_counter:03d}"
            group = "Unclassified"
            needs_review = "true"
        elif not group:
            group = "Unclassified"

        entries.append(
            ChannelEntry(
                name=name,
                url=url,
                group=group,
                tvg_id=tvg_id,
                tvg_name=tvg_name,
                tvg_logo=tvg_logo,
                source=source_url,
                needs_review=needs_review,
            )
        )

        if len(entries) >= MAX_IMPORTED_ENTRIES:
            break

    entries.sort(key=lambda item: (item.group.casefold(), item.name.casefold(), item.url))

    return ImportResult(
        entries=entries,
        lines_inspected=len(lines),
        duplicates_removed=duplicates_removed,
        unsafe_rejected=unsafe_rejected,
        malformed_rejected=malformed_rejected,
        rejection_reasons=rejection_reasons,
        rejected_domains=rejected_domains,
    )


def download_source(source_url: str) -> str:
    """Download source text with strict size and decoding protections."""
    headers = {"User-Agent": USER_AGENT, "Accept": "text/plain,*/*;q=0.5"}
    try:
        response = requests.get(
            source_url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            stream=True,
            allow_redirects=False,
        )
    except requests.RequestException as exc:  # pragma: no cover - exercised in tests
        raise ImportErrorSafe("connection_error") from exc

    if 300 <= response.status_code < 400:
        raise ImportErrorSafe("redirect_not_allowed")

    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise ImportErrorSafe("http_error") from exc

    chunks: list[bytes] = []
    total_size = 0
    for chunk in response.iter_content(chunk_size=8192):
        if not chunk:
            continue
        total_size += len(chunk)
        if total_size > MAX_DOWNLOAD_SIZE:
            raise ImportErrorSafe("download_too_large")
        chunks.append(chunk)

    if total_size == 0:
        raise ImportErrorSafe("empty_response")

    payload = b"".join(chunks)
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ImportErrorSafe("invalid_utf8") from exc

    if not text.strip():
        raise ImportErrorSafe("empty_response")

    return text


def ensure_parent(path: Path) -> None:
    """Create output parent directory if missing."""
    path.parent.mkdir(parents=True, exist_ok=True)


def write_channels_csv(path: Path, entries: Iterable[ChannelEntry]) -> None:
    """Write imported channels with deterministic UTF-8 CSV output."""
    ensure_parent(path)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADERS)
        for entry in entries:
            writer.writerow(
                [
                    entry.name,
                    entry.url,
                    entry.group,
                    entry.tvg_id,
                    entry.tvg_name,
                    entry.tvg_logo,
                    entry.source,
                    entry.needs_review,
                ]
            )


def write_summary_report(path: Path, source_url: str, result: ImportResult) -> None:
    """Write sanitised JSON report without secrets or rejected URL values."""
    ensure_parent(path)
    payload = {
        "source_url": source_url,
        "import_timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "lines_inspected": result.lines_inspected,
        "valid_entries_accepted": len(result.entries),
        "duplicate_entries_removed": result.duplicates_removed,
        "unsafe_entries_rejected": result.unsafe_rejected,
        "malformed_entries_rejected": result.malformed_rejected,
        "rejection_counts_by_reason": dict(sorted(result.rejection_reasons.items())),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_rejected_domains(path: Path, domains: set[str]) -> None:
    """Write unique rejected hostnames only."""
    ensure_parent(path)
    rows = sorted(d for d in domains if d)
    path.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")


def run_import(source_url: str = SOURCE_URL) -> int:
    """Execute import pipeline and return POSIX-style exit code."""
    try:
        source_text = download_source(source_url)
    except ImportErrorSafe as exc:
        print(f"Import failed ({exc}). Source: {mask_url(source_url)}", file=sys.stderr)
        return 1

    result = parse_source_lines(source_text, source_url)
    write_channels_csv(OUTPUT_CSV, result.entries)
    write_summary_report(SUMMARY_REPORT, source_url, result)
    write_rejected_domains(REJECTED_DOMAINS_REPORT, result.rejected_domains)

    print(
        "Import completed: "
        f"accepted={len(result.entries)} "
        f"duplicates={result.duplicates_removed} "
        f"unsafe_rejected={result.unsafe_rejected} "
        f"malformed_rejected={result.malformed_rejected}"
    )
    return 0


def main() -> None:
    """CLI entry point."""
    raise SystemExit(run_import())


if __name__ == "__main__":
    main()
