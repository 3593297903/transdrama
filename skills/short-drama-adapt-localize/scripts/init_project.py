"""Create a non-overwriting import checkpoint. Does not adapt or claim to read."""
import argparse
from pathlib import Path
from drama_core import ContractError, save_new
from source_io import extract_source


def initialize(paths, output, title, locale, region, era, episodes):
    output = Path(output)
    if output.exists():
        raise ContractError(f"Refusing existing project directory: {output}")
    if locale not in ("en-US", "en-GB", "en-CA", "en-AU", "en-IE") or not region.strip() or not era.strip():
        raise ContractError("Explicit locale, region and era are required")
    if not episodes or episodes != sorted(set(episodes)) or any(x < 1 for x in episodes):
        raise ContractError("Episodes must be unique ascending positive integers")
    sources = [extract_source(path, f"SRC{i}") for i, path in enumerate(paths, 1)]
    doc = {"schema_version": 1, "project": {"id": output.name, "title": title, "revision": 1,
           "locale": locale, "region": region, "era": era, "scope_summary": "等待逐集逐场阅读定位",
           "episodes": episodes, "expected_scene_ids": [], "episode_duration": {}, "status": "draft",
           "audio_status": "not_measured", "video_status": "not_generated"}, "sources": sources,
           **{key: [] for key in ("entities", "scenes", "events", "voices", "segments", "coverage", "reviews", "issues")}}
    output.mkdir(parents=True)
    save_new(output / "project.json", doc)
    return output / "project.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+")
    for key in ("out", "title", "locale", "region", "era"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--episodes", required=True, help="comma-separated, e.g. 1,2,3")
    args = parser.parse_args()
    try:
        output = initialize(args.sources, args.out, args.title, args.locale, args.region, args.era,
                            [int(x) for x in args.episodes.split(",")])
        print(f"Imported, NOT yet read/adapted: {output}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
