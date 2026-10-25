import csv
from pathlib import Path

root = Path.cwd()
dataset = root / "dataset"
evidence_root = dataset / "evidence"

with (dataset / "evidence_files.csv").open(
    "r", encoding="utf-8-sig", newline=""
) as f:
    manifest = list(csv.DictReader(f))

terms = (
    "export_1260",
    "export_1842",
    "NST-2026-0718-1842",
    "ingrid.dahl@outlook.com",
    "user_18",
)

print("=== CANDIDATE EVIDENCE FILES ===")

for item in manifest:
    relative = item.get("file_path", "")
    path = evidence_root / relative.removeprefix("evidence/")

    if not path.is_file() or path.suffix.lower() not in {
        ".log", ".json", ".txt", ".sql", ".csv"
    }:
        continue

    content = path.read_text(encoding="utf-8", errors="replace")
    hits = [
        (number, line.strip())
        for number, line in enumerate(content.splitlines(), 1)
        if any(term.casefold() in line.casefold() for term in terms)
    ]

    if hits:
        print(f"\n{item['file_id']} | {relative}")
        print("Captured:", item.get("captured_at"))
        for number, line in hits[:12]:
            print(f"  {number}: {line[:300]}")
        if len(hits) > 12:
            print(f"  ... {len(hits) - 12} additional matching lines")
