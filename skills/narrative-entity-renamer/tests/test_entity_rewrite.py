from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "entity_rewrite.py"
SPEC = importlib.util.spec_from_file_location("entity_rewrite_under_test", SCRIPT_PATH)
assert SPEC and SPEC.loader
entity_rewrite = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = entity_rewrite
SPEC.loader.exec_module(entity_rewrite)


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def run_main(arguments: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = entity_rewrite.main(arguments)
    return code, stdout.getvalue(), stderr.getvalue()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def base_mapping(source: str = "临江公寓", destination: str = "锦溪公寓") -> dict:
    return {
        "format_version": 1,
        "replacements": [
            {
                "from": source,
                "to": destination,
                "kind": "named_location",
                "preserve_suffix": "公寓",
                "expected_matches": 1,
            }
        ],
    }


def document_xml(paragraphs: list[str]) -> bytes:
    body = "".join(f"<w:p>{paragraph}</w:p>" for paragraph in paragraphs)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_NS}"><w:body>{body}</w:body></w:document>'
    ).encode("utf-8")


def make_docx(
    path: Path,
    paragraphs: list[str],
    *,
    document_relationships: str = "",
    extra_members: dict[str, bytes] | None = None,
) -> None:
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    ).encode("utf-8")
    root_relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{REL_NS}">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    ).encode("utf-8")
    doc_relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{REL_NS}">{document_relationships}</Relationships>'
    ).encode("utf-8")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types)
        package.writestr("_rels/.rels", root_relationships)
        package.writestr("word/document.xml", document_xml(paragraphs))
        package.writestr("word/_rels/document.xml.rels", doc_relationships)
        for name, payload in (extra_members or {}).items():
            package.writestr(name, payload)


class EntityRewriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_context = tempfile.TemporaryDirectory(prefix="entity-rewrite-test-")
        self.root = Path(self.temp_context.name)

    def tearDown(self) -> None:
        self.temp_context.cleanup()

    def test_contextual_longest_rule_and_generic_place_preservation(self) -> None:
        source = self.root / "source.md"
        output = self.root / "output.md"
        mapping = self.root / "mapping.json"
        report = self.root / "report.json"
        source.write_text(
            "角色B完整姓名：陈秀兰\n"
            "陈秀兰说：陈姨，去临江公寓。\n"
            "公寓外景；去公寓；其他公寓住户。\n",
            encoding="utf-8",
        )
        write_json(
            mapping,
            {
                "format_version": 1,
                "replacements": [
                    {
                        "from": "角色B完整姓名：陈秀兰",
                        "to": "角色B完整姓名：赵雅琴",
                        "kind": "person_full_name",
                        "expected_matches": 1,
                    },
                    {
                        "from": "临江公寓",
                        "to": "锦溪公寓",
                        "kind": "named_location",
                        "preserve_suffix": "公寓",
                        "expected_matches": 1,
                    },
                    {
                        "from": "陈秀兰",
                        "to": "陈姐",
                        "kind": "person_title",
                        "expected_matches": 1,
                    },
                    {
                        "from": "陈姨",
                        "to": "陈姐",
                        "kind": "person_title",
                        "expected_matches": 1,
                    },
                ],
                "protected_terms": ["公寓", "角色B"],
            },
        )
        code, _, _ = run_main(
            [str(source), "--map", str(mapping), "--output", str(output), "--report", str(report)]
        )
        self.assertEqual(code, 0)
        result = output.read_text(encoding="utf-8")
        self.assertIn("角色B完整姓名：赵雅琴", result)
        self.assertIn("陈姐说：陈姐，去锦溪公寓", result)
        self.assertIn("公寓外景；去公寓；其他公寓住户", result)
        self.assertNotIn("陈秀兰", result)
        self.assertNotIn("陈姨", result)
        self.assertNotIn("临江公寓", result)
        audit = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(audit["status"], "PASS")
        self.assertEqual(audit["total_replacements"], 4)

    def test_path_collisions_cannot_overwrite_inputs_or_output(self) -> None:
        source = self.root / "source.md"
        mapping = self.root / "mapping.json"
        source.write_text("临江公寓", encoding="utf-8")
        write_json(mapping, base_mapping())
        before_hash = hashlib.sha256(source.read_bytes()).hexdigest()

        code, _, _ = run_main(
            [str(source), "--map", str(mapping), "--dry-run", "--report", str(source), "--force"]
        )
        self.assertEqual(code, 2)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before_hash)

        collision = self.root / "same-output-report.md"
        code, _, _ = run_main(
            [
                str(source),
                "--map",
                str(mapping),
                "--output",
                str(collision),
                "--report",
                str(collision),
                "--force",
            ]
        )
        self.assertEqual(code, 2)
        self.assertFalse(collision.exists())

        code, _, _ = run_main(
            [str(source), "--map", str(mapping), "--dry-run", "--report", str(mapping), "--force"]
        )
        self.assertEqual(code, 2)
        json.loads(mapping.read_text(encoding="utf-8"))

    def test_noop_fails_by_default_and_requires_explicit_opt_in(self) -> None:
        source = self.root / "source.md"
        mapping = self.root / "mapping.json"
        source.write_text("无关文本", encoding="utf-8")
        data = {
            "format_version": 1,
            "replacements": [
                {"from": "不存在的人物", "to": "新人物", "kind": "person_title"}
            ],
        }
        write_json(mapping, data)
        code, stdout, _ = run_main([str(source), "--map", str(mapping), "--dry-run"])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(stdout)["status"], "FAIL")

        data["allow_noop"] = True
        data["replacements"][0]["expected_matches"] = 0
        write_json(mapping, data)
        code, stdout, _ = run_main([str(source), "--map", str(mapping), "--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "PASS")

    def test_schema_rejects_ambiguous_or_malformed_rules(self) -> None:
        invalid_cases = {
            "boolean_version": {
                "format_version": True,
                "replacements": [{"from": "陈秀兰", "to": "陈姐"}],
            },
            "string_boolean": {
                "format_version": 1,
                "allow_noop": "false",
                "replacements": [{"from": "陈秀兰", "to": "陈姐"}],
            },
            "duplicate_source": {
                "format_version": 1,
                "replacements": [
                    {"from": "陈秀兰", "to": "陈姐"},
                    {"from": "陈秀兰", "to": "陈姐", "expected_matches": 99},
                ],
            },
            "blank_source": {
                "format_version": 1,
                "allow_short_sources": True,
                "replacements": [{"from": "   ", "to": "陈姐"}],
            },
            "control_source": {
                "format_version": 1,
                "replacements": [{"from": "陈\n秀兰", "to": "陈姐"}],
            },
            "generic_location": {
                "format_version": 1,
                "replacements": [{"from": "公寓", "to": "住宅"}],
            },
            "weak_location_suffix": {
                "format_version": 1,
                "replacements": [
                    {
                        "from": "仁和中学",
                        "to": "仁和大学",
                        "kind": "named_location",
                        "preserve_suffix": "学",
                    }
                ],
            },
        }
        for name, data in invalid_cases.items():
            with self.subTest(name=name):
                mapping = self.root / f"{name}.json"
                write_json(mapping, data)
                with self.assertRaises(entity_rewrite.MappingError):
                    entity_rewrite.load_mapping(mapping)

    def test_visible_reference_markers_are_structural_barriers(self) -> None:
        rule = entity_rewrite.Rule("临江公寓", "锦溪公寓", "named_location", "公寓", 0)
        pattern, lookup = entity_rewrite.compile_rules([rule])
        markers = ["footnoteReference", "endnoteReference", "commentReference"]
        for marker in markers:
            with self.subTest(marker=marker):
                xml = (
                    f'<w:p xmlns:w="{W_NS}">'
                    "<w:r><w:t>临江</w:t></w:r>"
                    f'<w:r><w:{marker} w:id="2"/></w:r>'
                    "<w:r><w:t>公寓</w:t></w:r>"
                    "</w:p>"
                ).encode("utf-8")
                rewritten, counts = entity_rewrite.rewrite_xml_bytes(xml, pattern, lookup)
                self.assertEqual(counts["临江公寓"], 0)
                self.assertEqual(rewritten, xml)
                self.assertEqual(entity_rewrite.extract_xml_text(xml), "临江\n公寓")

    def test_container_entry_and_exit_are_structural_barriers(self) -> None:
        rule = entity_rewrite.Rule("临江公寓", "锦溪公寓", "named_location", "公寓", 0)
        pattern, lookup = entity_rewrite.compile_rules([rule])
        cases = {
            "outside_to_field": (
                "<w:r><w:t>临江</w:t></w:r>"
                '<w:fldSimple w:instr="PAGE"><w:r><w:t>公寓</w:t></w:r></w:fldSimple>'
            ),
            "field_to_outside": (
                '<w:fldSimple w:instr="PAGE"><w:r><w:t>临江</w:t></w:r></w:fldSimple>'
                "<w:r><w:t>公寓</w:t></w:r>"
            ),
            "outside_to_drawing": (
                "<w:r><w:t>临江</w:t></w:r>"
                "<w:r><w:drawing><a:p><a:r><a:t>公寓</a:t></a:r></a:p></w:drawing></w:r>"
            ),
            "drawing_to_outside": (
                "<w:r><w:drawing><a:p><a:r><a:t>临江</a:t></a:r></a:p></w:drawing></w:r>"
                "<w:r><w:t>公寓</w:t></w:r>"
            ),
        }
        for name, content in cases.items():
            with self.subTest(name=name):
                xml = (
                    f'<w:p xmlns:w="{W_NS}" '
                    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                    f"{content}</w:p>"
                ).encode("utf-8")
                rewritten, counts = entity_rewrite.rewrite_xml_bytes(xml, pattern, lookup)
                self.assertEqual(counts["临江公寓"], 0)
                self.assertEqual(rewritten, xml)
                self.assertEqual(entity_rewrite.extract_xml_text(xml), "临江\n公寓")

    def test_cross_run_replacement_preserves_run_structure_and_style(self) -> None:
        rule = entity_rewrite.Rule("临江公寓", "锦溪公寓", "named_location", "公寓", 1)
        pattern, lookup = entity_rewrite.compile_rules([rule])
        xml = (
            f'<w:p xmlns:w="{W_NS}">'
            "<w:r><w:rPr><w:b/></w:rPr><w:t>临</w:t></w:r>"
            "<w:r><w:rPr><w:i/></w:rPr><w:t>江公寓</w:t></w:r>"
            "</w:p>"
        ).encode("utf-8")
        rewritten, counts = entity_rewrite.rewrite_xml_bytes(xml, pattern, lookup)
        self.assertEqual(counts["临江公寓"], 1)
        self.assertEqual(entity_rewrite.extract_xml_text(rewritten), "锦溪公寓")
        self.assertIn(b"<w:b/>", rewritten)
        self.assertIn(b"<w:i/>", rewritten)
        self.assertIn("<w:t>锦</w:t>".encode(), rewritten)
        self.assertIn("<w:t>溪公寓</w:t>".encode(), rewritten)
        for split in range(1, len("临江公寓")):
            parts, part_counts = entity_rewrite.rewrite_parts(
                ["临江公寓"[:split], "临江公寓"[split:]], pattern, lookup
            )
            self.assertEqual("".join(parts), "锦溪公寓")
            self.assertEqual(part_counts["临江公寓"], 1)

    def test_docx_audit_covers_attributes_url_decoding_and_member_names(self) -> None:
        source = self.root / "source.docx"
        output = self.root / "output.docx"
        mapping = self.root / "mapping.json"
        report = self.root / "report.json"
        relationship = (
            '<Relationship Id="rId2" Type="urn:test" '
            'Target="media/%E4%B8%B4%E6%B1%9F%E5%85%AC%E5%AF%93.png"/>'
        )
        make_docx(
            source,
            ["<w:r><w:t>临江公寓</w:t></w:r>"],
            document_relationships=relationship,
            extra_members={"word/media/临江公寓.png": b"not-an-image"},
        )
        write_json(mapping, base_mapping())
        code, _, _ = run_main(
            [
                str(source),
                "--map",
                str(mapping),
                "--output",
                str(output),
                "--report",
                str(report),
                "--force",
            ]
        )
        self.assertEqual(code, 3)
        self.assertFalse(output.exists())
        audit = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(audit["forbidden_after_counts"]["临江公寓"], 2)
        locations = audit["forbidden_after_locations"]["临江公寓"]
        scopes = {item["scope"] for item in locations}
        self.assertIn("word/_rels/document.xml.rels", scopes)
        self.assertIn("[ZIP member] word/media/临江公寓.png", scopes)

    def test_valid_docx_output_reopens_as_xml_and_zip(self) -> None:
        source = self.root / "source.docx"
        output = self.root / "output.docx"
        mapping = self.root / "mapping.json"
        make_docx(
            source,
            [
                "<w:r><w:rPr><w:b/></w:rPr><w:t>临</w:t></w:r>"
                "<w:r><w:rPr><w:i/></w:rPr><w:t>江公寓</w:t></w:r>",
                "<w:r><w:t>公寓外景</w:t></w:r>",
            ],
        )
        data = base_mapping()
        data["protected_terms"] = ["公寓"]
        write_json(mapping, data)
        code, _, _ = run_main(
            [str(source), "--map", str(mapping), "--output", str(output)]
        )
        self.assertEqual(code, 0)
        entity_rewrite.validate_docx_package(output)
        with zipfile.ZipFile(output) as package:
            self.assertIsNone(package.testzip())
            rewritten = package.read("word/document.xml")
        rewritten_text = entity_rewrite.extract_xml_text(rewritten)
        self.assertIn("锦溪公寓", rewritten_text)
        self.assertIn("公寓外景", rewritten_text)

    def test_invalid_docx_or_xml_is_rejected(self) -> None:
        not_zip = self.root / "bad.docx"
        not_zip.write_bytes(b"not a zip")
        with self.assertRaises(entity_rewrite.MappingError):
            entity_rewrite.validate_docx_package(not_zip)

        malformed = self.root / "malformed.docx"
        with zipfile.ZipFile(malformed, "w") as package:
            package.writestr("word/document.xml", b"<broken>")
        with self.assertRaises(entity_rewrite.MappingError):
            entity_rewrite.validate_docx_package(malformed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
