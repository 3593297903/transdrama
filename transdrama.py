"""Project-local convenience CLI; adaptation itself is performed by the assistant."""
import runpy
import sys
from pathlib import Path

COMMANDS = {"init": "init_project", "check": "check_deliverables",
            "export": "export_deliverables", "revise": "revise_project"}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("Usage: python transdrama.py {init|check|export|revise} --help")
        print("No automatic translation/model calls. Read README.md for the assistant workflow.")
        return 0 if len(sys.argv) == 2 and sys.argv[1] in ("--help", "-h") else 1
    command = sys.argv.pop(1)
    scripts = Path(__file__).resolve().parent / "skills/short-drama-adapt-localize/scripts"
    sys.path.insert(0, str(scripts))
    runpy.run_path(str(scripts / (COMMANDS[command] + ".py")), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
