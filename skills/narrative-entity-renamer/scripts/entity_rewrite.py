#!/usr/bin/env python3
"""Apply audited, non-cascading entity replacements to UTF-8 text or DOCX files."""

from __future__ import annotations

import argparse
import codecs
import html
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote


PARAGRAPH_RE = re.compile(
    r"<(?P<prefix>w|a):p\b[^>]*>.*?</(?P=prefix):p>", re.DOTALL
)
TEXT_NODE_RE = re.compile(
    r"(?P<open><(?P<prefix>w|a):t\b[^>]*>)(?P<text>.*?)(?P<close></(?P=prefix):t>)",
    re.DOTALL,
)
RUN_PROPERTY_BLOCK_RE = re.compile(
    r"<(?P<prefix>w|a):rPr\b[^>]*>.*?</(?P=prefix):rPr>", re.DOTALL | re.IGNORECASE
)
RUN_PROPERTY_EMPTY_RE = re.compile(r"<(?:w|a):rPr\b[^>]*/>", re.DOTALL | re.IGNORECASE)
XML_TAG_RE = re.compile(
    r"</?(?P<prefix>[A-Za-z_][\w.-]*):(?P<name>[A-Za-z_][\w.-]*)\b[^>]*>",
    re.DOTALL,
)
NON_BARRIER_TAGS = {
    ("w", "r"),
    ("a", "r"),
    ("w", "bookmarkStart"),
    ("w", "bookmarkEnd"),
    ("w", "proofErr"),
    ("w", "permStart"),
    ("w", "permEnd"),
    ("w", "commentRangeStart"),
    ("w", "commentRangeEnd"),
    ("w", "moveFromRangeStart"),
    ("w", "moveFromRangeEnd"),
    ("w", "moveToRangeStart"),
    ("w", "moveToRangeEnd"),
    ("w", "customXmlInsRangeStart"),
    ("w", "customXmlInsRangeEnd"),
    ("w", "customXmlDelRangeStart"),
    ("w", "customXmlDelRangeEnd"),
    ("w", "customXmlMoveFromRangeStart"),
    ("w", "customXmlMoveFromRangeEnd"),
    ("w", "customXmlMoveToRangeStart"),
    ("w", "customXmlMoveToRangeEnd"),
}
GENERIC_LOCATION_TERMS = {
    "省",
    "市",
    "区",
    "县",
    "镇",
    "乡",
    "村",
    "城",
    "苑",
    "府",
    "路",
    "街",
    "巷",
    "桥",
    "站",
    "楼",
    "室",
    "公寓",
    "小区",
    "社区",
    "住宅",
    "别墅",
    "宿舍",
    "花园",
    "公园",
    "酒店",
    "医院",
    "诊所",
    "药店",
    "养老院",
    "福利院",
    "学校",
    "大学",
    "中学",
    "小学",
    "幼儿园",
    "大厦",
    "写字楼",
    "办公楼",
    "中心",
    "会所",
    "商场",
    "超市",
    "市场",
    "广场",
    "公司",
    "集团",
    "工厂",
    "仓库",
    "园区",
    "产业园",
    "基地",
    "餐厅",
    "咖啡馆",
    "书店",
    "图书馆",
    "博物馆",
    "体育馆",
    "影城",
    "剧院",
    "游乐园",
    "景区",
    "山庄",
    "度假村",
    "派出所",
    "警察局",
    "法院",
    "检察院",
    "银行",
    "车站",
    "火车站",
    "高铁站",
    "地铁站",
    "机场",
    "码头",
}
LOCATION_SUFFIXES = tuple(sorted(GENERIC_LOCATION_TERMS, key=lambda value: (-len(value), value)))
ALLOWED_KINDS = {
    "unspecified",
    "person",
    "person_alias",
    "person_title",
    "person_full_name",
    "full_name",
    "relationship",
    "technical_role",
    "speaker_label",
    "named_location",
    "organization",
    "other",
}
ROOT_KEYS = {
    "format_version",
    "replacements",
    "forbid_sources_after",
    "require_destinations_after",
    "forbid_after",
    "require_after",
    "require_before",
    "protected_terms",
    "allow_short_sources",
    "allow_noop",
}
RULE_KEYS = {"from", "to", "kind", "preserve_suffix", "expected_matches"}


class MappingError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    source: str
    destination: str
    kind: str
    preserve_suffix: str | None
    expected_matches: int | None


@dataclass
class MappingConfig:
    rules: list[Rule]
    forbid_after: list[str]
    require_after: list[str]
    require_before: list[str]
    protected_terms: list[str]
    forbid_sources_after: bool
    require_destinations_after: bool
    allow_noop: bool


def _strict_bool(data: dict[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise MappingError(f"{key} must be a JSON boolean")
    return value


def _valid_xml_10(value: str) -> bool:
    for character in value:
        codepoint = ord(character)
        if codepoint in {0x9, 0xA, 0xD}:
            continue
        if 0x20 <= codepoint <= 0xD7FF or 0xE000 <= codepoint <= 0xFFFD or 0x10000 <= codepoint <= 0x10FFFF:
            continue
        return False
    return True


def _contains_unicode_control(value: str) -> bool:
    return any(unicodedata.category(character).startswith("C") for character in value)


def _actual_location_suffix(value: str) -> str | None:
    return next(
        (suffix for suffix in LOCATION_SUFFIXES if value.endswith(suffix) and len(value) > len(suffix)),
        None,
    )


def _string_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise MappingError(f"{key} must be a list of nonempty strings")
    return list(dict.fromkeys(value))


def load_mapping(path: Path) -> MappingConfig:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MappingError(f"cannot read mapping JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise MappingError("mapping root must be an object")
    unknown_root_keys = sorted(set(data) - ROOT_KEYS)
    if unknown_root_keys:
        raise MappingError("unknown mapping fields: " + ", ".join(unknown_root_keys))
    format_version = data.get("format_version")
    if (
        not isinstance(format_version, int)
        or isinstance(format_version, bool)
        or format_version != 1
    ):
        raise MappingError("format_version must be 1")

    raw_rules = data.get("replacements")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise MappingError("replacements must be a nonempty list")

    allow_short = _strict_bool(data, "allow_short_sources", False)
    rules: list[Rule] = []
    seen: dict[str, str] = {}

    for index, item in enumerate(raw_rules, 1):
        if not isinstance(item, dict):
            raise MappingError(f"replacement {index} must be an object")
        unknown_rule_keys = sorted(set(item) - RULE_KEYS)
        if unknown_rule_keys:
            raise MappingError(
                f"replacement {index} has unknown fields: " + ", ".join(unknown_rule_keys)
            )
        source = item.get("from")
        destination = item.get("to")
        kind = item.get("kind", "unspecified")
        suffix = item.get("preserve_suffix")
        expected_matches = item.get("expected_matches")
        if not isinstance(source, str) or not source.strip():
            raise MappingError(f"replacement {index}.from must be a nonempty string")
        if not isinstance(destination, str) or not destination.strip():
            raise MappingError(f"replacement {index}.to must be a nonempty string")
        if source == destination:
            raise MappingError(f"replacement {index} maps a token to itself: {source!r}")
        if not isinstance(kind, str) or not kind:
            raise MappingError(f"replacement {index}.kind must be a nonempty string")
        if kind not in ALLOWED_KINDS:
            raise MappingError(
                f"replacement {index}.kind must be one of: " + ", ".join(sorted(ALLOWED_KINDS))
            )
        if suffix is not None and (not isinstance(suffix, str) or not suffix):
            raise MappingError(f"replacement {index}.preserve_suffix must be a nonempty string")
        if expected_matches is not None and (
            not isinstance(expected_matches, int) or isinstance(expected_matches, bool) or expected_matches < 0
        ):
            raise MappingError(f"replacement {index}.expected_matches must be a nonnegative integer")
        if not _valid_xml_10(source) or not _valid_xml_10(destination):
            raise MappingError(f"replacement {index} contains XML 1.0-prohibited characters")
        if _contains_unicode_control(source) or _contains_unicode_control(destination):
            raise MappingError(f"replacement {index} contains hidden or control characters")
        if not allow_short and len(source.strip()) < 2:
            raise MappingError(
                f"unsafe short source {source!r}; map a complete entity or explicitly set allow_short_sources"
            )
        if source in destination:
            raise MappingError(
                f"source {source!r} occurs inside destination {destination!r}; this is usually a broad unsafe mapping"
            )
        if source in GENERIC_LOCATION_TERMS:
            raise MappingError(f"refusing to map generic location category {source!r}; map the complete named place")
        if kind == "named_location" and suffix is None:
            raise MappingError(f"named_location rule {source!r} must declare preserve_suffix")
        if kind == "named_location" and suffix not in GENERIC_LOCATION_TERMS:
            raise MappingError(
                f"named_location suffix {suffix!r} is not an approved place-category suffix"
            )
        if kind == "named_location" and (source == suffix or destination == suffix):
            raise MappingError(
                f"named_location source and destination must include a proper-name prefix before {suffix!r}"
            )
        if suffix is not None and (not source.endswith(suffix) or not destination.endswith(suffix)):
            raise MappingError(
                f"suffix invariant {suffix!r} failed for {source!r} -> {destination!r}"
            )
        if kind == "named_location":
            source_suffix = _actual_location_suffix(source)
            destination_suffix = _actual_location_suffix(destination)
            if source_suffix != suffix or destination_suffix != suffix:
                raise MappingError(
                    f"named_location must preserve its longest recognized category suffix: "
                    f"{source!r} ({source_suffix!r}) -> {destination!r} ({destination_suffix!r}), "
                    f"declared {suffix!r}"
                )
        if source in seen:
            raise MappingError(f"duplicate replacement source is not allowed: {source!r}")
        seen[source] = destination
        rules.append(Rule(source, destination, kind, suffix, expected_matches))

    sources = {rule.source for rule in rules}
    conflicts = sorted({rule.destination for rule in rules if rule.destination in sources})
    if conflicts:
        raise MappingError(
            "destinations also used as sources (chain risk): " + ", ".join(repr(x) for x in conflicts)
        )

    return MappingConfig(
        rules=rules,
        forbid_after=_string_list(data, "forbid_after"),
        require_after=_string_list(data, "require_after"),
        require_before=_string_list(data, "require_before"),
        protected_terms=_string_list(data, "protected_terms"),
        forbid_sources_after=_strict_bool(data, "forbid_sources_after", True),
        require_destinations_after=_strict_bool(data, "require_destinations_after", True),
        allow_noop=_strict_bool(data, "allow_noop", False),
    )


def compile_rules(rules: Iterable[Rule]) -> tuple[re.Pattern[str], dict[str, Rule]]:
    ordered = sorted(rules, key=lambda rule: (-len(rule.source), rule.source))
    lookup = {rule.source: rule for rule in ordered}
    pattern = re.compile("|".join(re.escape(rule.source) for rule in ordered))
    return pattern, lookup


def replace_text(
    text: str, pattern: re.Pattern[str], lookup: dict[str, Rule]
) -> tuple[str, Counter[str]]:
    counts: Counter[str] = Counter()

    def replacement(match: re.Match[str]) -> str:
        source = match.group(0)
        counts[source] += 1
        return lookup[source].destination

    return pattern.sub(replacement, text), counts


def rewrite_parts(
    parts: list[str], pattern: re.Pattern[str], lookup: dict[str, Rule]
) -> tuple[list[str], Counter[str]]:
    logical = "".join(parts)
    matches = list(pattern.finditer(logical))
    if not matches:
        return parts, Counter()

    starts: list[int] = []
    ends: list[int] = []
    cursor = 0
    for part in parts:
        starts.append(cursor)
        cursor += len(part)
        ends.append(cursor)
    outputs = ["" for _ in parts]
    counts: Counter[str] = Counter()

    def append_original(start: int, end: int) -> None:
        for node_index, (node_start, node_end) in enumerate(zip(starts, ends)):
            overlap_start = max(start, node_start)
            overlap_end = min(end, node_end)
            if overlap_start < overlap_end:
                outputs[node_index] += parts[node_index][
                    overlap_start - node_start : overlap_end - node_start
                ]

    def append_destination(start: int, end: int, destination: str) -> None:
        affected: list[tuple[int, int]] = []
        for node_index, (node_start, node_end) in enumerate(zip(starts, ends)):
            overlap = max(0, min(end, node_end) - max(start, node_start))
            if overlap:
                affected.append((node_index, overlap))
        if not affected:
            raise MappingError("internal error: replacement span has no owning text run")

        source_length = end - start
        destination_length = len(destination)
        consumed_source = 0
        consumed_destination = 0
        for position, (node_index, overlap) in enumerate(affected):
            consumed_source += overlap
            if position == len(affected) - 1:
                cut = destination_length
            else:
                cut = (consumed_source * destination_length + source_length // 2) // source_length
            outputs[node_index] += destination[consumed_destination:cut]
            consumed_destination = cut

    source_cursor = 0
    for match in matches:
        append_original(source_cursor, match.start())
        source = match.group(0)
        append_destination(match.start(), match.end(), lookup[source].destination)
        counts[source] += 1
        source_cursor = match.end()
    append_original(source_cursor, len(logical))
    return outputs, counts


def has_structural_barrier(fragment: str) -> bool:
    cleaned = RUN_PROPERTY_BLOCK_RE.sub("", fragment)
    cleaned = RUN_PROPERTY_EMPTY_RE.sub("", cleaned)
    for tag in XML_TAG_RE.finditer(cleaned):
        key = (tag.group("prefix").lower(), tag.group("name"))
        if key not in NON_BARRIER_TAGS:
            return True
    return False


def split_text_node_groups(
    block: str, nodes: list[re.Match[str]]
) -> list[list[re.Match[str]]]:
    groups: list[list[re.Match[str]]] = []
    current: list[re.Match[str]] = []
    previous: re.Match[str] | None = None
    for node in nodes:
        if previous is not None and has_structural_barrier(block[previous.end() : node.start()]):
            if current:
                groups.append(current)
            current = []
        current.append(node)
        previous = node
    if current:
        groups.append(current)
    return groups


def rewrite_xml_bytes(
    raw: bytes, pattern: re.Pattern[str], lookup: dict[str, Rule]
) -> tuple[bytes, Counter[str]]:
    try:
        xml = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw, Counter()
    total: Counter[str] = Counter()

    def rewrite_paragraph(paragraph_match: re.Match[str]) -> str:
        block = paragraph_match.group(0)
        nodes = list(TEXT_NODE_RE.finditer(block))
        if not nodes:
            return block
        replacements: dict[int, str] = {}
        paragraph_counts: Counter[str] = Counter()
        for group in split_text_node_groups(block, nodes):
            parts = [html.unescape(node.group("text")) for node in group]
            new_parts, counts = rewrite_parts(parts, pattern, lookup)
            paragraph_counts.update(counts)
            for node, old_text, new_text in zip(group, parts, new_parts):
                if old_text != new_text:
                    replacements[node.start()] = new_text
        if not paragraph_counts:
            return block
        total.update(paragraph_counts)
        rewritten = block
        for node in reversed(nodes):
            if node.start() not in replacements:
                continue
            new_text = replacements[node.start()]
            opening = node.group("open")
            if new_text and (new_text[0].isspace() or new_text[-1].isspace()) and "xml:space=" not in opening:
                opening = opening[:-1] + ' xml:space="preserve">'
            replacement_node = opening + html.escape(new_text, quote=False) + node.group("close")
            start, end = node.span(0)
            rewritten = rewritten[:start] + replacement_node + rewritten[end:]
        return rewritten

    rewritten_xml = PARAGRAPH_RE.sub(rewrite_paragraph, xml)
    return rewritten_xml.encode("utf-8"), total


def extract_xml_text(raw: bytes) -> str:
    try:
        xml = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    paragraphs: list[str] = []
    for paragraph in PARAGRAPH_RE.finditer(xml):
        block = paragraph.group(0)
        nodes = list(TEXT_NODE_RE.finditer(block))
        for group in split_text_node_groups(block, nodes):
            paragraphs.append("".join(html.unescape(node.group("text")) for node in group))
    return "\n".join(paragraphs)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def extract_package_xml_text(raw: bytes, part_name: str) -> str:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise MappingError(f"invalid XML in DOCX part {part_name}: {exc}") from exc

    chunks: list[str] = []
    attribute_chunks: list[str] = []
    barrier_names = {
        "br",
        "tab",
        "cr",
        "fldChar",
        "instrText",
        "delText",
        "sym",
        "noBreakHyphen",
        "softHyphen",
        "ptab",
        "object",
        "drawing",
        "pict",
    }

    def separator() -> None:
        if chunks and chunks[-1] != "\n":
            chunks.append("\n")

    def walk(element: ET.Element, in_paragraph: bool = False) -> None:
        name = _local_name(element.tag)
        starts_paragraph = name == "p"
        if starts_paragraph:
            separator()
            in_paragraph = True
        if name in barrier_names:
            separator()

        for attribute_value in element.attrib.values():
            if not attribute_value:
                continue
            attribute_chunks.append(unquote(attribute_value))

        children = list(element)
        if not children:
            if element.text:
                if name == "t" and in_paragraph:
                    chunks.append(element.text)
                elif element.text.strip():
                    separator()
                    chunks.append(element.text)
                    separator()
        else:
            if element.text and element.text.strip():
                separator()
                chunks.append(element.text)
                separator()
            for child in children:
                walk(child, in_paragraph)
                if child.tail and child.tail.strip():
                    separator()
                    chunks.append(child.tail)
                    separator()

        if name in barrier_names or starts_paragraph:
            separator()

    walk(root)
    visible_text = "".join(chunks)
    attribute_text = "\n".join(attribute_chunks)
    return visible_text + ("\n" if visible_text and attribute_text else "") + attribute_text


def is_narrative_docx_part(name: str) -> bool:
    if not name.startswith("word/") or not name.endswith(".xml"):
        return False
    basename = name.rsplit("/", 1)[-1]
    return bool(
        basename == "document.xml"
        or re.fullmatch(r"header\d*\.xml", basename)
        or re.fullmatch(r"footer\d*\.xml", basename)
        or basename in {"footnotes.xml", "endnotes.xml", "comments.xml"}
    )


def transform_docx(
    source: Path, pattern: re.Pattern[str], lookup: dict[str, Rule]
) -> tuple[Path, str, str, str, str, Counter[str], list[str], list[str], dict[str, str]]:
    temp_file = tempfile.NamedTemporaryFile(prefix="entity-rewrite-", suffix=".docx", delete=False)
    temp_path = Path(temp_file.name)
    temp_file.close()
    before_parts: list[str] = []
    after_parts: list[str] = []
    package_before_parts: list[str] = []
    package_after_parts: list[str] = []
    processed_parts: list[str] = []
    audited_parts: list[str] = []
    package_after_by_part: dict[str, str] = {}
    total: Counter[str] = Counter()
    try:
        with zipfile.ZipFile(source, "r") as source_zip, zipfile.ZipFile(temp_path, "w") as output_zip:
            for info in source_zip.infolist():
                raw = source_zip.read(info.filename)
                member_text = unquote(info.filename)
                package_before_parts.append(member_text)
                package_after_parts.append(member_text)
                package_after_by_part[f"[ZIP member] {info.filename}"] = member_text
                is_xml = info.filename.lower().endswith((".xml", ".rels"))
                if is_xml:
                    audited_parts.append(info.filename)
                    package_before_parts.append(extract_package_xml_text(raw, info.filename))
                if is_narrative_docx_part(info.filename):
                    processed_parts.append(info.filename)
                    before_parts.append(extract_xml_text(raw))
                    raw, counts = rewrite_xml_bytes(raw, pattern, lookup)
                    total.update(counts)
                    after_parts.append(extract_xml_text(raw))
                if is_xml:
                    part_text = extract_package_xml_text(raw, info.filename)
                    package_after_parts.append(part_text)
                    package_after_by_part[info.filename] = part_text
                output_zip.writestr(info, raw)
        validate_docx_package(temp_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return (
        temp_path,
        "\n".join(before_parts),
        "\n".join(after_parts),
        "\n".join(package_before_parts),
        "\n".join(package_after_parts),
        total,
        processed_parts,
        audited_parts,
        package_after_by_part,
    )


def validate_docx_package(path: Path) -> None:
    try:
        with zipfile.ZipFile(path, "r") as package:
            corrupt_member = package.testzip()
            if corrupt_member is not None:
                raise MappingError(f"corrupt DOCX member after rewrite: {corrupt_member}")
            for name in package.namelist():
                if name.lower().endswith((".xml", ".rels")):
                    try:
                        ET.fromstring(package.read(name))
                    except ET.ParseError as exc:
                        raise MappingError(f"invalid rewritten XML in DOCX part {name}: {exc}") from exc
    except zipfile.BadZipFile as exc:
        raise MappingError(f"invalid DOCX package: {exc}") from exc


def read_utf8_text(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes()
    has_bom = raw.startswith(codecs.BOM_UTF8)
    if has_bom:
        raw = raw[len(codecs.BOM_UTF8) :]
    try:
        return raw.decode("utf-8"), has_bom
    except UnicodeDecodeError as exc:
        raise MappingError(f"text input must be UTF-8: {exc}") from exc


def encode_utf8_text(text: str, has_bom: bool) -> bytes:
    raw = text.encode("utf-8")
    return (codecs.BOM_UTF8 + raw) if has_bom else raw


def count_terms(text: str, terms: Iterable[str]) -> dict[str, int]:
    return {term: text.count(term) for term in terms}


def build_report(
    source: Path,
    intended_output: Path | None,
    config: MappingConfig,
    before: str,
    after: str,
    residual_before: str,
    residual_after: str,
    replacement_counts: Counter[str],
    audit_scope: dict[str, Any],
    residual_parts: dict[str, str],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    total_replacements = sum(replacement_counts.values())

    if total_replacements == 0 and not config.allow_noop:
        errors.append(
            "no replacement sources matched; verify the source version or set allow_noop to true intentionally"
        )

    required_before_counts = count_terms(before, config.require_before)
    for term, count in required_before_counts.items():
        if count == 0:
            errors.append(f"required source token missing: {term}")

    forbidden = list(config.forbid_after)
    if config.forbid_sources_after:
        forbidden.extend(rule.source for rule in config.rules)
    forbidden = list(dict.fromkeys(forbidden))
    forbidden_counts = count_terms(residual_after, forbidden)
    forbidden_locations = {
        term: [
            {"scope": scope, "count": text.count(term)}
            for scope, text in residual_parts.items()
            if text.count(term)
        ]
        for term in forbidden
    }
    for term, count in forbidden_counts.items():
        if count:
            errors.append(f"forbidden token remains ({count}): {term}")

    required = list(config.require_after)
    if config.require_destinations_after:
        for rule in config.rules:
            if replacement_counts[rule.source] > 0:
                required.append(rule.destination)
    required = list(dict.fromkeys(required))
    required_counts = count_terms(after, required)
    for term, count in required_counts.items():
        if count == 0:
            errors.append(f"required destination missing: {term}")

    protected_before = count_terms(before, config.protected_terms)
    protected_after = count_terms(after, config.protected_terms)
    for term in config.protected_terms:
        if protected_before[term] != protected_after[term]:
            errors.append(
                f"protected term count changed for {term}: {protected_before[term]} -> {protected_after[term]}"
            )

    for rule in config.rules:
        if replacement_counts[rule.source] == 0:
            warnings.append(f"source token not found: {rule.source}")
        if (
            rule.expected_matches is not None
            and replacement_counts[rule.source] != rule.expected_matches
        ):
            errors.append(
                f"unexpected match count for {rule.source}: "
                f"expected {rule.expected_matches}, got {replacement_counts[rule.source]}"
            )

    replacements = [
        {
            "from": rule.source,
            "to": rule.destination,
            "kind": rule.kind,
            "preserve_suffix": rule.preserve_suffix,
            "expected_matches": rule.expected_matches,
            "matches": replacement_counts[rule.source],
        }
        for rule in config.rules
    ]
    return {
        "status": "PASS" if not errors else "FAIL",
        "source": str(source.resolve()),
        "output": str(intended_output.resolve()) if intended_output else None,
        "changed": before != after,
        "total_replacements": total_replacements,
        "replacements": replacements,
        "audit_scope": audit_scope,
        "residual_scan_input_characters": len(residual_before),
        "residual_scan_output_characters": len(residual_after),
        "required_before_counts": required_before_counts,
        "forbidden_after_counts": forbidden_counts,
        "forbidden_after_locations": forbidden_locations,
        "required_after_counts": required_counts,
        "protected_term_counts": {
            term: {"before": protected_before[term], "after": protected_after[term]}
            for term in config.protected_terms
        },
        "warnings": warnings,
        "errors": errors,
    }


def atomic_write_bytes(path: Path, data: bytes, force: bool) -> None:
    if path.exists() and not force:
        raise MappingError(f"refusing to overwrite existing file without --force: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def atomic_copy_file(source: Path, path: Path, force: bool) -> None:
    if path.exists() and not force:
        raise MappingError(f"refusing to overwrite existing file without --force: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with source.open("rb") as input_handle, os.fdopen(descriptor, "wb") as output_handle:
            shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)
            output_handle.flush()
            os.fsync(output_handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def write_report(path: Path, report: dict[str, Any], force: bool) -> None:
    payload = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    atomic_write_bytes(path, payload, force)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply audited, one-pass entity replacements to UTF-8 text or DOCX files."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--map", dest="mapping", type=Path, required=True, help="UTF-8 JSON mapping")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path, help="write a new transformed file")
    mode.add_argument("--dry-run", action="store_true", help="validate and report without writing output")
    parser.add_argument("--report", type=Path, help="optional JSON audit report")
    parser.add_argument("--force", action="store_true", help="allow overwriting output or report")
    return parser.parse_args(argv)


def canonical_path(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    source: Path = args.source
    output: Path | None = args.output
    temp_docx: Path | None = None
    try:
        if not source.is_file():
            raise MappingError(f"source file not found: {source}")
        if not args.mapping.is_file():
            raise MappingError(f"mapping file not found: {args.mapping}")
        source_key = canonical_path(source)
        mapping_key = canonical_path(args.mapping)
        output_key = canonical_path(output) if output is not None else None
        report_key = canonical_path(args.report) if args.report is not None else None
        if source_key == mapping_key:
            raise MappingError("mapping file must differ from source")
        if output_key is not None and output_key == source_key:
            raise MappingError("output must differ from source; write a new file and verify it first")
        if output_key is not None and output_key == mapping_key:
            raise MappingError("output must differ from the mapping file")
        if report_key is not None and report_key in {source_key, mapping_key, output_key}:
            raise MappingError("report must differ from source, mapping, and output paths")
        if output is not None and output.exists() and not args.force:
            raise MappingError(f"refusing to overwrite existing output without --force: {output}")
        if args.report is not None and args.report.exists() and not args.force:
            raise MappingError(f"refusing to overwrite existing report without --force: {args.report}")

        config = load_mapping(args.mapping)
        pattern, lookup = compile_rules(config.rules)

        if source.suffix.lower() == ".docx":
            if output is not None and output.suffix.lower() != ".docx":
                raise MappingError("DOCX input requires a .docx output")
            (
                temp_docx,
                before,
                after,
                residual_before,
                residual_after,
                counts,
                processed_parts,
                audited_parts,
                residual_parts,
            ) = transform_docx(source, pattern, lookup)
            audit_scope = {
                "replacement": "Word narrative XML parts: " + ", ".join(processed_parts),
                "residual_scan": (
                    f"all URL-decoded ZIP member names plus visible text and canonical URL-decoded "
                    f"attribute values in all {len(audited_parts)} XML/.rels parts"
                ),
                "excluded": (
                    "image pixels, embedded binary/OLE payload bodies, and content fetched from "
                    "external links; relationship target strings themselves are scanned"
                ),
            }
            output_payload: bytes | None = None
        else:
            if output is not None and output.suffix.lower() == ".docx":
                raise MappingError("text input cannot be written as a .docx package")
            before, has_bom = read_utf8_text(source)
            after, counts = replace_text(before, pattern, lookup)
            residual_before = before
            residual_after = after
            residual_parts = {str(source.resolve()): after}
            audit_scope = {
                "replacement": "entire UTF-8 text file",
                "residual_scan": "entire UTF-8 text file",
                "excluded": "none",
            }
            output_payload = encode_utf8_text(after, has_bom)

        report = build_report(
            source,
            output,
            config,
            before,
            after,
            residual_before,
            residual_after,
            counts,
            audit_scope,
            residual_parts,
        )
        if report["errors"]:
            if args.report is not None:
                write_report(args.report, report, args.force)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 3
        if args.dry_run:
            if args.report is not None:
                write_report(args.report, report, args.force)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        assert output is not None
        if source.suffix.lower() == ".docx":
            assert temp_docx is not None
            atomic_copy_file(temp_docx, output, args.force)
        else:
            assert output_payload is not None
            atomic_write_bytes(output, output_payload, args.force)
        if args.report is not None:
            write_report(args.report, report, args.force)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (MappingError, OSError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if temp_docx is not None:
            temp_docx.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
