"""Create a non-overwriting import checkpoint. Does not adapt or claim to read."""
import argparse
import uuid
from pathlib import Path
from drama_core import ContractError, save_new
from source_io import extract_source
from release_contract import WORKFLOW_VERSION, RULES_VERSION, seal, head_record, settings


def initialize(paths, output, title, locale, region, era, episodes, work_id=None):
    output = Path(output)
    if output.exists():
        raise ContractError(f"Refusing existing project directory: {output}")
    defaults=settings({"locale":locale},source_era=era)
    region=region if region is not None else defaults["region"]
    era=era if era is not None else defaults["era"]
    if locale not in ("en-US", "en-GB", "en-CA", "en-AU", "en-IE") or not region.strip() or not era.strip():
        raise ContractError("Explicit locale, region and era are required")
    if not episodes or episodes != sorted(set(episodes)) or any(x < 1 for x in episodes):
        raise ContractError("Episodes must be unique ascending positive integers")
    sources = [extract_source(path, f"SRC{i}") for i, path in enumerate(paths, 1)]
    doc = {"schema_version": 2, "workflow_version": WORKFLOW_VERSION, "rules_version": RULES_VERSION,
           "project": {"id": work_id or uuid.uuid4().hex, "title": title, "revision": 1,
           "locale": locale, "region": region, "era": era, "scope_summary": "等待逐集逐场阅读定位",
           "episodes": episodes, "expected_scene_ids": [], "episode_duration": {}, "status": "draft",
           "audio_status": "not_measured", "video_status": "not_generated"}, "sources": sources,
           **{key: [] for key in ("entities", "scenes", "events", "voices", "segments", "coverage", "reviews", "issues", "narrators", "cultural_decisions")},
           "constraints": {}, "acceptance": {"target_language": [], "media": []}}
    seal(doc)
    output.mkdir(parents=True)
    save_new(output / "project.json", doc)
    save_new(output / "head.json", head_record(doc, output / "project.json"))
    return output / "project.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+")
    for key in ("out", "title"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--locale", default="en-US")
    parser.add_argument("--region")
    parser.add_argument("--era")
    parser.add_argument("--work-id", help="Stable work identity; omitted for a new independent work")
    parser.add_argument("--episodes", required=True, help="comma-separated, e.g. 1,2,3")
    args = parser.parse_args()
    try:
        output = initialize(args.sources, args.out, args.title, args.locale, args.region, args.era,
                            [int(x) for x in args.episodes.split(",")], args.work_id)
        print(f"Imported, NOT yet read/adapted: {output}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
