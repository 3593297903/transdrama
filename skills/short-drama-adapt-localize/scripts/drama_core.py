"""Deterministic text-production checks. No model, network, telemetry or media calls."""
from __future__ import annotations
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path


class ContractError(ValueError):
    pass


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ContractError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path):
    def bad(value):
        raise ContractError(f"Non-finite JSON number: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8-sig"),
                      object_pairs_hook=_pairs, parse_constant=bad)


def save_new(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def digest(value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ContractError("Expected a finite number")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ContractError("Expected a finite number") from exc
    if not result.is_finite():
        raise ContractError("Expected a finite number")
    return result


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def production_counts(doc):
    shots = [shot for seg in doc["segments"] for shot in seg["shots"]]
    return {"source_blocks": sum(len(x["blocks"]) for x in doc["sources"]),
            "read_blocks_declared": sum(b.get("read") is True for s in doc["sources"] for b in s["blocks"]),
            "episodes": doc["project"]["episodes"], "scenes": len(doc["scenes"]),
            "segments": len(doc["segments"]), "shot_fragments": len(shots),
            "planned_continuous_shots": len({s.get("continuous_take_id") or s["id"] for s in shots}),
            "locked_voices": len(doc["voices"]), "narration_voices": sum(v["channel"] == "narration" for v in doc["voices"]),
            "audio_fragments": sum(len(s["audio"]) for s in doc["segments"]),
            "planned_total_seconds": str(sum((number(s["duration"]) for s in doc["segments"]), Decimal(0))),
            "max_segment_seconds": str(max((number(s["duration"]) for s in doc["segments"]), default=Decimal(0))),
            "max_shot_fragment_seconds": str(max((number(s["end"])-number(s["start"]) for s in shots), default=Decimal(0)))}


def index_records(doc):
    index = {"PROJECT": doc["project"]}
    def add(item):
        key = item.get("id")
        if not nonempty(key) or key in index:
            raise ContractError(f"Missing or duplicate ID: {key}")
        index[key] = item
    for group in ("sources", "entities", "scenes", "events", "voices", "segments"):
        for item in doc[group]:
            add(item)
            if group == "sources":
                for block in item["blocks"]:
                    add(block)
    return index


def dependencies(doc):
    index = index_records(doc)
    graph = {key: set(item.get("depends_on", [])) for key, item in index.items()}
    for source in doc["sources"]:
        for block in source["blocks"]:
            graph[block["id"]].add(source["id"])
    for scene in doc["scenes"]:
        graph[scene["id"]].update(["PROJECT", *scene["entity_ids"]])
        if scene.get("previous_scene_id"):
            graph[scene["id"]].add(scene["previous_scene_id"])
    for event in doc["events"]:
        graph[event["id"]].update(["PROJECT", event["scene_id"]])
    for voice in doc["voices"]:
        graph[voice["id"]].update(["PROJECT", voice["scene_id"], *voice["source_ids"],
                                   *voice.get("addressee_ids", [])])
        if voice.get("speaker_id"):
            graph[voice["id"]].add(voice["speaker_id"])
    for segment in doc["segments"]:
        graph[segment["id"]].update(["PROJECT", segment["scene_id"]])
        graph[segment["id"]].update(x["id"] for x in segment["asset_refs"])
        graph[segment["id"]].update(x["voice_id"] for x in segment["audio"])
        for shot in segment["shots"]:
            graph[segment["id"]].update(x["event_id"] for x in shot["event_refs"])
    return index, graph


def closure(graph, roots):
    done, visiting = set(), set()
    def visit(key):
        if key not in graph:
            raise ContractError(f"Unknown dependency: {key}")
        if key in visiting:
            raise ContractError(f"Dependency cycle: {key}")
        if key in done:
            return
        visiting.add(key)
        for dep in graph[key]:
            visit(dep)
        visiting.remove(key)
        done.add(key)
    for root in roots:
        visit(root)
    return done


def snapshots(doc, roots):
    index, graph = dependencies(doc)
    return {key: digest(index[key]) for key in sorted(closure(graph, roots))}


def review_record(doc, review_id, category, scope, reviewer, evidence):
    """Record a review AFTER actual reading; this function performs no semantic review."""
    return {"id": review_id, "category": category, "scope": scope,
            "status": "checked", "reviewer": reviewer, "evidence": evidence,
            "snapshots": snapshots(doc, scope)}


def invalidate_changes(before, after):
    old, _ = dependencies(before)
    new, graph = dependencies(after)
    changed = {key for key in old.keys() | new.keys()
               if key not in old or key not in new or digest(old[key]) != digest(new[key])}
    affected = set(changed)
    while True:
        expanded = affected | {key for key, deps in graph.items() if deps & affected}
        if expanded == affected:
            break
        affected = expanded
    stale = []
    for review in after.get("reviews", []):
        if set(review.get("snapshots", {})) & affected:
            review["status"] = "stale"
            stale.append(review["id"])
    return {"changed_ids": sorted(changed), "affected_ids": sorted(affected),
            "stale_review_ids": stale}


def validate(doc):
    errors, pending = [], []
    def error(code, loc, actual, expected):
        errors.append({"code": code, "location": loc, "actual": actual, "expected": expected})
    def need(code, loc, actual, expected):
        pending.append({"code": code, "location": loc, "actual": actual, "expected": expected})
    def result():
        return {"structural_status": "failed" if errors else "passed",
                "semantic_status": "needs_review" if pending else ("not_evaluated" if errors else "recorded_reviews_current"),
                "overall_status": "failed" if errors else ("review_draft" if pending else "ready_for_text_delivery"),
                "audio_status": "not_measured", "video_status": "not_generated",
                "source_reading": "reader_declaration_not_independent_proof",
                "errors": errors, "review_required": pending}
    if not isinstance(doc, dict) or doc.get("schema_version") != 1:
        error("SCHEMA", "$", None, "schema_version=1 object")
        return result()
    if not isinstance(doc.get("project"), dict):
        error("SHAPE", "project", None, "object")
        return result()
    groups = ("sources", "entities", "scenes", "events", "voices", "segments", "coverage", "reviews", "issues")
    for group in groups:
        if not isinstance(doc.get(group), list) or any(not isinstance(x, dict) for x in doc[group]):
            error("SHAPE", group, None, "array of objects")
    if errors:
        return result()
    # Malformed nested input must produce a failed report, not bypass validation.
    try:
        _validate(doc, error, need)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, RecursionError) as exc:
        error("MALFORMED", "$", str(exc), "data-contract.md structure and valid references")
    report = result()
    if not errors:
        report["counts"] = production_counts(doc)
    return report


def _validate(doc, error, need):
    index, graph = dependencies(doc)
    closure(graph, graph)
    project = doc["project"]
    for key in ("id", "title", "locale", "region", "era", "scope_summary"):
        if not nonempty(project.get(key)):
            error("REQUIRED", f"project.{key}", project.get(key), "nonempty string")
    if project["locale"] not in ("en-US", "en-GB", "en-CA", "en-AU", "en-IE"):
        error("LOCALE", "project.locale", project["locale"], "explicit supported English locale")
    episodes = project["episodes"]
    if not episodes or any(type(x) is not int or x < 1 for x in episodes) or episodes != sorted(set(episodes)):
        error("EPISODES", "project.episodes", episodes, "unique ascending positive integers")
    if project.get("audio_status", "not_measured") != "not_measured":
        error("UNMEASURED", "project.audio_status", project.get("audio_status"), "not_measured (v1 has no audio measurement)")
    if project.get("video_status", "not_generated") != "not_generated":
        error("UNGENERATED", "project.video_status", project.get("video_status"), "not_generated")
    if project.get("status") != "locked":
        need("UNLOCKED", "project.status", project.get("status"), "locked after preflight")
    if not doc["sources"]:
        error("EMPTY_SOURCE", "sources", [], "at least one input")
    blocks = {}
    for source in doc["sources"]:
        sid = source["id"]
        if not isinstance(source.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"]):
            error("SOURCE_HASH", sid, source.get("sha256"), "SHA256 of input bytes")
        if source.get("extraction_status") != "complete" or source.get("limitations"):
            need("SOURCE_PARTIAL", sid, source.get("limitations"), "review missing channels or supply complete source")
        if source.get("reading_status") != "complete" or not source["blocks"]:
            need("SOURCE_UNREAD", sid, source.get("reading_status"), "complete reading")
        for block in source["blocks"]:
            blocks[block["id"]] = block
            if not nonempty(block.get("text")) or not nonempty(block.get("locator")):
                error("SOURCE_BLOCK", block["id"], block, "nonempty text and locator")
            if block.get("read") is not True:
                need("BLOCK_UNREAD", block["id"], block.get("read"), True)
            if block.get("kind") not in ("heading", "action", "dialogue", "offscreen", "narration", "other"):
                error("SOURCE_KIND", block["id"], block.get("kind"), "supported kind")
    entities = {x["id"]: x for x in doc["entities"]}
    for item in entities.values():
        for field in ("name", "description"):
            if not nonempty(item.get(field)):
                error("ASSET_DESCRIPTION", item["id"], item.get(field), field)
        if type(item.get("version")) is not int or item["version"] < 1:
            error("VERSION", item["id"], item.get("version"), "positive integer")
        if item.get("kind") not in ("character", "location", "prop"):
            error("ENTITY_KIND", item["id"], item.get("kind"), "character/location/prop")
        if (item.get("kind") == "character" and item.get("fictional") is True
                and item.get("original_name") == item["name"] and not item.get("inherited_mapping")):
            error("NAME_UNCHANGED", item["id"], item["name"], "new fictional name or confirmed inherited mapping")
        variants = item.get("variants", [])
        if len({x["id"] for x in variants}) != len(variants):
            error("VARIANT_DUPLICATE", item["id"], variants, "unique variant IDs")
    scenes = {x["id"]: x for x in doc["scenes"]}
    expected = project["expected_scene_ids"]
    if len(expected) != len(set(expected)) or set(expected) != set(scenes):
        error("SCENE_COVERAGE", "scenes", list(scenes), expected)
    if set(x["episode"] for x in scenes.values()) != set(episodes):
        error("EPISODE_COVERAGE", "scenes", [x["episode"] for x in scenes.values()], episodes)
    ordering = [(x["episode"], x["order"]) for x in scenes.values()]
    if ordering != sorted(set(ordering)):
        error("SCENE_ORDER", "scenes", ordering, "unique ascending order")
    for scene in scenes.values():
        for field in ("title", "goal", "change", "audience_information", "preflight"):
            if not nonempty(scene.get(field)):
                error("SCENE_REQUIRED", scene["id"], field, "nonempty field")
        for key in scene["entity_ids"]:
            if key not in entities:
                error("ASSET_UNKNOWN", scene["id"], key, "entity ID")
        for field in ("entry_state", "exit_state", "knowledge"):
            if not isinstance(scene.get(field), dict):
                error("STATE_SHAPE", scene["id"], field, "object")
        previous = scene.get("previous_scene_id")
        if previous:
            if previous not in scenes or list(scenes).index(previous) >= list(scenes).index(scene["id"]):
                error("PREVIOUS_SCENE", scene["id"], previous, "earlier scene ID")
            else:
                prior = scenes[previous]["exit_state"]
                for key, value in scene["entry_state"].items():
                    if key in prior and prior[key] != value and not nonempty(scene.get("entry_changes", {}).get(key)):
                        error("STATE_BREAK", scene["id"] + "." + key, value, prior[key])
    events = {x["id"]: x for x in doc["events"]}
    for event in events.values():
        if event["scene_id"] not in scenes or not nonempty(event.get("description")):
            error("EVENT", event["id"], event, "known scene and description")
        if not event["phases"] or len(set(event["phases"])) != len(event["phases"]):
            error("EVENT_PHASES", event["id"], event["phases"], "nonempty unique ordered phases")
    voices = {x["id"]: x for x in doc["voices"]}
    voice_order = []
    for voice in voices.values():
        vid = voice["id"]
        if voice["scene_id"] not in scenes:
            error("VOICE_SCENE", vid, voice["scene_id"], "known scene")
        voice_order.append((list(scenes).index(voice["scene_id"]), voice["order"]))
        for field in ("text", "meaning", "intent"):
            if not nonempty(voice.get(field)):
                error("VOICE_REQUIRED", vid, voice.get(field), field)
        pauses = voice.get("pauses", [])
        if len({p["after_char"] for p in pauses}) != len(pauses):
            error("PAUSE_DUPLICATE", vid, pauses, "unique pause positions")
        for pause in pauses:
            if type(pause["after_char"]) is not int or not 0 < pause["after_char"] < len(voice["text"]) or number(pause["seconds"]) < 0:
                error("PAUSE", vid, pause, "interior character boundary and nonnegative seconds")
        if type(voice.get("version")) is not int or voice["version"] < 1:
            error("VOICE_VERSION", vid, voice.get("version"), "positive integer")
        channel = voice["channel"]
        if channel not in ("dialogue", "offscreen", "narration"):
            error("VOICE_CHANNEL", vid, channel, "supported channel")
        speaker = voice.get("speaker_id")
        if channel == "narration":
            if speaker is not None:
                error("NARRATOR", vid, speaker, None)
        elif speaker not in entities or entities[speaker]["kind"] != "character":
            error("SPEAKER", vid, speaker, "character ID")
        for recipient in voice.get("addressee_ids", []):
            if recipient not in entities or entities[recipient]["kind"] != "character":
                error("ADDRESSEE", vid, recipient, "character ID")
        if not voice["source_ids"]:
            error("VOICE_ORIGIN", vid, [], "source voice IDs")
        for bid in voice["source_ids"]:
            if bid not in blocks or blocks[bid]["kind"] != channel:
                error("SOURCE_CHANNEL", vid, bid, "source block with same channel")
    if voice_order != sorted(set(voice_order)):
        error("VOICE_ORDER", "voices", voice_order, "unique story order")
    covered = set()
    for item in doc["coverage"]:
        bid = item["source_id"]
        if bid not in blocks or bid in covered:
            error("COVERAGE_SOURCE", "coverage", bid, "one record per source block")
        covered.add(bid)
        if not item["target_ids"] or not nonempty(item.get("reason")):
            error("COVERAGE_EMPTY", bid, item, "targets and reason")
        for target in item["target_ids"]:
            if target not in scenes and target not in voices and target not in events:
                error("COVERAGE_TARGET", bid, target, "scene/event/voice ID")
        if bid in blocks and blocks[bid]["kind"] in ("dialogue", "offscreen", "narration"):
            mapped = [voices[x] for x in item["target_ids"] if x in voices]
            if not mapped or any(v["channel"] != blocks[bid]["kind"] or bid not in v["source_ids"] for v in mapped):
                error("SOURCE_VOICE_LOST", bid, item["target_ids"], "traceable voice with same channel")
    if covered != set(blocks):
        error("SOURCE_COVERAGE", "coverage", sorted(covered), sorted(blocks))
    _segments(doc, scenes, entities, events, voices, error, need)
    _reviews(doc, error, need)


def _segments(doc, scenes, entities, events, voices, error, need):
    episode_ends = {x: Decimal(0) for x in doc["project"]["episodes"]}
    rendered_scenes, event_phases, clips = set(), {key: [] for key in events}, {key: [] for key in voices}
    nested_ids, previous_shot, previous_scene = set(index_records(doc)), None, -1
    take_ids = set()
    timeline = []
    for segment in doc["segments"]:
        sid, scid, ep = segment["id"], segment["scene_id"], segment["episode"]
        scene = scenes[scid]
        rank = list(scenes).index(scid)
        if rank < previous_scene or ep != scene["episode"]:
            error("SEGMENT_ORDER", sid, [ep, scid], "matching scene and story order")
        previous_scene = rank
        rendered_scenes.add(scid)
        start, duration = number(segment["start"]), number(segment["duration"])
        if not 0 < duration <= 15:
            error("SEGMENT_DURATION", sid, str(duration), "0 < seconds <= 15")
        if start != episode_ends[ep]:
            error("SEGMENT_GAP", sid, str(start), str(episode_ends[ep]))
        episode_ends[ep] = start + duration
        for field in ("setting", "sound", "atmosphere", "end_state"):
            if not nonempty(segment.get(field)):
                error("SEGMENT_REQUIRED", sid, field, "nonempty description")
        refs = {x["id"]: x for x in segment["asset_refs"]}
        if len(refs) != len(segment["asset_refs"]):
            error("ASSET_REPEAT", sid, list(refs), "unique assets")
        for aid, ref in refs.items():
            asset = entities[aid]
            if aid not in scene["entity_ids"] or ref["version"] != asset["version"]:
                error("ASSET_STALE", sid, ref, "current version of scene asset")
            if ref.get("variant_id") and ref["variant_id"] not in {x["id"] for x in asset.get("variants", [])}:
                error("VARIANT_UNKNOWN", sid, ref.get("variant_id"), "known variant")
            if not nonempty(ref.get("state")):
                error("ASSET_STATE", sid, aid, "explicit current state")
        end = Decimal(0)
        if not segment["shots"]:
            error("SHOTS_EMPTY", sid, [], "at least one shot")
        for shot in segment["shots"]:
            shid = shot["id"]
            if shid in nested_ids:
                error("NESTED_ID", sid, shid, "unique shot/audio ID")
            nested_ids.add(shid)
            a, b = number(shot["start"]), number(shot["end"])
            if a != end or not 0 <= a < b <= duration or b - a > 15:
                error("SHOT_INTERVAL", shid, [str(a), str(b)], "contiguous interval inside segment, <=15s")
            end = b
            for field in ("framing", "camera", "composition", "movement", "action"):
                if not nonempty(shot.get(field)):
                    error("SHOT_REQUIRED", shid, field, "nonempty shot field")
            predecessor = shot.get("continues_shot_id")
            take = shot.get("continuous_take_id")
            if take in take_ids and not predecessor:
                error("CONTINUATION_MISSING", shid, take, "explicit predecessor for a repeated continuous take ID")
            if take:
                take_ids.add(take)
            if predecessor:
                if not (previous_shot and previous_shot["id"] == predecessor
                        and previous_shot["episode"] == ep and shot.get("continuous_take_id")
                        and shot["continuous_take_id"] == previous_shot.get("continuous_take_id")):
                    error("CONTINUATION", shid, predecessor, "immediate preceding shot of same continuous take/episode")
            previous_shot = {**shot, "episode": ep}
            for ref in shot["event_refs"]:
                eid = ref["event_id"]
                if events[eid]["scene_id"] != scid:
                    error("EVENT_SCENE", shid, eid, scid)
                event_phases[eid].extend(ref["phases"])
        if end != duration:
            error("SHOT_COVERAGE", sid, str(end), str(duration))
        for clip in segment["audio"]:
            cid, vid = clip["id"], clip["voice_id"]
            if cid in nested_ids:
                error("NESTED_ID", sid, cid, "unique shot/audio ID")
            nested_ids.add(cid)
            voice = voices[vid]
            a, b = number(clip["start"]), number(clip["end"])
            if not 0 <= a < b <= duration:
                error("AUDIO_INTERVAL", cid, [str(a), str(b)], "positive interval inside segment")
            if voice["scene_id"] != scid:
                error("AUDIO_SCENE", cid, scid, voice["scene_id"])
            for key, expected in (("voice_version", voice["version"]), ("speaker_id", voice.get("speaker_id")), ("channel", voice["channel"])):
                if clip.get(key) != expected:
                    error("AUDIO_ATTRIBUTION", cid + "." + key, clip.get(key), expected)
            if voice.get("speaker_id") and voice["speaker_id"] not in refs:
                error("SPEAKER_ASSET", cid, voice["speaker_id"], "segment asset ref, including offscreen speaker")
            left, right = clip["char_start"], clip["char_end"]
            if type(left) is not int or type(right) is not int or not 0 <= left < right <= len(voice["text"]):
                error("CHAR_RANGE", cid, [left, right], "valid Python character interval")
            elif clip["text"] != voice["text"][left:right]:
                error("VOICE_TEXT", cid, clip["text"], voice["text"][left:right])
            record = {**clip, "global_start": start + a, "global_end": start + b, "episode": ep}
            clips[vid].append(record)
            timeline.append(record)
    if rendered_scenes != set(scenes):
        error("OUTPUT_SCENE_COVERAGE", "segments", sorted(rendered_scenes), list(scenes))
    for eid, phases in event_phases.items():
        if phases != events[eid]["phases"]:
            error("EVENT_COVERAGE", eid, phases, events[eid]["phases"])
    for vid, parts in clips.items():
        cursor, previous = 0, None
        for part in parts:
            if part["char_start"] != cursor:
                error("VOICE_SLICE_COVERAGE", vid, part["char_start"], cursor)
            if previous:
                pause = next((number(p["seconds"]) for p in voices[vid].get("pauses", []) if p["after_char"] == cursor), Decimal(0))
                if part["episode"] != previous["episode"] or part["global_start"] != previous["global_end"] + pause:
                    error("VOICE_CONTINUITY", vid, str(part["global_start"]), str(previous["global_end"] + pause))
            cursor, previous = part["char_end"], part
        if cursor != len(voices[vid]["text"]):
            error("VOICE_INCOMPLETE", vid, cursor, len(voices[vid]["text"]))
    ordered = sorted(timeline, key=lambda x: (x["episode"], x["global_start"]))
    first = list(dict.fromkeys(x["voice_id"] for x in ordered))
    if first != list(voices):
        error("PLAYBACK_ORDER", "audio", first, list(voices))
    for i, clip in enumerate(ordered):
        for prior in ordered[:i]:
            if prior["episode"] == clip["episode"] and prior["global_end"] > clip["global_start"]:
                group = voices[clip["voice_id"]].get("overlap_group")
                if not group or group != voices[prior["voice_id"]].get("overlap_group"):
                    error("AUDIO_OVERLAP", clip["id"], prior["id"], "nonoverlap or locked shared overlap_group")
    for ep, total in episode_ends.items():
        constraint = doc["project"]["episode_duration"].get(str(ep))
        if not constraint or constraint.get("kind") not in ("hard", "reference", "planned") or not nonempty(constraint.get("basis")):
            error("DURATION_BASIS", str(ep), constraint, "kind, seconds and basis")
        elif total != number(constraint["seconds"]):
            handler = error if constraint["kind"] in ("hard", "planned") else need
            handler("EPISODE_DURATION", str(ep), str(total), str(constraint["seconds"]))


def _reviews(doc, error, need):
    expected = {
        "adaptation": {"PROJECT", *[x["id"] for group in ("entities", "scenes", "events") for x in doc[group]]},
        "english": {x["id"] for x in doc["voices"]},
        "feasibility": {x["id"] for x in doc["segments"]},
        "visual_storytelling": {x["id"] for x in doc["segments"]},
    }
    covered = {key: set() for key in expected}
    ids = set()
    for review in doc["reviews"]:
        rid, category = review["id"], review["category"]
        if rid in ids or category not in expected:
            error("REVIEW_ID_CATEGORY", rid, category, "unique ID / known category")
            continue
        ids.add(rid)
        if (review.get("status") != "checked" or not nonempty(review.get("reviewer"))
                or not nonempty(review.get("evidence"))):
            need("REVIEW_PENDING", rid, review.get("status"), "actual review with evidence")
        elif review.get("snapshots") != snapshots(doc, review["scope"]):
            need("REVIEW_STALE", rid, None, "re-review affected current records")
        else:
            covered[category].update(review["scope"])
    for category, scope in expected.items():
        missing = scope - covered[category]
        if missing:
            need("REVIEW_COVERAGE", category, sorted(missing), "current recorded semantic review")
    for issue in doc["issues"]:
        if issue.get("status") != "resolved":
            need("OPEN_ISSUE", issue.get("id"), issue.get("detail"), "resolved or explicitly delivered as review draft")
        elif not nonempty(issue.get("resolution")):
            error("ISSUE_EVIDENCE", issue.get("id"), None, "resolution evidence")
