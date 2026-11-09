# 数据契约 schema 2 / B-release-2.0

UTF-8 project.json保存单一作品当前内容；文件级重复JSON键、NaN/Infinity拒绝。schema 1仍按旧契约兼容读取/检查，不能把旧审读冒称新版发布验收。用revise --migrate另存到新目录，原文件不改；未知人物/旁白/状态保持待核，旧审读stale。不降级已是2或更新的schema。

## 身份、内容与当前头

顶层schema_version=2，workflow_version=B-release-2.0，rules_version=2026-10-14.1。
project沿用id/title/revision/locale/region/era/scope_summary/episodes/expected_scene_ids/episode_duration/status/audio_status/video_status。id稳定；revision正整数；status=draft或locked。locale支持en-US/en-GB/en-CA/en-AU/en-IE。init默认en-US，具体地区/年代待原稿适配，不能把未知当确认。episodes正整数唯一升序；episode_duration集号键，kind=hard/reference/planned，seconds有限数，basis有依据，hard/planned精确相等，reference差异待核。未实测项目字段仍not_measured/not_generated。

lineage含content_hash、parent_content_hash、parent_revision、source_fingerprint、branch_id。根版本父项均null，修订父项精确指向前版，revision递增。content_hash是实际内容、来源、授权/设定及规则的SHA256；排除自身lineage、reviews/issues/acceptance、progress/operations/handoff与project修订号/锁定/媒体操作状态。其他未知附加字段保留并进入指纹，但保留不等于语义已支持。

编写后用release_contract.seal(doc,parent=before)封印，函数不签发审读。正常revise拒跨作品、错父指纹/父revision、倒退、未封内容、与head.json不一致的旧头；head是每剧目录的持久化当前指针，state_path相对head目录解析，不是通过证明。可选package_path也是相对头目录的导航；使用包仍须核对作品、内容版本及产物哈希，不能凭指针放行。--branch加新--head路径明确分支，不覆盖原分支。旧schema 1修订兼容原失效机制，当前头守卫需先迁移至2。

## 原有记录及新增约定

sources至少一份：id/name/sha256/extraction_status/reading_status/limitations/blocks。sha256是输入字节；block=id/locator/text/read/kind。kind=heading/action/dialogue/offscreen/narration/inner/other。提取后unread、read=false，真实逐块阅读后填写；不自动重开任意路径。TXT/MD为UTF-8，DOCX按正文表格顺序读取，不支持载体标partial并列限制。

entities：id/kind(character/location/prop)/original_name/name/fictional/version/description；variants可选[{id,description}]描述必需。relationship存在时为文本；character必要age_stage/voice_profile/relationship_basis，address_forms为角色ID到称呼对象，role=mentioned可注明未出场。未知精确年龄不猜；继承确认名字用inherited_mapping。资产身份、造型version与段内动态state分开。

narrators：id/type(external/present_inner/future_recollection/unknown)/time_view(present/past/future/unknown)/event_age_stage/speaking_age_stage/knowledge_boundary/reliability/audible_to。非external需要character_id，inner/未来回忆场内不可听，audible_to=[]；unknown待核。旁白speaker_id=null，无需伪造场内人物。

scenes沿用id/episode/order/title/goal/change/audience_information/preflight/entity_ids/entry_state/exit_state/knowledge；新增entry_reason、continuity=new_context或continues、critical_state_keys，可选previous_scene_id/context_scene_ids/entry_changes/depends_on。continues须直接前场链接与关键状态齐全；不一致有明确变化依据。前情依赖只指更早场，不允许环。knowledge包含characters角色ID对象，每个有knows/beliefs/pretends/withholds四个事实列表，audience独立列表；声明timepoint可区分入场和轮次变化。程序检查形状，实际知情仍需语义审读。

events=id/scene_id/description/phases（唯一有序），阶段须在镜头中按顺序恰好一次。
voices=id/scene_id/order/channel(dialogue/offscreen/narration/inner)/speaker_id/addressee_ids/text/meaning/intent/version/source_ids；narration/inner的narrator_id指独立身份；两者speaker_id=null。meaning是改后中文意思，source_ids保留原渠道。semantic_limits为可选高风险约束对象，不强制普通话音填满。pauses[{after_char,seconds}]锁停顿，overlap_group锁同时发声，estimated_speech_seconds仅文字规划。

segments=id/scene_id/episode/start（每集全局）/duration（0<秒≤15）/asset_refs/setting/sound/atmosphere/end_state/shots/audio。source_timecode可省略或null；其他值须有依据的非空文字。asset_refs=id/version/state，可variant_id；匹配当前实体版本及有效描述。
shot=id/start/end（段内）、framing/camera/composition/movement/action/event_refs[{event_id,phases}]；连续长镜用continuous_take_id和continues_shot_id，时间连续铺满全段，不重演动作。
audio=id/voice_id/voice_version/speaker_id/channel/char_start/char_end/text/start/end。Unicode字符半开区间，不是UTF-8字节，等于text切片；所有字完整一次，同说听渠道/版本。跨段时间与字符连续；片内停顿占片内，边界停顿占明确间隔。声轨独立于镜头，重叠须共同overlap_group。

coverage每个源block一条source_id/target_ids/reason，可authorization附加；target仅scene/event/voice，话音双向同渠道对应。目标/理由/授权进入真实依赖。ID在一部作品内全局唯一，另一作品可以重复局部ID；PROJECT、COV:、CULTURE:和CONTEXT:为程序保留记录空间。

constraints保存该作品主线/结局/允许变化和授权；cultural_decisions条目id/action(keep/adapt/verify/unresolved)/reason/affects_cause及可选status/evidence/region/era/affected_ids。因果相关核验须可靠证据、地区年代，未核待核。一般虚构生活设计不冒称现实制度确认。

## 审读、问题、真人与媒体

reviews=id/category/scope/status/reviewer/evidence/work_id/kind/result/snapshots。
category=adaptation/english_fidelity/english_viewing/feasibility/visual_storytelling/full_read；kind=same_source_ai或test，result=KEEP。test只能用于显式test_fixture工程材料。真实审读后调用review_record，快照展开递归依赖；英语绑定CONTEXT:整场话音/动作及必要前情。全局revision/操作日志不进入语义快照，跨作品不能沿用。

issues=id/scene_id/voice_id可选/excerpt/category/classification(confirmed/context/preference)/severity(minor/major/critical)/confidence(low/medium/high)/evidence/allowed_layer(facts/expression/schedule/shots)/attempts(0..2)/detail/status。保留修前片段用original_excerpt；关联root_issue_id存在且累计预算≤2，同定位改ID不重置。未闭问题待核；resolved/writer_decided/user_confirmed须resolution和recheck。recheck含当前work_id/scope（必须包含整场）/status=checked/result=KEEP/evidence/snapshots；用户确认另有真实user_confirmation。程序不证明语义，也不让writer_decided抵消确定重大错误。

acceptance={target_language:[],media:[]}。缺真实记录仍可交完整AI文字包，状态not_performed。真实记录须kind=real_attested，id/work_id/reviewer_source/qualification/date/scope/status/result/evidence/snapshots，另含revision/content_hash，精确绑定实际范围/版本/依赖。媒体另有artifacts[{name,sha256}]和measured_dimensions，只声明真实测过的项目。记录不能独立证明审者能力，禁止模拟人审认证。

handoff只作导航：work_id/content_hash/range/upstream/completed/unresolved/next_step；progress/operations不制造通过。恢复读取当前头、完整状态、来源、未决、最后实际完成场次；check --recovery的摘要不代替全文。

## 可运行命令与导出

SKILL_DIR替换成本SKILL.md所在真实目录，作品路径相对当前获准工作区，Python用环境已有解释器，不将产物写安装目录。

```text
python "SKILL_DIR/scripts/init_project.py" 原稿.txt --out work/作品 --title 作品名 --episodes 1,2
python "SKILL_DIR/scripts/check_deliverables.py" work/作品/project.json --report work/作品/check-r1.json --recovery --head work/作品/head.json
python "SKILL_DIR/scripts/revise_project.py" 旧项目.json --migrate --out work/迁移作品/project.json
python "SKILL_DIR/scripts/revise_project.py" work/作品/project.json work/作品/proposed-r2.json --out work/作品/project-r2.json
python "SKILL_DIR/scripts/revise_project.py" work/作品/project-r2.json work/作品/proposed-branch.json --out work/作品/branch.json --branch alternative --head work/作品/alternative-head.json
python "SKILL_DIR/scripts/export_deliverables.py" work/作品/project-r2.json --out outputs/作品-r2 --docx
python "SKILL_DIR/scripts/export_deliverables.py" work/作品/project-r2.json --out outputs/作品-r2 --resume
```

init只建来源草稿和唯一新作品ID、head，不创作/签发已读。check码0=当前文字记录齐全，3=待核，1=错误。导出结构错误拒绝，--allow-review-draft仅明示待核；默认不覆盖，--resume核相同作品内容版本，保留失败目录后重试。临时写入/回读，最终package.json+sha256列实际完整产物；TXT/DOCX同源，缺可选依赖诚实交TXT，失败无有效完整包。无递归清理。失效/导出本身不调用模型，不自动完成任何语义审读。
