"""Schema 2 release records. These helpers track evidence, not semantic truth."""
import copy
import json
import os
import re
import uuid
from pathlib import Path
from contextlib import contextmanager
from drama_core import ContractError, digest, load_json, nonempty, save_new

SCHEMA_VERSION = 2
WORKFLOW_VERSION = "B-release-2.0"
RULES_VERSION = "2026-10-14.1"
REVIEW_CATEGORIES = ("adaptation", "english_fidelity", "english_viewing",
                     "feasibility", "visual_storytelling", "full_read")
NON_CONTENT = {"lineage", "reviews", "issues", "acceptance", "progress", "operations", "handoff"}
PROJECT_METADATA = {"revision", "status", "audio_status", "video_status"}


def project_content(doc):
    return {"project": {k: v for k, v in doc["project"].items() if k not in PROJECT_METADATA},
            "workflow_version": doc["workflow_version"], "rules_version": doc["rules_version"],
            "constraints": doc.get("constraints", {})}


def content_hash(doc):
    payload = {k: v for k, v in doc.items() if k not in NON_CONTENT}
    payload["project"] = project_content(doc)["project"]
    return digest(payload)


def source_fingerprint(doc):
    return digest([{ "id": s["id"], "sha256": s["sha256"]} for s in doc["sources"]])


def seal(doc, parent=None, branch_id=None):
    """Seal authored content; this never adds successful reviews or closes issues."""
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("seal requires schema 2; migrate legacy data explicitly")
    prior = doc.get("lineage", {})
    doc["lineage"] = {"content_hash": content_hash(doc),
        "parent_content_hash": content_hash(parent) if parent else prior.get("parent_content_hash"),
        "parent_revision": parent["project"]["revision"] if parent else prior.get("parent_revision"),
        "source_fingerprint": source_fingerprint(doc),
        "branch_id": branch_id or prior.get("branch_id", "main")}
    return doc


def settings(current=None, confirmed=None, source_era=None):
    result = {"locale": "en-US", "era": source_era or "原稿待识别"}
    result.update(confirmed or {})
    result.update(current or {})
    if "region" not in result:
        markets={"en-US":"美国","en-GB":"英国","en-CA":"加拿大","en-AU":"澳大利亚","en-IE":"爱尔兰"}
        result["region"]=markets.get(result["locale"],"目标地区待确定")+"；具体地区待原稿适配"
    return result


def augment_index(doc, index):
    index["PROJECT"] = project_content(doc)
    # Range expansion is covered by required scopes, without changing the
    # meaning of an unrelated, already reviewed scene. Still in content_hash.
    index["PROJECT"]["project"] = {k:v for k,v in index["PROJECT"]["project"].items()
                                   if k not in ("episodes","expected_scene_ids","scope_summary")}
    def add(key, value):
        if not nonempty(key) or key in index:
            raise ContractError("Missing, duplicate or reserved release ID: " + str(key))
        index[key] = value
    for narrator in doc.get("narrators", []):
        add(narrator["id"], narrator)
    for cov in doc["coverage"]:
        add("COV:" + cov["source_id"], cov)
    for decision in doc.get("cultural_decisions", []):
        add("CULTURE:" + decision["id"], decision)
    for scene in doc["scenes"]:
        add("CONTEXT:" + scene["id"], {"scene": scene,
            "voices": [v for v in doc["voices"] if v["scene_id"] == scene["id"]],
            "events": [e for e in doc["events"] if e["scene_id"] == scene["id"]]})
    return index


def augment_graph(doc, graph):
    for decision in doc.get("cultural_decisions", []):
        for target in decision.get("affected_ids", [s["id"] for s in doc["scenes"]]):
            graph[target].add("CULTURE:" + decision["id"])
    for cov in doc["coverage"]:
        key = "COV:" + cov["source_id"]
        graph[key].add(cov["source_id"])
        for target in cov["target_ids"]:
            graph[target].add(key)
    for narrator in doc.get("narrators", []):
        if narrator.get("character_id"):
            graph[narrator["id"]].add(narrator["character_id"])
    for voice in doc["voices"]:
        if voice.get("narrator_id"):
            graph[voice["id"]].add(voice["narrator_id"])
    for scene in doc["scenes"]:
        key = "CONTEXT:" + scene["id"]
        graph[key].add(scene["id"])
        graph[key].update(v["id"] for v in doc["voices"] if v["scene_id"] == scene["id"])
        graph[key].update(e["id"] for e in doc["events"] if e["scene_id"] == scene["id"])
        graph[scene["id"]].update(scene.get("context_scene_ids", []))
        if scene.get("previous_scene_id"):
            graph[scene["id"]].add("CONTEXT:" + scene["previous_scene_id"])
        graph[scene["id"]].update("CONTEXT:" + sid for sid in scene.get("context_scene_ids", []))
    return graph


def review_roots(doc, category, scope):
    roots = set(scope)
    if category in ("adaptation", "english_fidelity", "english_viewing", "full_read"):
        scenes = {x["id"] for x in doc["scenes"] if x["id"] in roots}
        scenes.update(v["scene_id"] for v in doc["voices"] if v["id"] in roots)
        roots.update("CONTEXT:" + key for key in scenes)
    return sorted(roots)


def make_review(doc, rid, category, scope, reviewer, evidence, test_record=False):
    from drama_core import snapshots
    if category not in REVIEW_CATEGORIES or not scope or not nonempty(evidence) or not nonempty(reviewer):
        raise ContractError("Review needs a known category, nonempty scope, reviewer and actual evidence")
    return {"id": rid, "category": category, "scope": list(scope), "status": "checked",
        "work_id": doc["project"]["id"], "reviewer": reviewer, "evidence": evidence,
        "kind": "test" if test_record else "same_source_ai", "result": "KEEP",
        "snapshots": snapshots(doc, review_roots(doc, category, scope))}


def required_review_scopes(doc):
    assets = {x["id"] for g in ("entities", "scenes", "events", "narrators") for x in doc.get(g, [])}
    cov = {"COV:" + x["source_id"] for x in doc["coverage"]}
    culture = {"CULTURE:" + x["id"] for x in doc.get("cultural_decisions", [])}
    voices, segments = {v["id"] for v in doc["voices"]}, {s["id"] for s in doc["segments"]}
    return {"adaptation": {"PROJECT"} | assets | cov | culture,
            "english_fidelity": voices, "english_viewing": voices,
            "feasibility": segments, "visual_storytelling": segments,
            "full_read": {s["id"] for s in doc["scenes"]} | voices | segments | cov | culture}


def _current_record(doc, record, roots):
    from drama_core import snapshots
    return (record.get("work_id") == doc["project"]["id"]
            and record.get("status") == "checked"
            and record.get("snapshots") == snapshots(doc, roots))


def validate_reviews(doc, error, need):
    expected = required_review_scopes(doc)
    covered = {key: set() for key in expected}
    ids = set()
    for record in doc["reviews"]:
        rid, category = record.get("id"), record.get("category")
        if not nonempty(rid) or rid in ids:
            error("REVIEW_ID_CATEGORY", rid, category, "unique nonempty ID")
            continue
        ids.add(rid)
        if category not in expected:
            need("LEGACY_REVIEW", rid, category, "current release review category after actual re-reading")
            continue
        if (not isinstance(record.get("scope"), list) or not record["scope"]
                or not nonempty(record.get("reviewer")) or not nonempty(record.get("evidence"))
                or record.get("kind") not in ("same_source_ai", "test") or record.get("result") != "KEEP"):
            need("REVIEW_INCOMPLETE", rid, record.get("status"), "located reading evidence, scope, kind and KEEP result")
            continue
        if record.get("work_id") != doc["project"]["id"]:
            error("REVIEW_WORK", rid, record.get("work_id"), doc["project"]["id"])
        elif record["kind"] == "test" and not doc["project"].get("test_fixture"):
            need("SIMULATED_REVIEW", rid, "test", "actual AI reading for production")
        elif not _current_record(doc, record, review_roots(doc, category, record["scope"])):
            need("REVIEW_STALE" if record.get("status") == "checked" else "REVIEW_PENDING", rid,
                 record.get("status"), "successful actual reading of current dependencies")
        else:
            covered[category].update(record["scope"])
    for category, scope in expected.items():
        if scope - covered[category]:
            need("REVIEW_COVERAGE", category, sorted(scope - covered[category]), "current full scope reading")
    validate_issues(doc, error, need)


def validate_issues(doc, error, need):
    from drama_core import index_records
    index, ids, attempts, locations = index_records(doc), set(), {}, {}
    for issue in doc["issues"]:
        rid = issue.get("id")
        if not nonempty(rid) or rid in ids:
            error("ISSUE_ID", rid, None, "unique issue ID")
        ids.add(rid)
        if issue.get("legacy_status") is not None and issue.get("status") == "needs_review":
            if type(issue.get("attempts",0)) is not int or not 0 <= issue.get("attempts",0) <= 2:
                error("REPAIR_LIMIT",rid,issue.get("attempts"),"preserve and inspect exhausted legacy repair budget")
            need("LEGACY_ISSUE",rid,issue.get("detail"),"locate and re-evaluate old evidence; migration does not invent missing judgments")
            continue
        for field in ("scene_id", "excerpt", "category", "evidence", "allowed_layer", "detail"):
            if not nonempty(issue.get(field)):
                error("ISSUE_REQUIRED", str(rid) + "." + field, issue.get(field), "nonempty located evidence")
        if issue.get("scene_id") not in {s["id"] for s in doc["scenes"]}:
            error("ISSUE_LOCATION", rid, issue.get("scene_id"), "known scene")
        voice = index.get(issue.get("voice_id")) if issue.get("voice_id") else None
        if issue.get("voice_id") and (voice not in doc["voices"] or issue.get("excerpt", "") not in voice["text"]):
            # Fixed excerpts may belong to the pre-repair version, retained as evidence.
            if not nonempty(issue.get("original_excerpt")) or issue["original_excerpt"] != issue.get("excerpt"):
                error("ISSUE_EXCERPT", rid, issue.get("excerpt"), "current quote or retained original_excerpt")
        severity, confidence, classification = issue.get("severity"), issue.get("confidence"), issue.get("classification")
        if severity not in ("minor", "major", "critical") or confidence not in ("low", "medium", "high") or classification not in ("confirmed", "context", "preference"):
            error("ISSUE_CLASSIFICATION", rid, [severity, confidence, classification], "severity/confidence/classification enums")
        if severity in ("major", "critical") and (classification != "confirmed" or confidence != "high"):
            error("ISSUE_UNSUPPORTED_SEVERITY", rid, severity, "major errors need confirmed high-confidence evidence")
        if issue.get("allowed_layer") not in ("facts", "expression", "schedule", "shots"):
            error("ISSUE_LAYER", rid, issue.get("allowed_layer"), "facts/expression/schedule/shots")
        count = issue.get("attempts")
        if type(count) is not int or not 0 <= count <= 2:
            error("REPAIR_LIMIT", rid, count, "0..2 attempts; exhaustion is not success")
            count = 0
        root = issue.get("root_issue_id", rid)
        attempts[root] = attempts.get(root, 0) + count
        location = (issue.get("scene_id"), issue.get("voice_id"),
                    issue.get("original_excerpt", issue.get("excerpt")), issue.get("category"))
        locations[location] = locations.get(location, 0) + count
        status = issue.get("status")
        if status in ("resolved", "writer_decided", "user_confirmed"):
            if not nonempty(issue.get("resolution")):
                error("ISSUE_EVIDENCE", rid, None, "resolution and current-version recheck")
            if status == "writer_decided" and classification == "confirmed" and severity in ("major", "critical"):
                need("MAJOR_ISSUE", rid, issue.get("detail"), "repair confirmed major error")
            if status == "user_confirmed" and not nonempty(issue.get("user_confirmation")):
                error("USER_CONFIRMATION", rid, None, "actual user confirmation source")
            check = issue.get("recheck", {})
            roots = check.get("scope", [])
            if (issue.get("scene_id") not in roots or not nonempty(check.get("evidence")) or check.get("result") != "KEEP"
                    or not _current_record(doc, check, review_roots(doc, "english_fidelity", roots))):
                need("ISSUE_RECHECK", rid, status, "whole repaired scene and affected context re-read at current dependencies")
        else:
            need("OPEN_ISSUE", rid, issue.get("detail"), "located repair or explicit review draft")
    for root, total in attempts.items():
        if root not in ids:
            error("ISSUE_ROOT", root, None, "existing original issue ID")
        if total > 2:
            error("REPAIR_LIMIT", root, total, "at most two attempts across linked issues")
    for location, total in locations.items():
        if total > 2:
            error("REPAIR_LIMIT", str(location), total, "renaming the same located problem does not reset attempts")


def validate_release(doc, error, need):
    from drama_core import nonempty
    p = doc["project"]
    supported={"schema_version","workflow_version","rules_version","project","sources","entities","narrators",
               "scenes","events","voices","segments","coverage","reviews","issues","constraints","cultural_decisions",
               "acceptance","lineage","handoff","progress","operations"}
    if set(doc)-supported:
        need("UNVALIDATED_EXTENSION", "$", sorted(set(doc)-supported), "explicitly map/review unsupported semantic extensions")
    if not isinstance(doc.get("constraints"), dict):
        error("CONSTRAINTS_SHAPE", "constraints", doc.get("constraints"), "per-work authorization and facts object")
    if type(p.get("revision")) is not int or p["revision"] < 1:
        error("REVISION", "project.revision", p.get("revision"), "positive integer")
    if doc.get("workflow_version") != WORKFLOW_VERSION or doc.get("rules_version") != RULES_VERSION:
        need("RULE_VERSION", "$", [doc.get("workflow_version"), doc.get("rules_version")], "explicit migration/review for current rules")
    lineage = doc.get("lineage", {})
    if lineage.get("content_hash") != content_hash(doc):
        error("CONTENT_HASH", "lineage.content_hash", lineage.get("content_hash"), "sealed current content fingerprint")
    if lineage.get("source_fingerprint") != source_fingerprint(doc):
        error("SOURCE_FINGERPRINT", "lineage", None, "current source hashes")
    if not nonempty(lineage.get("branch_id")):
        error("BRANCH_ID", "lineage.branch_id", None, "nonempty explicit branch identity")
    parent, revision = lineage.get("parent_content_hash"), lineage.get("parent_revision")
    if (parent is None) != (revision is None) or (parent is not None and
            (not isinstance(parent, str) or not re.fullmatch(r"[0-9a-f]{64}",parent) or type(revision) is not int or not 0 < revision < p["revision"])):
        error("PARENT_VERSION", "lineage", [parent, revision], "paired parent hash and earlier positive revision")
    for entity in doc["entities"]:
        if entity["kind"] == "character":
            for field in ("age_stage", "voice_profile"):
                if not nonempty(entity.get(field)):
                    need("IDENTITY_UNRESOLVED", entity["id"] + "." + field, entity.get(field), "needed identity, no guessed precise age")
            if entity.get("relationship") and not nonempty(entity.get("relationship_basis")):
                need("RELATIONSHIP_BASIS", entity["id"], None, "action/trust basis visible in existing interaction")
            if not isinstance(entity.get("address_forms", {}), dict):
                error("ADDRESS_FORMS", entity["id"], None, "object of person ID to address")
    narrators = {n["id"]: n for n in doc.get("narrators", [])}
    characters = {x["id"] for x in doc["entities"] if x["kind"] == "character"}
    for narrator in narrators.values():
        nid = narrator["id"]
        if narrator.get("type") == "unknown":
            need("NARRATOR_UNRESOLVED", nid, "unknown", "contextual determination of narrator")
        elif narrator.get("type") not in ("external", "present_inner", "future_recollection"):
            error("NARRATOR_TYPE", nid, narrator.get("type"), "external/present_inner/future_recollection/unknown")
        for field in ("time_view", "event_age_stage", "speaking_age_stage", "knowledge_boundary", "reliability"):
            if narrator.get(field) is not None and not isinstance(narrator[field], str):
                error("NARRATOR_FIELD_TYPE", nid + "." + field, narrator[field], "string or unresolved null")
            elif not nonempty(narrator.get(field)):
                need("NARRATOR_IDENTITY", nid + "." + field, None, "explicit identity or unresolved, no invented age")
        if narrator.get("time_view") not in (None,"present","past","future","unknown"):
            error("NARRATOR_TIME", nid, narrator["time_view"], "present/past/future/unknown")
        if narrator.get("type") in ("present_inner", "future_recollection") and narrator.get("character_id") not in characters:
            error("NARRATOR_CHARACTER", nid, narrator.get("character_id"), "known character")
        audible = narrator.get("audible_to", [])
        if not isinstance(audible, list) or any(x not in characters for x in audible):
            error("NARRATOR_AUDIBILITY", nid, audible, "known listeners, empty for unspoken narration")
        if narrator.get("type") in ("present_inner", "future_recollection") and audible:
            error("NARRATOR_AUDIBILITY", nid, audible, "unspoken inner/recollection channel")
    for voice in doc["voices"]:
        if voice["channel"] in ("narration", "inner"):
            narrator = narrators.get(voice.get("narrator_id"))
            if narrator is None:
                need("NARRATOR_MISSING", voice["id"], None, "independent narrator identity")
            elif (voice["channel"] == "inner") != (narrator.get("type") == "present_inner") and narrator.get("type") != "unknown":
                error("NARRATOR_CHANNEL", voice["id"], narrator["type"], "matching inner versus narration channel")
        if "semantic_limits" in voice and not isinstance(voice["semantic_limits"], dict):
            error("SEMANTIC_LIMITS", voice["id"], voice["semantic_limits"], "optional high-risk constraints object")
    scenes = doc["scenes"]
    for i, scene in enumerate(scenes):
        knowledge = scene["knowledge"]
        people = knowledge.get("characters")
        if not isinstance(people, dict) or not isinstance(knowledge.get("audience"), list):
            need("KNOWLEDGE_UNRESOLVED", scene["id"], None, "characters with distinct knowledge/beliefs/pretends/withholds and audience list")
        else:
            for cid, state in people.items():
                if cid not in characters or not isinstance(state, dict) or any(
                        not isinstance(state.get(k), list) or any(not nonempty(x) for x in state[k])
                        for k in ("knows","beliefs","pretends","withholds")):
                    error("KNOWLEDGE_SHAPE", scene["id"]+"."+cid, state, "known character and four explicit fact lists")
            for cid in characters & set(scene["entity_ids"]):
                asset=next(e for e in doc["entities"] if e["id"]==cid)
                if asset.get("role")!="mentioned" and cid not in people:
                    need("KNOWLEDGE_UNRESOLVED", scene["id"]+"."+cid, None, "on-scene character state, no author omniscience")
        if not nonempty(scene.get("entry_reason")):
            need("ENTRY_REASON", scene["id"], None, "reason for entering this scene")
        mode = scene.get("continuity")
        if mode not in ("new_context", "continues"):
            need("CONTINUITY_UNKNOWN", scene["id"], mode, "explicit new context or continued scene")
        if i and mode == "continues":
            if scene.get("previous_scene_id") != scenes[i-1]["id"]:
                error("CONTINUITY_LINK", scene["id"], scene.get("previous_scene_id"), scenes[i-1]["id"])
            keys = set(scene.get("critical_state_keys", [])) | set(scenes[i-1].get("critical_state_keys", []))
            for key in keys:
                if any(key not in state for state in (scene["entry_state"], scene["exit_state"], scenes[i-1]["exit_state"])):
                    error("STATE_REQUIRED", scene["id"] + "." + key, None, "key present across continued states")
        prior_ids = {s["id"] for s in scenes[:i]}
        for key in scene.get("context_scene_ids", []):
            if key not in prior_ids:
                error("CONTEXT_ORDER", scene["id"], key, "earlier context scene")
    for decision in doc.get("cultural_decisions", []):
        if type(decision.get("affects_cause")) is not bool:
            error("CULTURAL_TYPE",decision.get("id"),decision.get("affects_cause"),"explicit boolean affects_cause")
        if decision.get("action") not in ("keep", "adapt", "verify", "unresolved") or not nonempty(decision.get("reason")):
            error("CULTURAL_DECISION", decision.get("id"), decision, "keep/adapt/verify/unresolved and rationale")
        if decision.get("affects_cause") and (decision.get("action") == "unresolved" or
                decision.get("action") == "verify" and not (decision.get("status") == "verified" and
                nonempty(decision.get("evidence")) and nonempty(decision.get("region")) and nonempty(decision.get("era")))):
            need("WORLD_FACT_UNRESOLVED", decision.get("id"), decision.get("reason"), "reliable region/era evidence for causal premise")
    validate_acceptance(doc, error, need)
    if doc.get("handoff"):
        h = doc["handoff"]
        if h.get("work_id") != p["id"] or h.get("content_hash") != lineage.get("content_hash"):
            need("HANDOFF_STALE", "handoff", None, "rebuild navigation checkpoint from current state")


def validate_acceptance(doc, error, need):
    for category in ("target_language", "media"):
        for record in doc.get("acceptance", {}).get(category, []):
            rid = record.get("id")
            mandatory = ("reviewer_source", "qualification", "date", "evidence")
            if record.get("kind") != "real_attested" or any(not nonempty(record.get(k)) for k in mandatory):
                error("ACCEPTANCE_EVIDENCE", rid, record.get("kind"), "real attributed reviewer/measurement evidence; no simulated certification")
            if category == "media":
                artifacts = record.get("artifacts", [])
                if not artifacts or any(not nonempty(a.get("name")) or not isinstance(a.get("sha256"), str)
                                        or len(a["sha256"]) != 64 for a in artifacts):
                    error("MEDIA_ARTIFACT", rid, artifacts, "actual identified media artifacts and byte hashes")
                if not isinstance(record.get("measured_dimensions"), list) or not record["measured_dimensions"]:
                    error("MEDIA_DIMENSIONS", rid, None, "explicit dimensions actually heard/viewed, no implied all-media pass")
            roots = record.get("scope", [])
            if not roots or record.get("result") != "KEEP" or not _current_record(doc, record, review_roots(doc, "full_read", roots)):
                need("ACCEPTANCE_STALE", rid, record.get("status"), "actual current scope and dependency fingerprint")
            if record.get("content_hash") != doc["lineage"]["content_hash"] or record.get("revision") != doc["project"]["revision"]:
                need("ACCEPTANCE_STALE", rid, None, "exact actual content version and fingerprint")


def acceptance_summary(doc):
    expected = required_review_scopes(doc)["full_read"]
    def status(category):
        records = doc.get("acceptance", {}).get(category, [])
        if not records:
            return "not_performed"
        covered = set()
        for r in records:
            if (r.get("kind") == "real_attested" and all(nonempty(r.get(k)) for k in
                    ("reviewer_source", "qualification", "date", "evidence")) and r.get("result") == "KEEP"
                    and r.get("content_hash") == doc["lineage"]["content_hash"] and r.get("revision") == doc["project"]["revision"]
                    and _current_record(doc, r, review_roots(doc, "full_read", r.get("scope", [])))):
                covered.update(r["scope"])
        return "recorded_full_scope_not_independent_certification" if expected <= covered else "partial_or_stale"
    return {"target_language": status("target_language"), "media": status("media"),
            "qualification_note": "Records cannot independently prove a reviewer's competence."}


def recovery_summary(doc):
    from drama_core import validate
    report = validate(doc)
    complete = set()
    for r in doc["reviews"]:
        if not report["errors"] and r.get("category") == "full_read" and r.get("status") == "checked" and not any(
                x["location"] == r.get("id") for x in report["review_required"]):
            complete.update(r.get("scope", []))
    scenes = [s["id"] for s in doc["scenes"]]
    return {"work_id": doc["project"]["id"], "revision": doc["project"]["revision"],
        "content_hash": doc.get("lineage", {}).get("content_hash"), "locked": doc["project"]["status"] == "locked",
        "sources": [{"id": s["id"], "name": s["name"], "sha256": s["sha256"],
                     "limitations": s["limitations"], "unread_ids": [b["id"] for b in s["blocks"] if b.get("read") is not True]} for s in doc["sources"]],
        "completed_scene_ids": [s for s in scenes if s in complete],
        "last_completed_scene": next((s for s in reversed(scenes) if s in complete), None),
        "remaining_scene_ids": [s for s in scenes if s not in complete],
        "unresolved": report["review_required"], "errors": report["errors"],
        "next_step": "Read complete current scenes and source blocks behind unresolved records; summaries are navigation only."}


def migrate(doc):
    if doc.get("schema_version") != 1:
        raise ContractError("Only schema 1 migrates to 2; never downgrade a newer schema")
    new = copy.deepcopy(doc)
    new.update(schema_version=2, workflow_version=WORKFLOW_VERSION, rules_version=RULES_VERSION)
    new.setdefault("constraints", {})
    new.setdefault("narrators", [])
    new.setdefault("cultural_decisions", [])
    new.setdefault("acceptance", {"target_language": [], "media": []})
    for scene in new["scenes"]:
        scene.setdefault("continuity", "unknown")
        scene.setdefault("entry_reason", "")
    for voice in new["voices"]:
        if voice["channel"] == "narration" and not voice.get("narrator_id"):
            nid = "NARRATOR:" + voice["id"]
            voice["narrator_id"] = nid
            new["narrators"].append({"id": nid, "type": "unknown", "audible_to": []})
    for review in new["reviews"]:
        review["status"] = "stale"
    for issue in new["issues"]:
        issue["legacy_status"] = issue.get("status")
        issue["status"] = "needs_review"
    new.setdefault("operations", []).append({"operation": "migration", "from_schema": 1, "original_document_hash": digest(doc)})
    return seal(new)


def guard_revision(before, after, head=None, branch=None):
    if before.get("schema_version") != 2 or after.get("schema_version") != 2:
        raise ContractError("Revision requires two schema 2 states; migrate legacy states separately")
    if before.get("rules_version") != after.get("rules_version") or before.get("workflow_version") != after.get("workflow_version"):
        raise ContractError("RULE_MIGRATION: rule/workflow changes require a separately reviewed migration, not a silent ordinary revision")
    if before["project"]["id"] != after["project"]["id"]:
        raise ContractError("WORK_MISMATCH: revision belongs to a different work")
    if before["lineage"]["content_hash"] != content_hash(before) or after["lineage"]["content_hash"] != content_hash(after):
        raise ContractError("CONTENT_HASH: seal actual before/proposed content before revising")
    if type(after["project"].get("revision")) is not int or after["project"]["revision"] <= before["project"]["revision"]:
        raise ContractError("REVISION_ROLLBACK: proposed revision must increase")
    if (after["lineage"].get("parent_content_hash") != before["lineage"]["content_hash"] or
            after["lineage"].get("parent_revision") != before["project"]["revision"]):
        raise ContractError("PARENT_MISMATCH: proposed state must name exact parent fingerprint and revision")
    if not branch and after["lineage"]["branch_id"] != before["lineage"]["branch_id"]:
        raise ContractError("BRANCH_REQUIRED: use explicit branch option")
    if head and (head.get("work_id"), head.get("revision"), head.get("content_hash"), head.get("branch_id")) != (
            before["project"]["id"], before["project"]["revision"], before["lineage"]["content_hash"], before["lineage"]["branch_id"]):
        raise ContractError("STALE_HEAD: read the latest state named by head.json before writing")


def head_record(doc, state_path, head_path=None):
    base=Path(head_path).resolve().parent if head_path else Path(state_path).resolve().parent
    return {"work_id": doc["project"]["id"], "revision": doc["project"]["revision"],
            "content_hash": doc["lineage"]["content_hash"], "branch_id": doc["lineage"]["branch_id"],
            "state_path": os.path.relpath(Path(state_path).resolve(),base), "note":"Resolve relative to head directory; current pointer, never approval"}


@contextmanager
def head_lock(path):
    lock = Path(str(path) + ".lock")
    try:
        with lock.open("x", encoding="utf-8") as f:
            f.write("Exclusive revision in progress; interruption requires inspect-and-recover, not automatic removal.")
    except FileExistsError as exc:
        raise ContractError("Head is locked; inspect interrupted/concurrent revision before recovery") from exc
    try:
        yield
    finally:
        lock.unlink()


def write_revision(before, after, out, head_path, branch=None):
    from drama_core import invalidate_changes
    out, head_path = Path(out), Path(head_path)
    if out.exists():
        raise ContractError("Refusing existing state: " + str(out))
    with head_lock(head_path):
        if branch:
            if head_path.exists():
                raise ContractError("Explicit branch requires a new head path; existing heads are preserved")
            if after["lineage"]["branch_id"] != branch or branch == before["lineage"]["branch_id"]:
                raise ContractError("New branch identity must match explicit branch option")
            guard_revision(before, after, branch=branch)
        else:
            if not head_path.exists():
                raise ContractError("Current head.json is required; do not silently revive an old head")
            guard_revision(before, after, load_json(head_path))
        report = invalidate_changes(before, after, check_revision=False)
        save_new(out, after)
        temp = head_path.with_name(head_path.name + ".pending-" + uuid.uuid4().hex)
        save_new(temp, head_record(after, out, head_path))
        os.replace(temp, head_path)
    return report
