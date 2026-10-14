# transdrama

已实现 B 方案：由当前助手执行的「短剧适度改编＋指定英语地区本土化」skill 工作流，配有来源读取、结构检查、版本失效与 TXT/DOCX 导出工具。不是一键调用外部模型的应用，也不是多个 GitHub 工具拼接的流水线。

## 最简单的使用方式

在 transdrama 项目中发起任务，附上素材并发送：

```text
请按本项目 AGENTS.md，完整读取 skills/short-drama-adapt-localize/SKILL.md，
使用 B 工作流处理我上传的视频提示词。

范围：第01—31集。
目标：美国英语 en-US；美国俄勒冈州虚构小镇；保留原稿年代，不擅自现代化。
输出：中文制作说明，英语对白和原有旁白，完整视频生成提示词，TXT和可用时DOCX。
已有设定：无；如素材有已确认的新设定，先区分参考旧设定与确认设定。
时长：原稿有硬总长则遵守；仅有估时须区分，冲突先指出，不删句/加速。

姓名全改、主要形象重设计、主要关系实改，剧情主线和结局方向保持，
必要局部情节、场景道具、对白与新关系联动。
原有旁白保留，无则不新增。不默认添加灵物替换专项。
先读完整范围再确定全局，锁稿后镜头不加戏。
维护可续作的project.json，实际检查并交付完整范围，不只给大纲。
不调用外部模型，不上传素材，不覆盖原稿；目标地区与原设定冲突时集中说明。
```

上面地区是调用示例，不是默认值；按作品实际需求改成明确地区、英语类型和年代。只有「欧美」而没有这些信息时，助手会集中询问关键项。

项目 `AGENTS.md` 已指向 `skills/short-drama-adapt-localize/SKILL.md`。该目录是一套正常结构、未禁用隐式调用的可安装 skill 包；当前环境拦截 `.agents` 写入，因此本次没有安装进自动发现目录，也没有全局安装。直接按项目路由即可使用，不依赖用户会安装插件。

## 实现了什么

1. 九阶段规则：全读→约束→关系/资产联合本土化→逐场事实→英语精修→锁前预检→锁稿分镜→双层验收→完整导出。
2. 输入提取：UTF-8 TXT/MD、DOCX正文与表格顺序；复杂内容主动标明未覆盖。提取后仍标未读，助手不能用“脚本提取成功”冒充阅读。
3. 检查：覆盖范围、ID和引用、每段/镜头≤15秒、总长、话音逐字/角色/渠道/顺序、跨段切片、显式停顿/重叠、事件动作阶段、造型版本、前后状态、过期审读。
4. 续作与返修：状态JSON、依赖哈希、定点审读记录；真实上游变化让受影响旧检查失效，不自动重写其他场。
5. 同一结构导出TXT/DOCX，回读正文一致；目录存在即拒绝覆盖。缺DOCX依赖只交TXT并说明，绝不伪造后缀。

内容改编、文化合理性、英文自然度、物理动作和摄影表达由助手实际审读；脚本不会自动完成创作，也不能证明锁定的稿子本身就正确。并不提供版权安全保证。

## 关键位置

- `skills/short-drama-adapt-localize/SKILL.md`：主入口与阶段路由。
- `skills/short-drama-adapt-localize/references/`：修改边界、地区资产、语言、镜头、验收与数据契约。
- `skills/short-drama-adapt-localize/scripts/`：可运行的读取/检查/导出/版本脚本。
- `examples/three-scenes/source.txt`：原创3场原稿。
- `examples/three-scenes/run-v2/project.json`：当前完整小样状态（revision=3）。
- `examples/three-scenes/deliverable-v2/完整视频提示词.txt`：完整6段成品文字。
- `examples/three-scenes/deliverable-v2/完整视频提示词.docx`：回读一致的DOCX，页面视觉QA尚未做。
- `examples/three-scenes/READING_REVIEW.md`：具体语义/物理/镜头审读及初稿修复。
- `qa/TEST_REPORT.md`：实测命令、结果与限制。

`run-v1`保留了较早的小样状态，已有I2/I3语义问题，不能当最新稿。`initial-draft.json`含故意注入的语义反例，用于说明程序能力边界。

## 命令行辅助（不是自动改编器）

在项目目录运行，python应替换为当前环境已允许的解释器，不自动安装依赖：

```text
python transdrama.py init 原稿.docx --out work/作品-r1 --title 作品名 --locale en-US --region 美国俄勒冈州虚构小镇 --era 1998 --episodes 1,2,3
python transdrama.py check work/作品-r1/project.json --report work/作品-r1/check-1.json
python transdrama.py export work/作品-r1/project.json --out outputs/作品-r1 --docx
python transdrama.py revise 旧状态.json 拟定新状态.json --out 新状态-失效标记.json
```

init只建立来源和草稿骨架，之后必须由助手阅读、改编、审读并填写状态。需要知道JSON字段时读 `references/data-contract.md`；不能只运行init后直接导出。

导出有待核问题时默认拒绝；`--allow-review-draft`可明确交付待核版，确定结构错误仍不导出。检查退出码0=当前文字检查记录齐全；3=待核；1=错误。未测音视频不会转成已测。

本环境已测试解释器：

```powershell
$dramaPython = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $dramaPython -m unittest discover -s tests -v
& $dramaPython transdrama.py check examples/three-scenes/run-v2/project.json
```

便携迁移时换成本机授权的Python；程序里没有硬编码此路径。标准库即可检查/导出TXT，DOCX另需已有python-docx。自测使用原创材料，结果留在 `qa/test-fixtures`，不改历史剧本。

## 已知边界

- 没有用户历史31集作品实测、英语母语盲评、视频读取/生成、音频核听/TTS或口型测试；4K只是提示目标。
- 程序不理解“最后/可能/明天才能”等中文语义；语义审读记录只是可追踪记录，不是自动正确性证书。
- 官方 skill 格式检查器已尝试运行，但其PyYAML依赖不在当前运行时；自带基础格式/引用检查通过，不等同官方验证。
- DOCX已生成并回读一致，但运行时无内置LibreOffice，未做页面渲染/视觉QA，也未使用用户桌面LibreOffice代替。
- 当前只做文字产线，不包含网站界面、账户系统、队列服务、外部API或遥测。
- 原有文件未覆盖；只添加本项目实现和原创测试数据。安装、联网、音视频制作或处理历史整剧需要另行明确请求。
