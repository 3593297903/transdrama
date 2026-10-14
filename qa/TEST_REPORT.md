# B 工作流实施与实测报告

日期：2026-10-10。项目：E:\transdrama。测试使用当前 Codex 内置 Python 3.12.14 与已有 python-docx；未安装新依赖、未调用外部模型、未上传私稿。

## 验收范围

实现 skill 入口、6份阶段/数据参考、项目级AGENTS路由、便利命令入口、来源读取、初始化、结构检查、修订依赖失效、TXT/DOCX同源导出；另外实现原创3场完整小样、初稿反例和逐项单元/CLI测试。

当前成品小样：run-v2/project.json（revision=3）、deliverable-v2中的完整TXT和DOCX。共1集3场、6段、12个镜头片段（其中两片属同一长镜，实际规划11镜）、8条锁定话音、9个播放片段；1条旁白、1条画外对白、6条普通对白。计划62秒，最长段13秒，最长单片镜头9秒。不是音视频测量结果。

## 已实际运行

解释器：`C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`。

```text
python -m unittest discover -s tests -v
python qa/run_checks.py --out qa/verification-v2
python transdrama.py check examples/three-scenes/run-v2/project.json
python transdrama.py export examples/three-scenes/run-v2/project.json --out examples/three-scenes/deliverable-v2 --docx
python transdrama.py init examples/three-scenes/source.txt --out examples/three-scenes/import-checkpoint --title ImportCheck --locale en-GB --region Fictional-England --era 1998 --episodes 1
```

verification-v2记录59项测试全部通过，0错误/0失败/0跳过；随后代码统计与正文空值保护的最终复跑记录见verification-final（同样保留实际日志）。测试返回码、运行时间与测试名以日志为准，不凭手工写的“通过”代替。

覆盖：合法跨镜/跨段、连续长镜、旁白有则保留/无则不添、画外对白、逐字漏词/重播/串人/错渠道、字符与时间断点、已声明停顿和重叠、精确15秒/15.01秒、总长硬约束与参考时长区别、镜头空缺、缺集缺场、源覆盖、未知ID、重复ID、造型/话音旧版本、动态状态与资产身份、状态断裂、过期审读、独立场不受无关变化影响、旧→新句数可变化、修订CLI拒绝覆盖、源读入后未读状态、DOCX表格顺序与部分内容限制、恢复状态、TXT/DOCX真实回读、缺依赖降级、导出错误、审稿版显式开关、检查CLI 0/3/1退出码。

正常成品导出结果：TXT created_and_read_back；DOCX created_and_read_back；docx_visual_qa=not_performed_by_exporter。导出目录已存在会失败，不悄悄覆盖。源导入得到15块，保持unread，不假称模型已读。

## 内容小样与修订证据

完整记录见examples/three-scenes/READING_REVIEW.md。当前助手自行写作与自审，没有独立评委。初稿V7的“明日修好”是故意注入的反例，用于证明字节检查不能验证锁定稿中文含义；不伪称项目自动理解并发现它。

实际二轮内容复核修复两处：第一场知识表提前带入第二场Owen推测；新关系的put me in charge台词不够明确，改为hired me。保留run-v1旧状态，不当最新成品。确认唯一钥匙流转、右手伤、木闩与锁的区别、纸本缺页、最后来访者的推测、明日才能核查等没有被英语精修改坏。

## 环境问题与未完成的验证

1. 初次56项测试有12项文件测试因Windows临时目录owner-only ACL在沙箱下拒绝访问而报错；改到项目内仍遇同一ACL问题。没有更改系统ACL或越权读写，最终改为创建普通继承权限的项目内独立测试目录并保留测试材料，之后通过。早期创建的空临时目录未执行强制清理；不包含用户作品。
2. `.agents`项目发现目录写入即使单独请求授权仍失败。已改为普通`skills`包并由项目AGENTS引用；不把它说成自动发现或全局安装。空的首次尝试目录没有当作有效skill。
3. 实际执行官方quick_validate.py失败：ModuleNotFoundError: No module named 'yaml'。没有自动装PyYAML。自带基础frontmatter/引用路径/占位检查通过，但不是官方完整验证。
4. 当前运行时没有内置LibreOffice；文档技能禁止调用用户桌面LibreOffice替代，所以未进行页面渲染与视觉QA。没有伪造“渲染通过”。DOCX仅内容回读验收，版面仍需之后检查。
5. 未进行历史31集长稿实测、母语盲评、TTS朗读时长、口型、视频生成、图像一致性或4K成片检查；这些不属于本轮文字实现。

## 安全与剩余边界

没有覆盖用户原文件，没有修改Desktop提示词，没有读取密钥或自动安装66个项目。代码为本项目自行实现，参考已有B方案方法，不复制第三方仓库代码。生产脚本无网络/模型调用、遥测和后台服务；XML命名空间URL只是格式标识，不会发起请求。

结构通过只证明本数据契约中的机器条件及审读记录当前，不能证明审读结论绝对正确。英语地道度、改编幅度、文化/物理语义和版权需要相应人工判断；本项目不签发“不侵权”或用户批准结论。
