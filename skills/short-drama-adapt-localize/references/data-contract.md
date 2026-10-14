# 数据契约 v1 与命令

状态为单个UTF-8 project.json；完整可执行示例见项目 examples/three-scenes/build_example.py 及其 project.json。一次成品只引用一个定稿状态，不同时读多个冲突版本。未知附加字段可保留，但不代表程序检查了其语义。

## 顶层与必需字段

- schema_version: 1。
- project: id,title,revision,locale(en-US/en-GB/en-CA/en-AU/en-IE),region,era,scope_summary,episodes(正整数升序),expected_scene_ids,episode_duration,status(draft/locked),audio_status(not_measured),video_status(not_generated)。episode_duration以集号字符串为键，值含kind(hard/reference/planned)、seconds、basis。hard与planned精确比对，reference不符待核。用户批准另附真实证据，不代替locked。
- sources: id,name,sha256,extraction_status(complete/partial),reading_status(unread/complete),limitations,blocks。block含id,locator,text,read布尔,kind(heading/action/dialogue/offscreen/narration/other)。自动读入始终read=false，人工阅读后分类。sha256记录输入字节，不自动重开任意原始路径。
- entities: id,kind(character/location/prop),original_name,name,fictional,version正整数,description；可选inherited_mapping,relationship,voice_profile,variants[{id,description}],depends_on。身份ID不变，造型版本/动态状态分开。
- scenes: id,episode,order,title,goal,change,audience_information,preflight,entity_ids,entry_state,exit_state,knowledge；可选previous_scene_id,entry_changes,depends_on。knowledge应分角色/听者/观众，state为具名事实对象。跨场相同事实字段不一致须entry_changes理由；语义正确性另审。
- events: id,scene_id,description,phases(唯一有序动作阶段名),depends_on可选。所有阶段必须在镜头中恰好按顺序覆盖一次；连续长镜分片可覆盖不同阶段。
- voices: id,scene_id,order,channel(dialogue/offscreen/narration),speaker_id(旁白null),addressee_ids,text,meaning,intent,version,source_ids；可选pauses[{after_char,seconds}],overlap_group。text是最终英语，meaning是改后中文意思。旁白只对应源旁白，画外对白不能改渠道。
- segments: id,scene_id,episode,start(该集全局起点),duration,asset_refs,setting,sound,atmosphere,end_state,shots,audio；可选source_timecode（没有依据时省略）。asset_refs含id,version,state，variant_id可选。
- shot: id,start,end（段内）,framing,camera,composition,movement,action,event_refs[{event_id,phases}]；可选continuous_take_id,continues_shot_id。无新事件的状态保持镜event_refs可空；不能漏/重演事件。全段镜头时间连续铺满。
- audio片段: id,voice_id,voice_version,speaker_id,channel,char_start,char_end,text,start,end。Python Unicode字符半开区间，不是UTF-8字节；必须等于锁定text切片，保留空格与标点。跨段字符与全局时间连续；有停顿须锁定pauses。一个片段可跨同段多个镜头，不需要重复写入每镜。
- coverage: 每个源block一条{source_id,target_ids,reason}；目标scene/event/voice。源话音必须对应同渠道voice且voice.source_ids反指来源；允许一对多/多对一，不强制句数相等。
- reviews: id,category,scope,status,reviewer,evidence,snapshots。用drama_core.review_record在真实审读之后记录；快照包含递归依赖。categories=adaptation/english/feasibility/visual_storytelling。事件依赖场景，场景依赖资产与前场，话音依赖源/角色，成品依赖资产/事件/话音；新增依赖可写depends_on，禁止环。
- issues: id,status,detail；resolved必须resolution；建议附证据、影响ID、修复范围/次数/版本。未关闭问题阻止正常版，但可显式导出待核版。

sources/entities/scenes/events/voices/segments和各source block的ID全局唯一；PROJECT保留给项目记录。镜头/音轨ID也不能重复。空列表只在实际无此类别时可用，不能用空段冒充输出。

## 命令（在项目根目录，python换成当前可用解释器）

```text
python skills/short-drama-adapt-localize/scripts/init_project.py 输入.docx --out work/作品-r1 --title 作品名 --locale en-GB --region 英国某地 --era 1998 --episodes 1,2,3
python skills/short-drama-adapt-localize/scripts/check_deliverables.py work/作品-r1/project.json --report work/作品-r1/check-1.json
python skills/short-drama-adapt-localize/scripts/revise_project.py 旧状态.json 拟定新状态.json --out 新状态-失效标记.json
python skills/short-drama-adapt-localize/scripts/export_deliverables.py work/作品-r1/project.json --out outputs/作品-r1 --docx
```

读取脚本只提取，不自动标已读/改编。当前助手依skill完成内容并保存状态，再检查/导出；不是无模型命令行翻译器。导出目录必须不存在，失败留下的文件及报告要检查后另选新目录，不静默覆盖。--allow-review-draft仅允许语义/来源待核，不能绕开确定结构错误。

严格JSON：重复键、NaN/Infinity拒绝。数值用十进制定点比较防15.01误过。音频/视频验收未实现，因此不能写audio_status=passed。源DOCX正文与表格按文档顺序读，复杂文本框/脚注/修订/图片等保守标partial，不能当已提取全稿。
