# 审读、修复、发布前验收与恢复

结构程序检查字段/类型、引用、数字、文本、版本与记录依赖；无法证明原稿意思正确、英语自然或可拍。四项独立报告：structure_coverage、ai_story_language、target_language、media。当前成功文本状态仍为ready_for_text_delivery，不代表真人终审/成片/发布完成。

schema 2 必需实际审读类别：adaptation、english_fidelity、english_viewing、feasibility、visual_storytelling、full_read。review_record在真实阅读之后保存work_id/scope/evidence/kind/result/snapshots，scope可以分批覆盖，具体审读须读完整相应场景。测试记录kind=test仅限test_fixture，不转成生产/真人证明。缺字段、未执行、failed、needs_review、stale、checked区分；异常不能回退空错误通过。

问题有场景/话音/片段、分类与证据、严重性置信度、允许层、attempts、root_issue_id、status与resolution。confirmed重大问题需要明确高置信证据；偏好/语境疑问不冒充重大确定错误，重大未决不被总分抵消。修复最多两次，关联ID与同定位预算累计；耗尽是待核。resolved/writer_decided/user_confirmed须当前整场recheck；writer_decided不能关掉确认重大错误，user_confirmed须真实确认来源，不等于语言认证。

上游改动先保存新版本，seal正确父版本，用revise做身份/当前头/依赖守卫。coverage目标、理由、授权改变使改编审读失效；英语绑定整场上下轮、事件、人物/叙述身份与必要前情。日志、progress、全局revision不进入语义快照，不能因为修订号增长无差别废掉无关检查。规则、来源、真实内容变化分别可追溯。

双重对照：原稿/授权→新事实；锁稿→成品。全范围终读可分批，但不能用摘要、首尾集或10%代替。原稿整部已提供时先全剧定稿后分批制作。角色、称呼、承诺、伤势/持物/证据、时间、知情和叙述身份跨集核对。

无人审仍可完整交付AI文字包，明确未做真实目标语终审/待终审。正式发布建议具有美国英语影视经验的真实审者对实际发布全范围终读。真人记录仅真实发生后登记reviewer_source/qualification/date/scope/作品版本/结论与证据快照；程序不能证明审者能力。人审改词回核批准意思；不自动外发/采购。

媒体验收需真实实听实看并记录实际文件哈希与测过的dimensions；不把文字估时当音频实测，不把提示分辨率当4K成片。未测口音、重音、声线、字幕、口型、连续性逐项未测。无媒体记录时not_performed；JSON记录只是有来源的验收声明。

导出先check：结构错误拒绝，待核只用--allow-review-draft明示审稿版。临时产物全部回读后发布目录，最后package.json作为完整包标志，包含作品/内容版本与产物哈希。失败留诊断，无有效完整标志；不覆盖旧有效包，不递归清理目录。--resume只验证复用相同内容/版本完整包，或保留并重试同作品同指纹失败/中断包；损坏完整包不静默重建，改用新目录。

恢复：读取head.json指向的当前状态、完整来源块、未决、最后实际完成场次和版本，用check --recovery导航，再打开相应完整上下轮。handoff只记录作品/内容指纹、范围、上游、已完成/未决/下一步；进度/摘要不能制造通过。每剧独立work目录与当前头，多部清单由助手逐部执行；没有后台队列、定时生产或跨剧共用人物记忆。
