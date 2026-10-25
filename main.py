"""Phase 1: inspect and validate the Ghost Data challenge dataset.

Run from the repository root:
    python .\code\main.py

This phase deliberately does not generate output.csv yet. The evidence and
policy evaluation must be implemented before assigning case statuses.
"""
from __future__ import annotations

import csv
import shlex
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "dataset"

REQUIRED_COLUMNS = {
    "deletion_requests.csv": {
        "case_id", "email", "requested_at", "reported_status",
        "reported_at", "audit_at", "request_text",
    },
    "deletion_rules.csv": set(),
    "evidence_files.csv": {"file_id", "file_path", "origin", "captured_at"},
    "system_activity.csv": {
        "activity_id", "event_time", "event_type", "source_system",
        "target_system", "resource_id", "reported_result", "details",
    },
    "user_audit_log.csv": {
        "audit_id", "user_id", "event_time", "field_name",
        "old_value", "new_value",
    },
    "user_identities.csv": {
        "user_id", "name", "email", "phone", "email_hash", "updated_at",
    },
}


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV as dictionaries while tolerating a UTF-8 BOM."""
    if not path.is_file():
        raise FileNotFoundError(f"Required file was not found: {path}")
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse ISO timestamps, including UTC values ending in 'Z'."""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Treat naive timestamps consistently as UTC rather than local computer time.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_log_line(line: str) -> dict[str, Any] | None:
    """Parse a timestamp followed by shell-style key=value log fields."""
    stripped = line.strip()
    if not stripped:
        return None

    first_space = stripped.find(" ")
    if first_space < 0:
        return None

    timestamp_text = stripped[:first_space]
    timestamp = parse_timestamp(timestamp_text)
    if timestamp is None:
        return None

    try:
        tokens = shlex.split(stripped[first_space + 1:])
    except ValueError:
        # A malformed quoted field should not crash the whole audit.
        return {"timestamp": timestamp, "raw": stripped, "parse_error": True}

    record: dict[str, Any] = {
        "timestamp": timestamp,
        "raw": stripped,
        "parse_error": False,
    }
    for token in tokens:
        if "=" in token:
            key, value = token.split("=", 1)
            record[key] = value
        else:
            # Preserve bare tokens instead of silently dropping them.
            record.setdefault("_extra_tokens", []).append(token)
    return record


def resolve_evidence_path(file_path: str) -> Path:
    """Resolve a manifest path beneath dataset/ and reject path traversal."""
    candidate = (DATASET / file_path).resolve()
    dataset_root = DATASET.resolve()
    if candidate != dataset_root and dataset_root not in candidate.parents:
        raise ValueError(f"Evidence path escapes dataset directory: {file_path}")
    return candidate


def validate_csv_inputs() -> dict[str, list[dict[str, str]]]:
    """Load known input tables and validate their required columns."""
    tables: dict[str, list[dict[str, str]]] = {}
    for filename, required in REQUIRED_COLUMNS.items():
        path = DATASET / filename
        rows = read_csv(path)
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            header = next(csv.reader(handle), [])
        missing = sorted(required - set(header))
        if missing:
            raise ValueError(f"{filename} is missing required columns: {missing}")
        tables[filename] = rows
    return tables


def inspect_evidence_manifest(rows: list[dict[str, str]]) -> tuple[Counter, list[str]]:
    """Count evidence types and report manifest entries whose files are missing."""
    extension_counts: Counter = Counter()
    missing_files: list[str] = []

    for row in rows:
        relative_path = row.get("file_path", "")
        path = resolve_evidence_path(relative_path)
        extension_counts[path.suffix.lower() or "[no extension]"] += 1
        if not path.is_file():
            missing_files.append(f"{row.get('file_id', '?')}: {relative_path}")

    return extension_counts, missing_files


def inspect_sample_log(manifest_rows: list[dict[str, str]]) -> None:
    """Parse a small number of real log records and display safe structural facts."""
    log_entry = next(
        (
            row for row in manifest_rows
            if row.get("file_path", "").lower().endswith(".log")
        ),
        None,
    )
    if not log_entry:
        print("\nNo .log file was listed in evidence_files.csv.")
        return

    log_path = resolve_evidence_path(log_entry["file_path"])
    print(f"\nSample log: {log_entry['file_id']} ({log_entry['file_path']})")
    event_counts: Counter = Counter()
    service_counts: Counter = Counter()
    parsed_count = 0
    cutoff_count = 0
    first_record: dict[str, Any] | None = None

    # This is a parser smoke test, not a case decision. Case-specific cutoff
    # filtering will be applied when we connect evidence to each request.
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            record = parse_log_line(line)
            if record is None:
                continue
            parsed_count += 1
            if first_record is None:
                first_record = record
            if record.get("event"):
                event_counts[str(record["event"])] += 1
            if record.get("service"):
                service_counts[str(record["service"])] += 1
            if record.get("timestamp"):
                cutoff_count += 1

    print(f"Timestamped records parsed: {parsed_count}")
    print(f"Records with timestamps available for cutoff checks: {cutoff_count}")
    print(f"Distinct event names in this file: {len(event_counts)}")
    print(f"Distinct services in this file: {len(service_counts)}")
    if first_record:
        print("First parsed record fields:", ", ".join(sorted(first_record.keys())))
        print("First parsed event:", first_record.get("event", "(no event field)"))
        print("First parsed service:", first_record.get("service", "(no service field)"))


def main() -> int:
    print("Ghost Data Still Exists — dataset inspection (Phase 1)")
    print(f"Repository root: {ROOT}")
    print(f"Dataset directory: {DATASET}")

    try:
        tables = validate_csv_inputs()
    except (FileNotFoundError, ValueError) as error:
        print(f"\nINPUT VALIDATION FAILED: {error}", file=sys.stderr)
        return 1

    print("\nCSV input row counts:")
    for filename, rows in tables.items():
        print(f"  {filename}: {len(rows)} rows")

    requests = tables["deletion_requests.csv"]
    case_ids = [row.get("case_id", "") for row in requests]
    if len(requests) != 518:
        print(f"\nWARNING: expected 518 requests, found {len(requests)}.")
    if len(case_ids) != len(set(case_ids)):
        print("\nWARNING: duplicate case_id values were found.")
    if any(not case_id for case_id in case_ids):
        print("\nWARNING: one or more requests have an empty case_id.")

    manifest = tables["evidence_files.csv"]
    extension_counts, missing_files = inspect_evidence_manifest(manifest)
    print("\nEvidence files by extension:")
    for extension, count in sorted(extension_counts.items()):
        print(f"  {extension}: {count}")

    print(f"\nManifest entries: {len(manifest)}")
    print(f"Missing evidence files: {len(missing_files)}")
    for item in missing_files[:10]:
        print(f"  MISSING: {item}")

    inspect_sample_log(manifest)

    print("\nPhase 1 completed. No deletion statuses were guessed and output.csv was not changed.")
    print("Next phase: inspect JSON/SQL evidence and implement case-level identity, policy, and cutoff evaluation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
