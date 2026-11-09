"""Export a single canonical text to TXT and optional DOCX; re-read both."""
import argparse
import json
import hashlib
import uuid
from pathlib import Path
from drama_core import ContractError, load_json, save_new, validate, digest


def canonical_lines(doc, review_draft=False):
    p = doc["project"]
    lines = [p["title"] + ("（待核审稿版）" if review_draft else ""),
             f"地区：{p['region']}；年代：{p['era']}；英语：{p['locale']}",
             "所有时长为制作规划；未进行音频实测或视频生成。9:16、2160×3840为输出目标。"]
    entities = {x["id"]: x for x in doc["entities"]}
    narrators = {x["id"]: x for x in doc.get("narrators", [])}
    if doc["schema_version"] == 2:
        from release_contract import acceptance_summary
        acceptance = acceptance_summary(doc)
        human_label = {"not_performed":"未做真实目标语终审／待终审",
                       "partial_or_stale":"真实终审记录不全或已过期",
                       "recorded_full_scope_not_independent_certification":"有全范围真实记录；程序不独立认证审者能力"}[acceptance["target_language"]]
        media_label = "未实听实看" if acceptance["media"] == "not_performed" else acceptance["media"]
        lines += [f"作品：{p['id']}；内容版本：{p['revision']}；规则：{doc['rules_version']}",
                  "内容指纹：" + doc["lineage"]["content_hash"],
                  "验收：结构与覆盖见附件；" + ("AI审读为测试模拟记录" if any(r.get("kind") == "test" for r in doc["reviews"]) else "AI审读为同源审读") + "；真实目标语终审：" + human_label +
                  "；实际媒体验收：" + media_label]
    for seg in doc["segments"]:
        lines += [f"第{seg['episode']:02d}集｜{seg['id']}｜{seg['duration']}秒｜场次{seg['scene_id']}",
                  "原片时码：" + (seg.get("source_timecode") or "无（未提供有依据的原片时码）"), "①基础设定"]
        for ref in seg["asset_refs"]:
            asset = entities[ref["id"]]
            variant = next((x['description'] for x in asset.get('variants', []) if x['id'] == ref.get('variant_id')), "")
            description = asset['description'].rstrip("。； ")
            variant = variant.rstrip("。； ")
            lines.append(f"{asset['name']}：{description}" + (f"；本造型：{variant}" if variant else "") + f"；当前状态：{ref['state']}")
        narrator_ids = list(dict.fromkeys(next(v.get("narrator_id") for v in doc["voices"] if v["id"] == clip["voice_id"])
                                         for clip in seg["audio"] if clip["channel"] in ("narration", "inner")))
        for nid in narrator_ids:
            if nid in narrators:
                n = narrators[nid]
                person=entities.get(n.get("character_id"),{}).get("name","外部讲述者／关联身份待核")
                lines.append("叙述身份：" + n["type"] + "；关联人物：" + person + "；事件时年龄阶段：" + (n.get("event_age_stage") or "待核") +
                             "；讲述时年龄阶段：" + (n.get("speaking_age_stage") or "待核") + "；时间视角：" + (n.get("time_view") or "待核") +
                             "；知情边界：" + (n.get("knowledge_boundary") or "待核") + "；场内可听者：" + (", ".join(n.get("audible_to", [])) or "无"))
        lines += ["场景与空间：" + seg["setting"], "声音：" + seg["sound"], "②氛围与画质",
                  "9:16竖屏；2160×3840输出目标；" + seg["atmosphere"], "③分镜内容"]
        for shot in seg["shots"]:
            continuity = (f"；连续长镜{shot['continuous_take_id']}" if shot.get("continuous_take_id") else "")
            if shot.get("continues_shot_id"):
                continuity += f"；接续{shot['continues_shot_id']}，不是新切镜"
            lines.append(f"{shot['start']}—{shot['end']}秒｜{shot['id']}｜{shot['framing']}｜机位：{shot['camera']}｜构图：{shot['composition']}｜运镜：{shot['movement']}{continuity}。动作：{shot['action']}")
        # Audio is a single segment-level timeline, not repeated in every covered shot.
        for clip in seg["audio"]:
            label = ("旁白" if clip["channel"] == "narration" else "人物当下内心（场内不可听）" if clip["channel"] == "inner"
                     else entities[clip["speaker_id"]]["name"] + ("（画外对白）" if clip["channel"] == "offscreen" else ""))
            lines.append(f"声音 {clip['start']}—{clip['end']}秒｜{label}：{clip['text']}")
        lines.append("结束状态：" + seg["end_state"])
    lines += ["继承卡（不作为第二遍配音）"]
    for entity in doc["entities"]:
        lines.append(f"{entity.get('original_name', '原名未设')} → {entity['name']}（{entity['id']}，v{entity['version']}）")
        if entity.get("relationship"):
            lines.append("关系：" + entity["relationship"])
    if doc["segments"]:
        lines.append("最新结尾：" + doc["segments"][-1]["end_state"])
    lines.append("待核问题：" + ("见同目录 validation.json；本版仅供审稿。" if review_draft else "无未关闭的已记录文字问题；英语为单模型审读，非母语盲评。"))
    if doc["schema_version"] == 2:
        lines += ["完成范围：" + p["scope_summary"],
                  "未实测：配音时长、口音/重音/声线、字幕、口型和画面连续性；DOCX只核正文，页面视觉QA见导出状态。",
                  "正式发布常规职责建议：由具有目标市场英语影视经验的真实审者终读实际发布全范围；未经授权不得外发。"]
    return lines


def _create_docx(lines, path):
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = Inches(.8)
    section.left_margin = section.right_margin = Inches(.85)
    normal = document.styles["Normal"]
    normal.font.name, normal.font.size = "Arial", Pt(11)
    normal.font.color.rgb = RGBColor(0, 0, 0)
    normal.paragraph_format.space_after = Pt(6)
    fonts = normal.element.get_or_add_rPr()
    east = OxmlElement("w:rFonts")
    east.set(qn("w:eastAsia"), "Microsoft YaHei")
    fonts.append(east)
    for i, line in enumerate(lines):
        para = document.add_paragraph(line)
        if i == 0:
            para.runs[0].bold = True
            para.runs[0].font.size = Pt(18)
        elif line.startswith("第") and "｜" in line:
            para.runs[0].bold = True
            para.paragraph_format.keep_with_next = True
        elif line in ("①基础设定", "②氛围与画质", "③分镜内容", "继承卡（不作为第二遍配音）"):
            para.runs[0].bold = True
            para.paragraph_format.keep_with_next = True
    document.save(path)
    actual = [p.text for p in Document(path).paragraphs]
    if actual != lines:
        raise ContractError("DOCX read-back differs from canonical text")


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_package(out, work_id=None, content_fingerprint=None, revision=None):
    out = Path(out)
    package = load_json(out / "package.json")
    if package.get("status") != "completed" or (work_id is not None and package.get("work_id") != work_id) or (
            content_fingerprint is not None and package.get("content_hash") != content_fingerprint) or (
            revision is not None and package.get("revision") != revision):
        raise ContractError("Package identity/version differs; use a new output directory")
    if not isinstance(package.get("artifacts"), dict) or not package["artifacts"]:
        raise ContractError("Package artifact manifest is missing")
    for name, expected in package["artifacts"].items():
        path = (out / name).resolve()
        if path.parent != out.resolve() or not path.is_file() or _sha(path) != expected:
            raise ContractError("Package artifact missing/changed/unsafe: " + name)
    return package


def export(doc, out, want_docx=False, allow_review_draft=False, docx_writer=None, resume=False):
    report = validate(doc)
    if report["errors"]:
        raise ContractError("Structural validation failed; run check_deliverables.py for details")
    if report["review_required"] and not allow_review_draft:
        raise ContractError("Semantic/reading review pending; resolve or explicitly export review draft")
    out = Path(out)
    fingerprint = doc.get("lineage", {}).get("content_hash") or digest(doc)
    if out.exists():
        if not resume:
            raise ContractError(f"Refusing existing output directory: {out}")
        if (out / "package.json").exists():
            verify_package(out, doc["project"]["id"], fingerprint, doc["project"]["revision"])
            status = load_json(out / "export-status.json")
            if want_docx and status["docx"] == "not_requested":
                raise ContractError("Completed TXT-only package is preserved; use a new directory for requested DOCX")
            return status
        old = load_json(out / "export-status.json")
        if old.get("package_status") not in ("failed", "building", "completed") or old.get("work_id") != doc["project"]["id"] or old.get("content_hash") != fingerprint:
            raise ContractError("Resume requires a failed package of this work and exact content; inspect interruption first")
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = out.with_name("." + out.name + ".partial-" + uuid.uuid4().hex)
    stage.mkdir()
    status = {"txt": "created_and_read_back", "docx": "not_requested",
              "docx_visual_qa": "not_performed_by_exporter", "validation": report["overall_status"],
              "work_id": doc["project"]["id"], "revision": doc["project"]["revision"],
              "content_hash": fingerprint, "package_status": "building"}
    try:
        lines = canonical_lines(doc, bool(report["review_required"]))
        txt = stage / "完整视频提示词.txt"
        with txt.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write("\n".join(lines) + "\n")
        if txt.read_text(encoding="utf-8").splitlines() != lines:
            raise ContractError("TXT read-back differs")
        if want_docx:
            try:
                (docx_writer or _create_docx)(lines, stage / "完整视频提示词.docx")
                from source_io import extract_source
                actual = extract_source(stage / "完整视频提示词.docx")
                if [b["text"] for b in actual["blocks"]] != lines or actual["extraction_status"] != "complete":
                    raise ContractError("Independent DOCX read-back differs or contains unsupported content")
                status["docx"] = "created_and_read_back"
            except ImportError:
                if (stage / "完整视频提示词.docx").exists():
                    status["docx"] = "failed"
                    raise ContractError("Dependency failure left a partial DOCX; package is incomplete")
                status["docx"] = "unavailable_dependency_txt_delivered"
            except Exception as exc:
                status["docx"] = "failed"
                status["docx_error"] = str(exc)
                raise ContractError("DOCX export failed; partial TXT retained, see export-status.json") from exc
        status["package_status"] = "completed"
        save_new(stage / "validation.json", report)
        save_new(stage / "export-status.json", status)
        save_new(stage / "review-summary.json", {"work_id":doc["project"]["id"], "revision":doc["project"]["revision"],
            "content_hash":fingerprint, "scope":doc["project"]["scope_summary"], "coverage_records":len(doc["coverage"]),
            "reviews":[{k:v for k,v in r.items() if k != "snapshots"} for r in doc["reviews"]],
            "issues":doc["issues"], "acceptance":report.get("acceptance", {"target_language":"not_performed","media":"not_performed"})})
        for name in ("validation.json", "export-status.json", "review-summary.json"):
            load_json(stage / name)
        package = {"status":"completed", "work_id":doc["project"]["id"], "revision":doc["project"]["revision"],
                   "schema_version":doc["schema_version"], "content_hash":fingerprint,
                   "artifacts":{p.name:_sha(p) for p in sorted(stage.iterdir()) if p.is_file()}}
        if out.exists():
            out.rename(out.with_name("." + out.name + ".failed-" + uuid.uuid4().hex))
        stage.rename(out)
        save_new(out / ".package.pending.json", package)
        (out / ".package.pending.json").rename(out / "package.json")
        verify_package(out, doc["project"]["id"], fingerprint, doc["project"]["revision"])
        return status
    except Exception as exc:
        status["package_status"] = "failed"
        status["error"] = str(exc)
        target = stage if stage.exists() else out
        if (target / "package.json").exists():
            (target / "package.json").rename(target / (".package.failed-" + uuid.uuid4().hex + ".json"))
        # Only this attempt's diagnostic files are written; no recursive delete.
        (target / "export-status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        if not (target / "validation.json").exists():
            save_new(target / "validation.json", report)
        if stage.exists() and not out.exists():
            stage.rename(out)
        raise ContractError("Incomplete export preserved at " + str(target if target.exists() else out) + ": " + str(exc)) from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    parser.add_argument("--out", required=True)
    parser.add_argument("--docx", action="store_true")
    parser.add_argument("--allow-review-draft", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Verify/reuse a completed identical package, or preserve and retry an identified failed package")
    args = parser.parse_args()
    try:
        status = export(load_json(args.project), args.out, args.docx, args.allow_review_draft, resume=args.resume)
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 3 if status["validation"] == "review_draft" or status["docx"].startswith("unavailable") else 0
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
