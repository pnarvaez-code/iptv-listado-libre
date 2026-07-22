"""Generate canales.m3u from channels.csv."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

CSV_HEADERS = ["name", "url", "group", "tvg_id", "tvg_name", "tvg_logo", "source", "needs_review"]
CHANNELS_CSV = Path("channels.csv")
OUTPUT_M3U = Path("canales.m3u")


def escape_attr(value: str) -> str:
    """Escape values for EXTINF attributes."""
    return value.replace('"', "'").strip()


def load_rows(path: Path) -> list[dict[str, str]]:
    """Load and sort channels from CSV."""
    if not path.exists():
        raise FileNotFoundError(f"Missing CSV file: {path}")

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != CSV_HEADERS:
            raise ValueError("channels.csv schema mismatch")
        rows = [
            {
                "name": (row.get("name") or "").strip(),
                "url": (row.get("url") or "").strip(),
                "group": (row.get("group") or "Unclassified").strip() or "Unclassified",
                "tvg_id": (row.get("tvg_id") or "").strip(),
                "tvg_name": (row.get("tvg_name") or "").strip(),
                "tvg_logo": (row.get("tvg_logo") or "").strip(),
            }
            for row in reader
            if (row.get("url") or "").strip()
        ]
    rows.sort(key=lambda item: (item["group"].casefold(), item["name"].casefold(), item["url"]))
    return rows


def generate_m3u(rows: list[dict[str, str]]) -> str:
    """Generate deterministic M3U content."""
    lines = ["#EXTM3U"]
    for row in rows:
        attrs: list[str] = []
        if row["tvg_id"]:
            attrs.append(f'tvg-id="{escape_attr(row["tvg_id"])}"')
        if row["tvg_name"]:
            attrs.append(f'tvg-name="{escape_attr(row["tvg_name"])}"')
        if row["tvg_logo"]:
            attrs.append(f'tvg-logo="{escape_attr(row["tvg_logo"])}"')
        if row["group"]:
            attrs.append(f'group-title="{escape_attr(row["group"])}"')

        attr_text = f" {' '.join(attrs)}" if attrs else ""
        lines.append(f"#EXTINF:-1{attr_text},{row['name']}")
        lines.append(row["url"])
    return "\n".join(lines) + "\n"


def run_generate() -> int:
    """Generate file and return exit code."""
    try:
        rows = load_rows(CHANNELS_CSV)
        content = generate_m3u(rows)
        OUTPUT_M3U.write_text(content, encoding="utf-8")
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def main() -> None:
    """CLI entry point."""
    raise SystemExit(run_generate())


if __name__ == "__main__":
    main()
