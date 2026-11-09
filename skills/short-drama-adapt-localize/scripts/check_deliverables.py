"""Exit 0=current recorded text checks; 3=review required; 1=invalid/error."""
import argparse
import json
from drama_core import load_json, save_new, validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    parser.add_argument("--report", help="New report path, never overwrite")
    parser.add_argument("--recovery", action="store_true", help="Include work-local recovery navigation; never certifies reading")
    parser.add_argument("--head", help="Verify this state against its authoritative head JSON")
    args = parser.parse_args()
    try:
        doc = load_json(args.project)
        report = validate(doc)
        if args.head and not report["errors"]:
            from release_contract import head_record
            current = load_json(args.head)
            expected = head_record(doc, args.project)
            if any(current.get(k) != expected[k] for k in ("work_id", "revision", "content_hash", "branch_id")):
                report["errors"].append({"code":"STALE_HEAD", "location":args.head,
                                        "actual":current, "expected":expected})
                report.update(structural_status="failed", overall_status="failed")
        if args.recovery and not report["errors"]:
            from release_contract import recovery_summary
            report["recovery"] = recovery_summary(doc)
        if args.report:
            save_new(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report["errors"] else (3 if report["review_required"] else 0)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
