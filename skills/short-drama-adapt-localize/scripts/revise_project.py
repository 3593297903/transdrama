"""Save proposed revision with dependent review invalidation; never edits inputs."""
import argparse
import json
from pathlib import Path
from drama_core import invalidate_changes, load_json, save_new
from release_contract import migrate, write_revision, head_record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before")
    parser.add_argument("proposed", nargs="?")
    parser.add_argument("--out", required=True)
    parser.add_argument("--migrate", action="store_true", help="Migrate schema 1 to a NEW schema 2 state; never approve old reviews")
    parser.add_argument("--head", help="Authoritative head JSON; defaults to before state's directory/head.json")
    parser.add_argument("--branch", help="Explicit new branch identity; requires a new --head path")
    args = parser.parse_args()
    try:
        before = load_json(args.before)
        if args.migrate:
            if args.proposed or args.branch:
                raise ValueError("Migration takes one legacy state and a new output/head; no proposed state or branch")
            after = migrate(before)
            head = Path(args.head) if args.head else Path(args.out).parent / "head.json"
            if Path(args.out).exists() or head.exists():
                raise ValueError("Migration refuses existing state or head; select a new work directory")
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            save_new(args.out, after)
            save_new(head, head_record(after, args.out, head))
            report = {"schema_version": 2, "work_id": after["project"]["id"], "review_status": "requires_actual_re_reading"}
        else:
            if not args.proposed:
                raise ValueError("Proposed state is required unless --migrate is specified")
            after = load_json(args.proposed)
            if after.get("schema_version") == 2 or before.get("schema_version") == 2:
                head = Path(args.head) if args.head else Path(args.before).parent / "head.json"
                if args.branch and not args.head:
                    raise ValueError("Explicit branch requires an explicit new --head path")
                report = write_revision(before, after, args.out, head, args.branch)
            else:
                report = invalidate_changes(before, after)
                save_new(args.out, after)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
