"""Save proposed revision with dependent review invalidation; never edits inputs."""
import argparse
import json
from drama_core import invalidate_changes, load_json, save_new


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before")
    parser.add_argument("proposed")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        before, after = load_json(args.before), load_json(args.proposed)
        report = invalidate_changes(before, after)
        save_new(args.out, after)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
