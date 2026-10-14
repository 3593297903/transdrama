"""Run actual checks and preserve log/results in a new audit directory."""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    run = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                         cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (out / "unittest.log").write_text(run.stdout + run.stderr, encoding="utf-8")
    skill = ROOT / "skills/short-drama-adapt-localize"
    content = (skill / "SKILL.md").read_text(encoding="utf-8")
    refs = re.findall(r"`(references/[^`]+\.md)`", content)
    basic = {"frontmatter_delimiters": content.startswith("---\n") and "\n---\n" in content,
             "name": "name: short-drama-adapt-localize\n" in content,
             "description": bool(re.search(r"^description: .+", content, re.M)),
             "references_exist": all((skill / ref).is_file() for ref in refs),
             "no_unfinished_marker": "[TODO:" not in content}
    summary = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "python": sys.executable,
               "command": "python -m unittest discover -s tests -v", "returncode": run.returncode,
               "test_count": int(re.search(r"Ran (\d+) tests", run.stderr).group(1)) if re.search(r"Ran (\d+) tests", run.stderr) else None,
               "basic_skill_layout": basic,
               "note": "Basic layout checks are not the unavailable PyYAML-based official validator; no semantic or media certification."}
    (out / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if run.returncode == 0 and all(basic.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
