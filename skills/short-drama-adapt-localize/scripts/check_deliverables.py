"""Exit 0=current recorded text checks; 3=review required; 1=invalid/error."""
import argparse
import json
from drama_core import load_json, save_new, validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    parser.add_argument("--report", help="New report path, never overwrite")
    args = parser.parse_args()
    try:
        report = validate(load_json(args.project))
        if args.report:
            save_new(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report["errors"] else (3 if report["review_required"] else 0)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
