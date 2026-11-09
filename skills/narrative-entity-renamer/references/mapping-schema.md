# Mapping and Context Rules

Read this reference when a renaming request mixes aliases, titles, complete names, relationships, simple family surname planning, or named locations, or when using `scripts/entity_rewrite.py`.

## 1. Classification model

### Person forms

- **Full personal name:** a complete identity such as a surname plus given name. Retain or introduce it only in an explicit complete-name context and only when approved.
- **Everyday honorific:** forms such as `陈姐`, `林太太`, `顾先生`, or `王叔`. These normally belong in dialogue, speaker labels, narrative prose, shot descriptions, continuity rules, and negative prompts.
- **Relationship label:** forms such as `她丈夫`, `林太太的丈夫`, or `顾先生的妻子`. Update dependent names without changing the relationship.
- **Technical role label:** forms such as `角色A林太太`. Keep the stable role ID and remove redundant parentheticals after renaming.

A string that happens to look like a full name is not automatically preferred. The requested context controls the form.

### Place forms

- **Named place:** a proper-name prefix plus a category suffix, such as `临江公寓`, `仁和医院`, or `云栖路`.
- **Generic place:** the category alone or a descriptive phrase, such as `公寓外景`, `去医院`, or `街道路口`.

Replace only the complete named place. Preserve its suffix unless the user explicitly changes the place category.

Common suffixes include `公寓`, `小区`, `花园`, `苑`, `府`, `城`, `酒店`, `医院`, `学校`, `大学`, `中学`, `小学`, `大厦`, `中心`, `会所`, `商场`, `公司`, `集团`, `餐厅`, `咖啡馆`, `路`, `街`, `巷`, `桥`, `站`, `机场`, and `码头`. This list is a search aid, not proof that every matching phrase is a proper name.

For `kind: named_location`, the helper derives the longest recognized category suffix from both source and destination. The declared `preserve_suffix` must equal both derived suffixes; a weak common tail such as `学` cannot disguise `中学` → `大学`.

## 2. Replacement precedence

1. Complete named locations and longest full names.
2. Complete aliases and honorifics.
3. Mechanical normalization created by the replacements.

Never replace single-character surnames globally. Never map a generic suffix such as `公寓` to a new named place. Do not use sequential replacement commands that can transform a newly inserted destination again.

The helper performs literal replacement after this semantic classification; it does not infer Chinese word boundaries. Review all candidate occurrences before mapping. For any source that could appear inside a longer identity or field, use a longer contextual rule and an exact `expected_matches` value, or edit that exceptional occurrence manually.

## 3. JSON mapping schema

The helper accepts UTF-8 JSON:

```json
{
  "format_version": 1,
  "replacements": [
    {
      "from": "临江公寓",
      "to": "锦溪公寓",
      "kind": "named_location",
      "preserve_suffix": "公寓",
      "expected_matches": 3
    },
    {
      "from": "陈秀兰",
      "to": "陈姐",
      "kind": "person_title",
      "expected_matches": 2
    },
    {
      "from": "陈姨",
      "to": "陈姐",
      "kind": "person_title",
      "expected_matches": 1
    },
    {
      "from": "林晚晴",
      "to": "林太太",
      "kind": "person_title",
      "expected_matches": 4
    }
  ],
  "forbid_sources_after": true,
  "require_destinations_after": true,
  "forbid_after": ["温太太", "李姐"],
  "require_after": ["锦溪公寓", "陈姐", "林太太"],
  "require_before": ["临江公寓"],
  "protected_terms": ["公寓", "角色A", "角色B"]
}
```

The example is illustrative, not a universal mapping. Replace every example count with the count from the actual occurrence inventory.

### Fields

- `format_version`: must be `1`.
- `replacements`: ordered records with nonempty `from` and `to` strings. The helper still executes them longest-source-first.
- `kind`: optional controlled audit label. Accepted values are `unspecified`, `person`, `person_alias`, `person_title`, `person_full_name`, `full_name`, `relationship`, `technical_role`, `speaker_label`, `named_location`, `organization`, and `other`.
- `preserve_suffix`: invariant requiring both source and destination to end with this exact suffix. It is mandatory when `kind` is `named_location`.
- `expected_matches`: optional nonnegative integer. Use it for every nontrivial rule after counting semantically approved, non-overlapping matches under longest-rule precedence; an occurrence consumed by a longer contextual rule does not count again for a nested shorter rule. A mismatch fails before output is written.
- `forbid_sources_after`: defaults to `true`. Set to `false` only when an old token is intentionally allowed in a separately reviewed context.
- `require_destinations_after`: defaults to `true`. A destination is required when its source matched at least once.
- `forbid_after`: extra tokens that must be absent after the pass.
- `require_after`: tokens that must exist after the pass.
- `require_before`: tokens that must exist before editing; useful for detecting the wrong source version.
- `protected_terms`: tokens whose total occurrence count must not change. Use this for stable role IDs or generic category nouns when the suffix should remain.
- `allow_short_sources`: defaults to `false`. Enabling it permits one-character sources and should be exceptional and manually reviewed.
- `allow_noop`: defaults to `false`. Set it to `true` only for an intentional validation-only pass, preferably with `expected_matches: 0`.

Unknown fields, duplicate sources, string-shaped booleans such as `"false"`, boolean-shaped format versions, mapping chains, source-inside-destination rules, generic location categories, pure-whitespace/hidden-control sources, and XML 1.0-invalid characters are rejected. Output and report paths must differ from the source, mapping, and each other even when `--force` is used.

`require_before_counts` is a raw literal substring count in the original text and may therefore be higher than a shorter rule's `matches` value when a longer contextual rule contains that shorter source. Use `expected_matches` for replacement ownership and `require_before` only as a source-version guard.

## 4. Full-name exception

If a document contains a genuine field such as `完整姓名：陈秀兰`, choose one of these explicitly:

- retain the approved full name only in that field and use `陈姐` elsewhere through a context-aware manual edit; or
- replace it with a separately approved new full name and map everyday aliases to `陈姐`.

The deterministic helper applies approved literal strings globally but executes longest sources first in a single pass. A unique complete field can therefore be mapped as a longer contextual rule, for example `角色B完整姓名：陈秀兰` → `角色B完整姓名：赵雅琴`, alongside the general rule `陈秀兰` → `陈姐`. Give both rules exact `expected_matches` values and validate the longer field with `require_before`. If the field is not unique, disambiguate it with stable surrounding text or handle the exceptional occurrence manually and audit it.

## 5. Simple family surname planning

The simple family surname lock is a semantic planning rule used before literal replacements are generated. It does not authorize global surname-character replacement.

Use it only when replacement full names are being invented and neither the user nor the source declares an exceptional surname arrangement. Under the ordinary-family default:

- paternal grandfather, father, and son share one new surname;
- maternal grandfather and mother share one new surname;
- paternal and maternal surname groups use different surnames by default;
- a married woman's full personal name retains her own approved surname;
- a spouse-based honorific such as `顾太太` may follow the husband's surname without changing a full name such as `沈知岚`;
- relatives who do not appear or do not need full names are not invented merely to complete a group;
- explicit user-approved names and explicit source exceptions override the default lock.

Choose and validate the complete replacement names before producing the JSON mapping. Record family role, surname group, and honorific surname source in the entity inventory. The executable mapping must continue to contain complete names and complete honorifics only.

Example family plan:

| Family role | Surname group | Old full name | New full name | New honorific |
|---|---|---|---|---|
| paternal grandfather | paternal | 张建国 | 顾怀山 | 顾老先生 |
| father | paternal | 张明远 | 顾承远 | 顾先生 |
| son | paternal | 张浩 | 顾景川 | 景川、小顾 |
| maternal grandfather | maternal | 林德山 | 沈伯川 | 沈老先生 |
| mother | maternal | 林雅琴 | 沈知岚 | 沈女士、顾太太 |

Valid complete-token mappings include:

- `张建国` → `顾怀山`
- `张明远` → `顾承远`
- `张浩` → `顾景川`
- `林德山` → `沈伯川`
- `林雅琴` → `沈知岚`
- `张先生` → `顾先生`
- `张太太` → `顾太太`
- `林女士` → `沈女士`

Never generate:

- `张` → `顾`
- `林` → `沈`

If a user-approved full name conflicts with the default surname group, preserve the approved name and record the exception. If two user-approved names conflict and the intended relationship cannot be determined without changing the user's choices, ask one concise question before editing.

Before execution, verify the planned names. After execution, verify the same invariants again:

- paternal grandfather, father, and son share the approved paternal surname;
- maternal grandfather and mother share the approved maternal surname;
- the two groups remain distinct unless an exception was approved;
- spouse-based honorifics do not alter a woman's full personal surname;
- no one-character surname rule entered the mapping.

## 6. Required QA

- Verify every old alias, not only the most visible one.
- Scan for proper-name suffixes after editing and classify each remaining result.
- Compare quoted dialogue before and after; approved entity tokens should be the only changes.
- Check role locks, continuity sections, negative prompts, filenames, captions, required/forbidden token lists, and regenerated artifacts.
- Confirm stable counts for segments, shots, frames, timestamps, or other structural invariants relevant to the source.
- When editing `.docx`, open or render the result when available; passing the text audit alone does not prove page layout quality.
- Read the report's audit scope. DOCX residual checks cover canonical URL-decoded ZIP member names plus visible text and canonical URL-decoded attribute values from every XML and relationship part. They do not inspect image pixels, embedded binary/OLE payload bodies, or content fetched from external links; relationship target strings themselves are scanned.
- When a DOCX scan fails, inspect `forbidden_after_locations`; it identifies the XML or relationship part containing each forbidden token.

After changing the helper itself, run its bundled regression suite from the skill root:

```powershell
python -X utf8 -m unittest discover -s tests -p "test_*.py" -v
```
