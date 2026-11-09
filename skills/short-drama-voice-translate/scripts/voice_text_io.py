"""Locate and replace approved speech spans. No translation/model/network calls."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.parsers import expat
from xml.sax.saxutils import escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CHANNELS = {"dialogue", "offscreen", "narration", "inner", "recollection", "readout"}
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U000323af]")
STORY = re.compile(r"word/(document|header\d+|footer\d+|footnotes|endnotes|comments)\.xml\Z")
PROTECTED = {W + t for t in ("ins", "del", "moveFrom", "moveTo", "fldSimple", "fldChar", "instrText", "hyperlink")}
WARNING = {W + t for t in ("drawing", "pict", "altChunk", "object", "sym")}
MAX_SOURCE = 64_000_000
MAX_EXPANDED = 256_000_000


class VoiceError(ValueError):
    pass


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise VoiceError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(VoiceError("Invalid JSON number: " + value)))


def check_destination(path, *inputs):
    resolved = Path(path).resolve()
    package_root = Path(__file__).resolve().parent.parent
    if resolved == package_root or package_root in resolved.parents:
        raise VoiceError("Write outputs to the task workspace, not the skill installation")
    if any(resolved == Path(item).resolve() for item in inputs if item is not None):
        raise VoiceError("Output cannot be an input file")
    if resolved.exists():
        raise VoiceError("Refusing to overwrite: " + str(resolved))
    return resolved


def write_new(path, raw, *inputs):
    dest = check_destination(path, *inputs)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("xb") as stream:
        stream.write(raw)
    return dest


def tag_end(raw, start):
    quote = None
    for pos in range(start, len(raw)):
        char = raw[pos]
        if quote:
            if char == quote:
                quote = None
        elif char in (34, 39):
            quote = char
        elif char == 62:
            return pos + 1
    raise VoiceError("Unterminated XML tag")


def xml_blocks(raw, part):
    # Expat supplies original byte offsets; do not serialize the whole XML tree.
    declared = re.search(br"<\?xml[^>]*encoding\s*=\s*['\"]([^'\"]+)", raw[:256], re.I)
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or (declared and declared[1].lower() not in (b"utf-8", b"utf8")):
        raise VoiceError("Only UTF-8 DOCX XML is supported: " + part)
    parser = expat.ParserCreate(namespace_separator="}")
    blocks, paragraphs, tags, active_text, warnings = [], [], [], [], []

    def protect(reason):
        for paragraph in paragraphs:
            if reason not in paragraph["protected"]:
                paragraph["protected"].append(reason)

    def start(name, attrs):
        if name == W + "p":
            paragraph = {"id": f"{part}:P{len(blocks)+1:06d}", "part": part, "text": "",
                         "nodes": [], "protected": [t.split("}")[-1] for t in tags if t in PROTECTED]}
            paragraphs.append(paragraph)
            blocks.append(paragraph)
        if name in PROTECTED:
            protect(name.split("}")[-1])
        if name in WARNING or name.endswith("}oMath"):
            warnings.append(f"{part}: contains {name.split('}')[-1]}; embedded/non-text content not interpreted")
        if paragraphs and name == W + "t":
            paragraph = paragraphs[-1]
            begin = parser.CurrentByteIndex
            content = tag_end(raw, begin)
            node = {"start": len(paragraph["text"]), "text": "", "kind": "text",
                    "open_start": begin, "open_end": content, "content_start": content,
                    "content_end": content, "space": attrs.get("http://www.w3.org/XML/1998/namespace}space")}
            paragraph["nodes"].append(node)
            active_text.append((paragraph, node))
        elif paragraphs and name in (W + "tab", W + "br", W + "cr"):
            paragraph = paragraphs[-1]
            value = "\t" if name == W + "tab" else "\n"
            paragraph["nodes"].append({"start": len(paragraph["text"]), "text": value, "kind": "boundary"})
            paragraph["text"] += value
        tags.append(name)

    def chars(value):
        if active_text:
            paragraph, node = active_text[-1]
            node["text"] += value
            paragraph["text"] += value

    def end(name):
        if name == W + "t" and active_text:
            paragraph, node = active_text.pop()
            node["content_end"] = parser.CurrentByteIndex
            # An empty self-closing w:t never intersects a nonempty selection.
        if name == W + "p":
            paragraphs.pop()
        tags.pop()

    def reject_doctype(*args):
        raise VoiceError("DTD/entities are not supported in DOCX XML")

    parser.StartElementHandler = start
    parser.CharacterDataHandler = chars
    parser.EndElementHandler = end
    parser.StartDoctypeDeclHandler = reject_doctype
    parser.ExternalEntityRefHandler = lambda *args: 0
    try:
        parser.Parse(raw, True)
    except expat.ExpatError as exc:
        raise VoiceError(f"Invalid XML {part}: {exc}") from exc
    for block in blocks:
        if block["protected"]:
            warnings.append(f"{block['id']}: protected complex markup {','.join(block['protected'])}")
    return blocks, warnings


def load_source(path):
    path = Path(path)
    if path.stat().st_size > MAX_SOURCE:
        raise VoiceError("Source too large; split explicitly before processing")
    raw = path.read_bytes()
    result = {"path": path, "raw": raw, "source_sha256": sha(raw), "blocks": [], "warnings": []}
    suffix = path.suffix.lower()
    if suffix in (".txt", ".md"):
        text = raw.decode("utf-8-sig")
        position = 0
        for index, line in enumerate(text.splitlines(keepends=True), 1):
            body = line[:-2] if line.endswith("\r\n") else line[:-1] if line.endswith(("\n", "\r")) else line
            result["blocks"].append({"id": f"L{index:06d}", "text": body, "offset": position, "protected": []})
            position += len(line)
        result.update(format="text", text=text, bom=raw.startswith(b"\xef\xbb\xbf"))
    elif suffix == ".docx":
        result.update(format="docx", parts={}, members=[], comment=b"")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            names = [member.filename for member in members]
            if len(set(names)) != len(names):
                raise VoiceError("Duplicate DOCX ZIP members")
            if sum(member.file_size for member in members) > MAX_EXPANDED:
                raise VoiceError("Expanded DOCX too large")
            if any(name.lower().startswith("_xmlsignatures/") for name in names):
                raise VoiceError("Digitally signed DOCX: cannot preserve signature after editing")
            if "word/document.xml" not in names:
                raise VoiceError("DOCX main document is missing")
            result["members"] = [(member, archive.read(member)) for member in members]
            result["comment"] = archive.comment
            parts = [n for n in names if STORY.fullmatch(n)]
            parts.sort(key=lambda n: (n != "word/document.xml", n))
            for part in parts:
                payload = archive.read(part)
                blocks, warnings = xml_blocks(payload, part)
                result["parts"][part] = payload
                result["blocks"].extend(blocks)
                result["warnings"].extend(warnings)
            if any(name.startswith("word/embeddings/") for name in names):
                result["warnings"].append("Embedded files were not opened or translated")
    else:
        raise VoiceError("Supported inputs: UTF-8 TXT/MD or DOCX")
    return result


def inspect(source):
    return {"source": str(source["path"].resolve()), "source_sha256": source["source_sha256"],
            "format": source["format"], "warnings": source["warnings"],
            "note": "Extracted, not semantically read. Model must identify speech and check coverage.",
            "blocks": [{k: block[k] for k in ("id", "text", "protected")} for block in source["blocks"]]}


def validate_patch(source, patch):
    if not isinstance(patch, dict) or type(patch.get("version")) is not int or patch["version"] != 1:
        raise VoiceError("Expected translation patch version 1")
    fingerprint = patch.get("source_sha256")
    if not isinstance(fingerprint, str) or fingerprint.lower() != source["source_sha256"]:
        raise VoiceError("Original source fingerprint changed or wrong source")
    edits = patch.get("translations")
    if not isinstance(edits, list) or not edits:
        raise VoiceError("No translations; do not fabricate edits to already-English material")
    blocks = {block["id"]: block for block in source["blocks"]}
    grouped = {}
    for edit in edits:
        if not isinstance(edit, dict):
            raise VoiceError("Each translation must be an object")
        bid = edit.get("block_id")
        if not isinstance(bid, str) or bid not in blocks:
            raise VoiceError("Unknown source block: " + str(bid))
        block = blocks[bid]
        start, end = edit.get("start"), edit.get("end")
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(block["text"]):
            raise VoiceError("Invalid source character range: " + bid)
        if block["protected"]:
            raise VoiceError("Selected block has unsupported complex markup: " + bid)
        original, target = edit.get("source"), edit.get("target")
        if not isinstance(original, str) or block["text"][start:end] != original:
            raise VoiceError("Source span mismatch: " + bid)
        if not HAN.search(original):
            raise VoiceError("Selected source has no Chinese; existing English is protected: " + bid)
        if not isinstance(target, str) or not target.strip() or HAN.search(target):
            raise VoiceError("Target must be nonempty English without Han characters: " + bid)
        if any(c in original + target for c in "\r\n\t"):
            raise VoiceError("Do not cross a paragraph, line break or tab: " + bid)
        if any(ord(c) < 32 for c in target):
            raise VoiceError("Control character in translated speech: " + bid)
        if not isinstance(edit.get("channel"), str) or edit["channel"] not in CHANNELS:
            raise VoiceError("Unknown speech channel: " + bid)
        grouped.setdefault(bid, []).append(edit)
    for bid, items in grouped.items():
        items.sort(key=lambda edit: edit["start"])
        if any(left["end"] > right["start"] for left, right in zip(items, items[1:])):
            raise VoiceError("Overlapping/duplicate translation spans: " + bid)
    return blocks, grouped


def replace_ranges(text, replacements):
    # Original offsets, applied right-to-left; no global string replacement.
    for start, end, target in sorted(replacements, key=lambda item: item[0], reverse=True):
        text = text[:start] + target + text[end:]
    return text


def xml_replacements(block, edits, payload):
    by_node = {}
    for edit in edits:
        first, covered = True, 0
        for index, node in enumerate(block["nodes"]):
            ns, ne = node["start"], node["start"] + len(node["text"])
            start, end = max(edit["start"], ns), min(edit["end"], ne)
            if start >= end:
                continue
            if node["kind"] != "text":
                raise VoiceError("Selected speech crosses a non-text boundary: " + block["id"])
            by_node.setdefault(index, []).append((start - ns, end - ns, edit["target"] if first else ""))
            first = False
            covered += end - start
        if first or covered != edit["end"] - edit["start"]:
            raise VoiceError("Speech span cannot be mapped to original XML: " + block["id"])
    updates = []
    for index, edits_in_node in by_node.items():
        node = block["nodes"][index]
        value = replace_ranges(node["text"], edits_in_node)
        updates.append((node["content_start"], node["content_end"], escape(value).encode("utf-8")))
        if value and (value[0].isspace() or value[-1].isspace()) and node["space"] != "preserve":
            opening = payload[node["open_start"]:node["open_end"]]
            if re.search(br"\bxml:space\s*=", opening):
                opening = re.sub(br"\bxml:space\s*=\s*(['\"])[^'\"]*\1", b'xml:space="preserve"', opening)
            else:
                opening = opening[:-1] + b' xml:space="preserve">'
            updates.append((node["open_start"], node["open_end"], opening))
    return updates


def render(source, patch):
    blocks, grouped = validate_patch(source, patch)
    if source["format"] == "text":
        edits = [(blocks[bid]["offset"] + item["start"], blocks[bid]["offset"] + item["end"], item["target"])
                 for bid, items in grouped.items() for item in items]
        result = replace_ranges(source["text"], edits).encode("utf-8")
        return (b"\xef\xbb\xbf" if source["bom"] else b"") + result, None
    member_edits = {}
    for bid, items in grouped.items():
        block = blocks[bid]
        part = block["part"]
        member_edits.setdefault(part, []).extend(xml_replacements(block, items, source["parts"][part]))
    changed = {}
    for part, changes in member_edits.items():
        ordered = sorted(changes, key=lambda item: item[0])
        if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:])):
            raise VoiceError("Overlapping XML updates")
        changed[part] = replace_ranges(source["parts"][part], changes)
        actual, _ = xml_blocks(changed[part], part)
        actual = {b["id"]: b["text"] for b in actual}
        for block in (b for b in source["blocks"] if b.get("part") == part):
            expected = replace_ranges(block["text"], [(e["start"], e["end"], e["target"]) for e in grouped.get(block["id"], [])])
            if actual.get(block["id"]) != expected:
                raise VoiceError("DOCX paragraph read-back differs: " + block["id"])
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.comment = source["comment"]
        for member, payload in source["members"]:
            archive.writestr(member, changed.get(member.filename, payload))
    return buffer.getvalue(), {member.filename: changed.get(member.filename, payload) for member, payload in source["members"]}


def verify_output(source, patch, output, expected_raw=None, expected_parts=None):
    if Path(output).suffix.lower() != source["path"].suffix.lower():
        raise VoiceError("Output must use the same format as the source")
    if expected_raw is None:
        expected_raw, expected_parts = render(source, patch)
    raw = Path(output).read_bytes()
    if source["format"] == "text":
        if raw != expected_raw:
            raise VoiceError("Output differs from approved span-only replacements")
    else:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            expected_names = [m.filename for m, _ in source["members"]]
            if names != expected_names or archive.comment != source["comment"]:
                raise VoiceError("DOCX members/order/comment changed")
            for name in names:
                if archive.read(name) != expected_parts[name]:
                    raise VoiceError("Unexpected DOCX member content change: " + name)
    if sha(source["path"].read_bytes()) != source["source_sha256"]:
        raise VoiceError("Original source was changed during this operation")
    return {"status": "verified_selected_spans_only", "translations": len(patch["translations"]),
            "source_sha256": source["source_sha256"], "output_sha256": sha(raw),
            "warnings": source["warnings"], "semantic_review": "not_performed_by_script",
            "speech_scope_and_coverage": "must_be_checked_by_model", "audio_timing": "not_measured"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "locate", "apply", "verify"):
        command = sub.add_parser(name)
        command.add_argument("--source", required=True)
        if name == "inspect":
            command.add_argument("--out")
        if name == "locate":
            command.add_argument("--block", required=True)
            command.add_argument("--text", required=True)
        if name in ("apply", "verify"):
            command.add_argument("--patch", required=True)
        if name == "apply":
            command.add_argument("--out", required=True)
        if name == "verify":
            command.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        source = load_source(args.source)
        if args.command == "inspect":
            report = inspect(source)
            if args.out:
                write_new(args.out, (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"), args.source)
                report = {"inventory": str(Path(args.out).resolve()), "blocks": len(source["blocks"]), "warnings": source["warnings"]}
        elif args.command == "locate":
            block = next((b for b in source["blocks"] if b["id"] == args.block), None)
            if block is None or not args.text:
                raise VoiceError("Unknown block or empty search text")
            matches, cursor = [], 0
            while (position := block["text"].find(args.text, cursor)) >= 0:
                matches.append({"block_id": args.block, "start": position, "end": position + len(args.text), "source": args.text})
                cursor = position + 1
            report = {"matches": matches, "context": block["text"], "protected": block["protected"]}
        else:
            patch = read_json(args.patch)
            if args.command == "apply":
                check_destination(args.out, args.source, args.patch)
                if Path(args.out).suffix.lower() != Path(args.source).suffix.lower():
                    raise VoiceError("Output must use the same file extension")
                raw, parts = render(source, patch)
                if sha(Path(args.source).read_bytes()) != source["source_sha256"]:
                    raise VoiceError("Original changed before writing; re-read it")
                write_new(args.out, raw, args.source, args.patch)
                report = verify_output(source, patch, args.out, raw, parts)
                report["output"] = str(Path(args.out).resolve())
            else:
                report = verify_output(source, patch, args.output)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (VoiceError, OSError, UnicodeError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
