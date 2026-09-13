"""Maintenance script: clears run history under runs_root() (see atba/context_store.py).

This is the same directory the frontend's "History" page (/runs) reads from — each subdirectory is
one run_id, holding stepN.json + manifest.json. Deleting a run's folder here is exactly equivalent to
it disappearing from that list.

Usage (run on the server, from the repo root, with the same environment/.env the backend uses — so
that ATBA_RUNS_DIR, if set, resolves to the same directory):
    python -m scripts.clear_runs                  # lists what would be deleted, deletes nothing
    python -m scripts.clear_runs --yes             # deletes every run
    python -m scripts.clear_runs --run-id <id> --yes   # deletes just one run
    python -m scripts.clear_runs --older-than 30 --yes # deletes runs not updated in the last 30 days

Deliberately does NOT remove runs_root() itself, only what's inside it — so the directory (and any
ATBA_RUNS_DIR mount point) survives, and the next run just recreates its own subfolder as usual.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atba.context_store import runs_root  # noqa: E402


def _updated_at(run_dir: Path) -> datetime | None:
    manifest = run_dir / "manifest.json"
    if not manifest.exists():
        return None
    import json

    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return datetime.fromisoformat(data["updated_at"])
    except (json.JSONDecodeError, OSError, KeyError, ValueError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-id", help="Delete only this run instead of everything.")
    parser.add_argument(
        "--older-than",
        type=int,
        metavar="DAYS",
        help="Delete only runs whose manifest.json updated_at is older than this many days "
        "(runs with no/unreadable manifest are skipped, not deleted, when this filter is used).",
    )
    parser.add_argument("--yes", action="store_true", help="Actually delete. Without this flag, only lists targets.")
    args = parser.parse_args()

    root = runs_root()
    if not root.exists():
        print(f"{root} does not exist yet — nothing to clear.")
        return

    if args.run_id:
        targets = [root / args.run_id]
        if not targets[0].is_dir():
            print(f"No such run: {targets[0]}")
            return
    else:
        targets = [d for d in root.iterdir() if d.is_dir()]
        if args.older_than is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=args.older_than)
            kept = []
            for d in targets:
                ts = _updated_at(d)
                if ts is not None and ts < cutoff:
                    kept.append(d)
            targets = kept

    if not targets:
        print("Nothing matches — nothing to delete.")
        return

    print(f"{'Deleting' if args.yes else 'Would delete'} {len(targets)} run(s) under {root}:")
    for d in sorted(targets):
        print(f"  {d.name}")

    if not args.yes:
        print("\nDry run only — pass --yes to actually delete.")
        return

    for d in targets:
        shutil.rmtree(d)
    print("Done.")


if __name__ == "__main__":
    main()
