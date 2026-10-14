import copy
from contextlib import contextmanager
import importlib.util
import json
import subprocess
import sys
import uuid
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = ROOT / "qa" / "test-fixtures"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)


@contextmanager
def test_directory():
    # Retain reproducible test artifacts. Windows sandbox rejects mkdtemp's
    # owner-only ACL; ordinary project directories inherit the permitted ACL.
    folder = TEMP_ROOT / ("run-" + uuid.uuid4().hex)
    folder.mkdir()
    yield str(folder)
SCRIPTS = ROOT / "skills/short-drama-adapt-localize/scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("fixture_builder", ROOT / "examples/three-scenes/build_example.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
from drama_core import ContractError, digest, invalidate_changes, load_json, review_record, save_new, validate
from export_deliverables import canonical_lines, export
from init_project import initialize
from source_io import extract_source


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.doc = fixture.build()

    def codes(self):
        return {x["code"] for x in validate(self.doc)["errors"]}

    def has(self, code):
        self.assertIn(code, self.codes())

    def test_complete_fixture(self):
        result = validate(self.doc)
        self.assertEqual(result["overall_status"], "ready_for_text_delivery", result)
        self.assertEqual(result["audio_status"], "not_measured")

    def test_cross_segment_voice_and_long_take(self):
        self.assertEqual(self.doc["segments"][1]["shots"][0]["continues_shot_id"], "SH2")
        self.assertEqual(self.doc["segments"][0]["audio"][1]["char_end"], self.doc["segments"][1]["audio"][0]["char_start"])
        self.assertEqual(self.codes(), set())

    def test_cross_shot_offscreen_remains_dialogue(self):
        clip = self.doc["segments"][1]["audio"][1]
        self.assertEqual(clip["channel"], "offscreen")
        self.assertEqual(self.codes(), set())

    def test_existing_narration_preserved(self):
        self.doc["segments"][0]["audio"].pop(0)
        self.has("VOICE_INCOMPLETE")

    def test_no_narration_source_cannot_add(self):
        self.doc["sources"][0]["blocks"][2]["kind"] = "action"
        self.has("SOURCE_CHANNEL")

    def test_valid_without_narration(self):
        self.doc["sources"][0]["blocks"][2]["kind"] = "action"
        self.doc["voices"].pop(0)
        self.doc["segments"][0]["audio"].pop(0)
        self.doc["coverage"][2]["target_ids"] = ["S1"]
        self.doc["reviews"] = []
        self.assertEqual(self.codes(), set())

    def test_wrong_channel(self):
        self.doc["segments"][1]["audio"][1]["channel"] = "narration"
        self.has("AUDIO_ATTRIBUTION")

    def test_wrong_speaker(self):
        self.doc["segments"][0]["audio"][1]["speaker_id"] = "C2"
        self.has("AUDIO_ATTRIBUTION")

    def test_missing_word(self):
        self.doc["segments"][2]["audio"][0]["text"] = "Who was the person here?"
        self.has("VOICE_TEXT")

    def test_duplicate_voice(self):
        duplicate = copy.deepcopy(self.doc["segments"][2]["audio"][0])
        duplicate["id"] = "REPLAY"
        self.doc["segments"][2]["audio"].append(duplicate)
        self.has("VOICE_SLICE_COVERAGE")

    def test_sliced_voice_gap(self):
        self.doc["segments"][1]["audio"][0]["char_start"] += 1
        self.has("VOICE_SLICE_COVERAGE")

    def test_cross_segment_time_gap(self):
        self.doc["segments"][1]["audio"][0]["start"] = .2
        self.has("VOICE_CONTINUITY")

    def test_explicit_locked_pause(self):
        self.doc["segments"][1]["audio"][0]["start"] = .2
        self.doc["voices"][1]["pauses"] = [{"after_char": self.doc["segments"][1]["audio"][0]["char_start"], "seconds": .2}]
        self.assertEqual(self.codes(), set())

    def test_nondeclared_audio_overlap(self):
        self.doc["segments"][2]["audio"][1]["start"] = 2
        self.has("AUDIO_OVERLAP")

    def test_declared_overlap(self):
        self.doc["segments"][2]["audio"][1]["start"] = 2
        self.doc["voices"][3]["overlap_group"] = "intentional-interruption"
        self.doc["voices"][4]["overlap_group"] = "intentional-interruption"
        self.assertEqual(self.codes(), set())

    def test_exact_fifteen(self):
        self.doc["segments"][3]["duration"] = 15
        self.doc["segments"][3]["shots"][-1]["end"] = 15
        for seg in self.doc["segments"][4:]:
            seg["start"] += 2
        self.doc["project"]["episode_duration"]["1"]["seconds"] = 64
        self.assertEqual(self.codes(), set())

    def test_over_fifteen(self):
        self.doc["segments"][3]["duration"] = 15.01
        self.has("SEGMENT_DURATION")

    def test_hard_total(self):
        self.doc["project"]["episode_duration"]["1"] = {"kind":"hard","seconds":60,"basis":"user request"}
        self.has("EPISODE_DURATION")

    def test_reference_total_needs_review(self):
        self.doc["project"]["episode_duration"]["1"] = {"kind":"reference","seconds":60,"basis":"source estimate"}
        result = validate(self.doc)
        self.assertFalse(result["errors"])
        self.assertTrue(any(x["code"] == "EPISODE_DURATION" for x in result["review_required"]))

    def test_shot_gap(self):
        self.doc["segments"][1]["shots"][1]["start"] = 3
        self.has("SHOT_INTERVAL")

    def test_missing_shots(self):
        self.doc["segments"][0]["shots"] = []
        self.has("SHOTS_EMPTY")

    def test_missing_scene_output(self):
        self.doc["segments"] = self.doc["segments"][:4]
        self.has("OUTPUT_SCENE_COVERAGE")

    def test_missing_episode(self):
        self.doc["project"]["episodes"].append(2)
        self.has("EPISODE_COVERAGE")

    def test_unknown_reference(self):
        self.doc["segments"][0]["asset_refs"][0]["id"] = "UNKNOWN"
        self.has("MALFORMED")

    def test_duplicate_global_id(self):
        self.doc["voices"][0]["id"] = "C1"
        self.has("MALFORMED")

    def test_duplicate_nested_id(self):
        self.doc["segments"][0]["shots"][0]["id"] = "C1"
        self.has("NESTED_ID")

    def test_missing_source_mapping(self):
        self.doc["coverage"].pop()
        self.has("SOURCE_COVERAGE")

    def test_source_one_voice_can_split_into_two_locked_voices(self):
        # Adaptation is allowed to change utterance count. Both target voices
        # retain source provenance; production is checked against the new lock.
        first = self.doc["voices"][4]
        second = copy.deepcopy(first)
        first["text"] = "It might've been Owen. "
        second.update(id="V5B", order=5.5, text="I still need to check.")
        self.doc["voices"].insert(5, second)
        old = self.doc["segments"][2]["audio"][1]
        old.update(end=5, text=first["text"], char_end=len(first["text"]))
        self.doc["segments"][2]["audio"].append({**old, "id":"G3-V5B", "voice_id":"V5B", "start":5, "end":8,
                                                  "text":second["text"], "char_end":len(second["text"])})
        self.doc["coverage"][8]["target_ids"].append("V5B")
        self.assertEqual(self.codes(), set())

    def test_independent_scene_dependency_not_invalidated(self):
        self.doc["scenes"].append({"id":"S-INDEPENDENT", "entity_ids":["C3"]})
        before = copy.deepcopy(self.doc)
        self.doc["entities"][0]["relationship"] = "new relationship requiring local repair"
        report = invalidate_changes(before, self.doc)
        self.assertIn("S1", report["affected_ids"])
        self.assertNotIn("S-INDEPENDENT", report["affected_ids"])

    def test_revise_cli_marks_changed_reviews(self):
        with test_directory() as tmp:
            before, proposed, result = [Path(tmp) / name for name in ("before.json", "proposed.json", "result.json")]
            save_new(before, self.doc)
            self.doc["entities"][0]["relationship"] = "new relationship needing review"
            save_new(proposed, self.doc)
            command = [sys.executable, str(SCRIPTS / "revise_project.py"), str(before), str(proposed), "--out", str(result)]
            run = subprocess.run(command, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertTrue(all(x["status"] == "stale" for x in load_json(result)["reviews"]))
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)

    def test_unread_source_not_passed(self):
        self.doc["sources"][0]["blocks"][-1]["read"] = False
        self.assertEqual(validate(self.doc)["overall_status"], "review_draft")

    def test_partial_extraction_not_passed(self):
        self.doc["sources"][0]["limitations"] = ["Unread textbox"]
        self.assertEqual(validate(self.doc)["overall_status"], "review_draft")

    def test_stale_asset_version(self):
        self.doc["entities"][0]["version"] = 2
        self.has("ASSET_STALE")

    def test_stale_voice_version(self):
        self.doc["voices"][0]["version"] += 1
        self.has("AUDIO_ATTRIBUTION")

    def test_unknown_variant(self):
        self.doc["segments"][0]["asset_refs"][0]["variant_id"] = "missing"
        self.has("VARIANT_UNKNOWN")

    def test_dynamic_state_not_identity_change(self):
        self.assertEqual(self.doc["segments"][0]["asset_refs"][3]["id"], self.doc["segments"][-1]["asset_refs"][3]["id"])
        self.assertNotEqual(self.doc["segments"][0]["asset_refs"][3]["state"], self.doc["segments"][-1]["asset_refs"][3]["state"])
        self.assertEqual(self.codes(), set())

    def test_state_break(self):
        self.doc["scenes"][1]["entry_state"]["key"] = "Nora口袋"
        self.has("STATE_BREAK")

    def test_dependent_review_invalidation(self):
        before = copy.deepcopy(self.doc)
        self.doc["entities"][0]["relationship"] = "改成合作关系，待联动"
        report = invalidate_changes(before, self.doc)
        self.assertIn("C1", report["changed_ids"])
        self.assertIn("G1", report["affected_ids"])
        self.assertEqual({x["status"] for x in self.doc["reviews"]}, {"stale"})

    def test_unrelated_source_asset_not_rewritten(self):
        # C3 is only mentioned, not a visual asset; change its unseen costume, not relationship/name.
        before = copy.deepcopy(self.doc)
        isolated = {"id":"UNUSED","kind":"prop","name":"test","original_name":"test","description":"unused","version":1}
        before["entities"].append(copy.deepcopy(isolated))
        self.doc["entities"].append(isolated)
        self.doc["entities"][-1]["description"] = "different unused prop"
        report = invalidate_changes(before, self.doc)
        self.assertEqual(report["affected_ids"], ["UNUSED"])
        self.assertEqual(before["scenes"], self.doc["scenes"])

    def test_changed_text_invalidates_review_without_version_bump(self):
        self.doc["voices"][3]["meaning"] = "changed semantics"
        self.assertTrue(any(x["code"] == "REVIEW_STALE" for x in validate(self.doc)["review_required"]))

    def test_semantic_error_cannot_be_solved_by_byte_checker(self):
        self.doc["voices"][6]["text"] = "I'll have it fixed by tomorrow."
        clip = self.doc["segments"][4]["audio"][0]
        clip["text"] = self.doc["voices"][6]["text"]
        clip["char_end"] = len(clip["text"])
        result = validate(self.doc)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["overall_status"], "review_draft")

    def test_open_issue(self):
        self.doc["issues"][0]["status"] = "open"
        self.assertEqual(validate(self.doc)["overall_status"], "review_draft")

    def test_audio_measurement_cannot_be_faked(self):
        self.doc["project"]["audio_status"] = "passed"
        self.has("UNMEASURED")

    def test_long_take_requires_valid_predecessor(self):
        self.doc["segments"][1]["shots"][0]["continues_shot_id"] = "SH1"
        self.has("CONTINUATION")

    def test_event_repeat(self):
        self.doc["segments"][1]["shots"][1]["event_refs"][0]["phases"].append("持钥匙就位")
        self.has("EVENT_COVERAGE")

    def test_invalid_number(self):
        self.doc["segments"][0]["duration"] = "NaN"
        self.has("MALFORMED")

    def test_malformed_root(self):
        for bad in (None, [], {}, {"schema_version":1,"project":[]}):
            self.assertEqual(validate(bad)["overall_status"], "failed")

    def test_duplicate_json_key_rejected(self):
        with test_directory() as tmp:
            path = Path(tmp) / "duplicate.json"
            path.write_text('{"x":1,"x":2}', encoding="utf-8")
            with self.assertRaises(ContractError):
                load_json(path)

    def test_checkpoint_roundtrip(self):
        with test_directory() as tmp:
            path = Path(tmp) / "checkpoint.json"
            save_new(path, self.doc)
            restored = load_json(path)
            self.assertEqual(digest(restored), digest(self.doc))
            self.assertEqual(validate(restored)["overall_status"], "ready_for_text_delivery")

    def test_source_import_unread_and_no_overwrite(self):
        with test_directory() as tmp:
            target = Path(tmp) / "new"
            initialize([ROOT / "examples/three-scenes/source.txt"], target, "test", "en-GB", "England", "1998", [1])
            imported = load_json(target / "project.json")
            self.assertEqual(len(imported["sources"][0]["blocks"]), 15)
            self.assertFalse(imported["sources"][0]["blocks"][0]["read"])
            with self.assertRaises(ContractError):
                initialize([ROOT / "examples/three-scenes/source.txt"], target, "test", "en-GB", "England", "1998", [1])

    def test_docx_import_table_order_and_limitations(self):
        xml = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>first</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>table</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p><w:r><w:t>last</w:t></w:r></w:p><w:p><w:r><w:drawing/></w:r></w:p></w:body></w:document>'''
        with test_directory() as tmp:
            path = Path(tmp) / "sample.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", xml)
            source = extract_source(path)
            self.assertEqual([x["text"] for x in source["blocks"]], ["first","table","last"])
            self.assertEqual(source["extraction_status"], "partial")

    def test_unsupported_video(self):
        with test_directory() as tmp:
            path = Path(tmp) / "video.mp4"
            path.write_bytes(b"not a video reader")
            with self.assertRaises(ContractError):
                extract_source(path)

    def test_export_txt_and_existing_directory(self):
        with test_directory() as tmp:
            out = Path(tmp) / "export"
            status = export(self.doc, out)
            self.assertEqual(status["txt"], "created_and_read_back")
            self.assertEqual((out / "完整视频提示词.txt").read_text(encoding="utf-8").splitlines(), canonical_lines(self.doc))
            with self.assertRaises(ContractError):
                export(self.doc, out)

    def test_docx_export_real_readback(self):
        try:
            from docx import Document
        except ImportError:
            self.skipTest("python-docx unavailable")
        with test_directory() as tmp:
            out = Path(tmp) / "export"
            status = export(self.doc, out, want_docx=True)
            self.assertEqual(status["docx"], "created_and_read_back")
            self.assertEqual([p.text for p in Document(out / "完整视频提示词.docx").paragraphs], canonical_lines(self.doc))

    def test_missing_docx_dependency_delivers_txt(self):
        def missing(*args):
            raise ImportError("simulated missing python-docx")
        with test_directory() as tmp:
            out = Path(tmp) / "export"
            result = export(self.doc, out, True, docx_writer=missing)
            self.assertEqual(result["docx"], "unavailable_dependency_txt_delivered")
            self.assertTrue((out / "完整视频提示词.txt").exists())
            self.assertFalse((out / "完整视频提示词.docx").exists())

    def test_docx_failure_explicit(self):
        def failed(*args):
            raise OSError("simulated disk failure")
        with test_directory() as tmp:
            out = Path(tmp) / "export"
            with self.assertRaises(ContractError):
                export(self.doc, out, True, docx_writer=failed)
            self.assertEqual(load_json(out / "export-status.json")["docx"], "failed")

    def test_invalid_structure_cannot_export(self):
        self.doc["segments"][0]["audio"] = []
        with test_directory() as tmp:
            with self.assertRaises(ContractError):
                export(self.doc, Path(tmp) / "export", allow_review_draft=True)

    def test_review_draft_requires_explicit_flag(self):
        self.doc["reviews"] = []
        with test_directory() as tmp:
            out = Path(tmp) / "export"
            with self.assertRaises(ContractError):
                export(self.doc, out)
            result = export(self.doc, out, allow_review_draft=True)
            self.assertEqual(result["validation"], "review_draft")
            self.assertIn("待核审稿版", (out / "完整视频提示词.txt").read_text(encoding="utf-8"))

    def test_cli_exit_codes(self):
        with test_directory() as tmp:
            path = Path(tmp) / "project.json"
            save_new(path, self.doc)
            cmd = [sys.executable, str(SCRIPTS / "check_deliverables.py"), str(path)]
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            pending = copy.deepcopy(self.doc)
            pending["reviews"] = []
            path2 = Path(tmp) / "pending.json"
            save_new(path2, pending)
            self.assertEqual(subprocess.run(cmd[:-1] + [str(path2)], capture_output=True).returncode, 3)
            broken = copy.deepcopy(self.doc)
            broken["segments"] = []
            path3 = Path(tmp) / "broken.json"
            save_new(path3, broken)
            self.assertEqual(subprocess.run(cmd[:-1] + [str(path3)], capture_output=True).returncode, 1)


if __name__ == "__main__":
    unittest.main()
