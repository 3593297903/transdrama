"""Reproducible ORIGINAL fixture. Review notes are explicit, not an auto-review service."""
import argparse
import copy
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills/short-drama-adapt-localize/scripts"))
from drama_core import save_new, review_record, validate
from source_io import extract_source


def build():
    source = extract_source(Path(__file__).with_name("source.txt"))
    kinds = ["heading", "action", "narration", "dialogue", "offscreen", "action",
             "action", "dialogue", "dialogue", "dialogue", "action", "action", "dialogue", "dialogue", "action"]
    for block, kind in zip(source["blocks"], kinds):
        block.update(read=True, kind=kind)
    source["reading_status"] = "complete"
    doc = {"schema_version": 1, "project": {"id": "old-pump-house", "title": "旧泵房｜原创三场英语改编小样",
        "revision": 3, "locale": "en-GB", "region": "虚构英格兰北部乡村维修小院", "era": "1998年",
        "scope_summary": "完整第1集，场1—3；保留查门、查登记簿、明日再查的主线；母女改为主管与受雇维修助理。",
        "episodes": [1], "expected_scene_ids": ["S1", "S2", "S3"], "episode_duration": {"1": {"kind": "planned", "seconds": 62,
        "basis": "原创源稿文字规划62秒；非视频/音频测量"}}, "status": "locked", "audio_status": "not_measured", "video_status": "not_generated"},
        "sources": [source], "entities": [], "scenes": [], "events": [], "voices": [], "segments": [], "coverage": [], "reviews": [], "issues": []}
    def entity(eid, kind, old, name, description, **extra):
        doc["entities"].append({"id": eid, "kind": kind, "original_name": old, "name": name, "fictional": True,
                                "version": 1, "description": description, **extra})
    entity("C1", "character", "青禾", "Nora Vale", "28岁维修助理，宽额圆下颌、深棕短卷发、浓直眉，旧橄榄色棉工装外套配炭灰长裤，帆布工具袋；右手缠浅色绷带，全程只用左手操作。",
           relationship="Mara新雇的维修助理，不是女儿；受托照看维修小院，有检查检修门的职责。",
           voice_profile="对主管直说事实但不越权；不确定就明确说还要查，不装作已修好。",
           variants=[{"id": "workwear", "description": "工装保持不变；绷带在右手。"}])
    entity("C2", "character", "素娘", "Mara Ellis", "46岁小院维修主管，长方脸、灰绿眼、栗色齐颈直发，暗红细格衬衫、深棕绒面背心、旧皮靴；衣袖挽至前臂。",
           relationship="Nora的直接主管，有交付钥匙和安排次日核查的权限，不是母亲。",
           voice_profile="务实简短；关心伤手是同事安全提醒，不说教。")
    entity("C3", "character", "老周", "Owen Reed", "未出场的前次维修人员；仅被提及，不生成面孔或追加行为。")
    entity("L1", "location", "旧泵房", "旧泵棚", "褪色砖墙、窄木门、门边木架、墙上登记簿挂钩；两人可并肩站立。门锁与门后木闩互相独立，木闩卡住门。无电子门禁。")
    entity("P1", "prop", "钥匙", "黄铜钥匙", "唯一一把旧黄铜机械钥匙，只能开锁，不能解除门后木闩。")
    entity("P2", "prop", "登记簿", "维修登记簿", "一本绿布封皮纸质维修登记簿，缺一页，书脊旁残留纸茬；缺页内容未知，不出现被撕的画面或新证据。")
    states = [
      ({"key": "Nora左手", "door": "锁闭且木闩卡住", "book": "墙上挂钩", "right_hand": "受伤不用", "last_visitor": "未知"},
       {"key": "锁孔中", "door": "锁已开但木闩卡住", "book": "墙上挂钩", "right_hand": "受伤不用", "last_visitor": "未知"}),
      ({"key": "锁孔中", "door": "锁已开但木闩卡住", "book": "墙上挂钩", "right_hand": "受伤不用", "last_visitor": "未知"},
       {"key": "Nora口袋", "door": "锁已开但木闩卡住", "book": "木架上摊开缺一页", "right_hand": "受伤不用", "last_visitor": "可能Owen未确认"}),
      ({"key": "Nora口袋", "door": "锁已开但木闩卡住", "book": "木架上摊开缺一页", "right_hand": "受伤不用", "last_visitor": "可能Owen未确认"},
       {"key": "Nora口袋", "door": "锁已开但木闩卡住", "book": "木架上摊开缺一页", "right_hand": "受伤不用", "last_visitor": "可能Owen未确认"})]
    for i, (entry, leave) in enumerate(states, 1):
        scene = {"id": f"S{i}", "episode": 1, "order": i, "title": ["检查木门", "翻查登记簿", "约定明日再查"][i-1],
            "goal": ["确认门能否打开", "确认最后来过的人", "确定核查时间"][i-1],
            "change": ["锁打开但门仍卡住", "发现缺页，来访人仍只是猜测", "明日继续核查，不承诺修复"][i-1],
            "audience_information": ["主管已把钥匙交给助理；右手伤未愈", "看见缺页，但不知道内容与原因", "知道只能明日查清，并非保证修好"][i-1],
            "preflight": "文字规划：留表演停顿；只用左手操作；钥匙与登记簿流转分别安排，不把全部动作强行同时做。未测音频。",
            "entity_ids": ["C1", "C2", "C3", "L1", "P1", "P2"], "entry_state": entry, "exit_state": leave,
            "knowledge": ({"entry": {"Nora": "已有钥匙，尚未试门", "Mara": "已委派Nora照看小院", "观众": "待旁白交代停水与钥匙"},
                           "exit": {"两人": "试门得知木闩卡住；尚未讨论最后来访者", "观众": "看到卡住的木闩；尚未看到缺页"}}
                          if i == 1 else {"entry": {"两人": "门卡住，尚未确认最后来访者", "观众": "仅知道之前已播放事实"},
                           "exit": {"两人": "Owen只是可能来访者，缺页内容未知", "观众": "看过缺页，但没有看到内容或撕页者"}})}
        if i > 1:
            scene["previous_scene_id"] = f"S{i-1}"
        doc["scenes"].append(scene)
    event_specs = [("E1", "S1", "Nora左手开锁，发现门被木闩卡住后停手", ["持钥匙就位", "插入转锁", "门受阻停手"]),
                   ("E2", "S2", "Mara取簿打开指缺页；Nora左手取钥匙入袋", ["取下打开簿", "指示缺页", "收回钥匙"]),
                   ("E3", "S3", "约定明日再查后离开，登记簿留在架上", ["约定时间保持现状", "松开簿并离开"])]
    for eid, scene, description, phases in event_specs:
        doc["events"].append({"id": eid, "scene_id": scene, "description": description, "phases": phases})
    voice_specs = [
      ("V1", "S1", "narration", None, 3, "The water had been off for three days. Nora already had Mara's key.", "停水三天；钥匙已经由Mara交给Nora。", "交代背景与已持钥匙"),
      ("V2", "S1", "dialogue", "C1", 4, "You hired me to look after this place, Mara. Let me check the door.", "Mara雇我照看这里，我先检查门。", "呈现新雇佣职责并请求检查"),
      ("V3", "S1", "offscreen", "C2", 5, "Not with your right hand. It hasn't healed yet.", "不要用右手，伤还没好。", "提醒同事保护伤手"),
      ("V4", "S2", "dialogue", "C2", 8, "Who was the last person here?", "谁最后来过这里？", "询问最后来访者"),
      ("V5", "S2", "dialogue", "C1", 9, "It might've been Owen. I still need to check.", "可能是Owen，我还得查。", "谨慎回答而非确认"),
      ("V6", "S2", "dialogue", "C2", 10, "There's a page missing here.", "这里少了一页。", "指出可见缺页"),
      ("V7", "S3", "dialogue", "C1", 13, "I can't find out until tomorrow.", "明天才能查清。", "限定最早核查时间，不保证修好"),
      ("V8", "S3", "dialogue", "C2", 14, "Then we'll come back tomorrow. Leave the book here for now.", "明天再来，簿子暂时放这儿。", "安排下次核查与簿子留置")]
    for i, (vid, scene, channel, speaker, line, text, meaning, intent) in enumerate(voice_specs, 1):
        doc["voices"].append({"id": vid, "scene_id": scene, "order": i, "channel": channel,
            "speaker_id": speaker, "addressee_ids": ([] if speaker is None else ["C2" if speaker == "C1" else "C1"]),
            "text": text, "meaning": meaning, "intent": intent, "version": 2 if vid in ("V7", "V2") else 1, "source_ids": [f"SRC1:B{line}"]})
    voices = {x["id"]: x for x in doc["voices"]}
    def segment(sid, scene, start, duration, key_state, book_state, end):
        refs = [{"id": aid, "version": 1, "state": state} for aid, state in
                [("C1", "门左侧，右手伤不参与动作"), ("C2", "门右侧"), ("L1", "门内木闩仍卡住，出口和挂钩位置不变"),
                 ("P1", key_state), ("P2", book_state)]]
        refs[0]["variant_id"] = "workwear"
        seg = {"id": sid, "scene_id": scene, "episode": 1, "start": start, "duration": duration,
            "asset_refs": refs, "setting": "两人在窄门外，木架在Mara身侧；不进入泵棚，不揭示门后其他空间。",
            "sound": "小院风声、衣料轻响和同期动作声；不加音乐催情；声音轨严格按下列区间，只播放一次。",
            "atmosphere": "写实柔和阴天散射光，旧砖与木纹有自然磨损，亮度跨段一致。", "end_state": end,
            "shots": [], "audio": []}
        doc["segments"].append(seg)
        return seg
    def shot(seg, shid, a, b, framing, composition, action, eid, phases, continuous=None, previous=None):
        item = {"id": shid, "start": a, "end": b, "framing": framing, "camera": "门外平视，不越过人物视线轴",
                "composition": composition, "movement": "固定机位，动作在画框内完成", "action": action,
                "event_refs": [{"event_id": eid, "phases": phases}] if phases else []}
        if continuous:
            item["continuous_take_id"] = continuous
        if previous:
            item["continues_shot_id"] = previous
        seg["shots"].append(item)
    def audio(seg, vid, a, b, left=0, right=None):
        voice = voices[vid]
        right = len(voice["text"]) if right is None else right
        seg["audio"].append({"id": f"{seg['id']}-{vid}-{left}", "voice_id": vid, "voice_version": voice["version"],
            "speaker_id": voice["speaker_id"], "channel": voice["channel"], "start": a, "end": b,
            "char_start": left, "char_end": right, "text": voice["text"][left:right]})
    g1 = segment("G1", "S1", 0, 12, "Nora左手持有，尚未插锁", "墙上挂钩", "两人到门前；Nora话音持续到下一段，钥匙仍在左手。")
    shot(g1, "SH1", 0, 5, "双人中景", "门居中；左侧Nora左手钥匙可见，右手绷带不遮挡", "Nora持钥匙站定，Mara在右侧停下；不是来寻找钥匙。", "E1", ["持钥匙就位"])
    shot(g1, "SH2", 5, 12, "Nora中近景", "Nora面朝右侧Mara，左手钥匙仍在腰前", "Nora抬眼与主管交流，保持持钥匙状态，没有开始开门。", "E1", [], "TAKE1")
    split = voices["V2"]["text"].index("Let")
    audio(g1, "V1", 0, 5)
    audio(g1, "V2", 5, 12, 0, split)
    g2 = segment("G2", "S1", 12, 8, "先在左手，随后入锁", "墙上挂钩", "门锁已开但木闩卡住；钥匙留在锁孔；右手未用力。")
    shot(g2, "SH3", 0, 2, "Nora中近景", "继承SH2相同构图及眼线", "连续接续Nora发言，左手钥匙位置保持，不重复上一段动作。", "E1", [], "TAKE1", "SH2")
    shot(g2, "SH4", 2, 6, "左手与锁孔近景", "左手钥匙和锁孔居中；右手不入操作区域", "Nora左手将唯一钥匙插入锁孔并转开门锁；Mara仍在画外原位。", "E1", ["插入转锁"])
    shot(g2, "SH5", 6, 8, "门缝细节近景", "门缝与卡住的木闩同框，位置清楚但不穿越门板", "门只松开一点便碰到木闩；Nora停下，钥匙留在锁里。", "E1", ["门受阻停手"])
    audio(g2, "V2", 0, 2, split)
    audio(g2, "V3", 2, 7)
    g3 = segment("G3", "S2", 20, 9, "锁孔中", "由挂钩取下，随后打开", "Mara已打开簿子；Owen只是可能来访者，尚未确认。")
    shot(g3, "SH6", 0, 9, "双人中景", "Mara及挂钩在右，Nora在左；木架在下方可见", "Mara取下登记簿，边与Nora交流边在木架上打开；不提前指认缺页。", "E2", ["取下打开簿"])
    audio(g3, "V4", 0, 3)
    audio(g3, "V5", 3, 8)
    g4 = segment("G4", "S2", 29, 13, "先在锁孔，后入Nora口袋", "木架上摊开，由Mara扶住", "登记簿缺一页；钥匙已在Nora口袋；门仍卡住。")
    shot(g4, "SH7", 0, 5, "登记簿特写", "木架承托簿子；Mara手指与书脊纸茬可见", "Mara指向缺页纸茬，不显示缺失内容或另一个人的撕页动作。", "E2", ["指示缺页"])
    shot(g4, "SH8", 5, 10, "Nora腰部与门锁近景", "只让左手、锁孔、口袋构成清楚动作路径", "Nora左手把钥匙从锁孔取出，放入工装口袋。", "E2", ["收回钥匙"])
    shot(g4, "SH9", 10, 13, "双人中景", "两人面向木架，簿子仍摊开，Mara扶着簿沿", "保持刚完成的状态，两人短暂停顿；不新增交换眼神暗示或新线索。", "E2", [])
    audio(g4, "V6", 1, 4)
    g5 = segment("G5", "S3", 42, 8, "Nora口袋", "摊在木架上，Mara仍扶着", "只能明日查清；双方没有声称知道来访人或修好时间。")
    shot(g5, "SH10", 0, 8, "Nora与Mara双人近景", "Nora左、Mara右，木架与簿沿保留在下方", "Nora说明核查时间，Mara听完；右手保持松弛，没有操作道具。", "E3", ["约定时间保持现状"])
    audio(g5, "V7", 0, 4)
    g6 = segment("G6", "S3", 50, 12, "Nora口袋", "留在木架上摊开", "两人已离开门前；门仍被木闩卡住；登记簿留架，明日再查。")
    shot(g6, "SH11", 0, 6, "Mara中近景", "Mara面向Nora，簿子和扶簿手在框内", "Mara回应并保持簿子不动，不增加任何保证。", "E3", [])
    shot(g6, "SH12", 6, 12, "门外双人中景", "门、木架和退离路线同框，不切去未出现的人", "Mara松开簿沿，两人从门前离开；簿子留在木架上，门维持原状。", "E3", ["松开簿并离开"])
    audio(g6, "V8", 0, 6)
    target_map = {1:["S1","S2","S3"],2:["S1"],3:["V1"],4:["V2"],5:["V3"],6:["E1"],7:["S2","E2"],
                  8:["V4"],9:["V5"],10:["V6"],11:["E2"],12:["S3"],13:["V7"],14:["V8"],15:["E3"]}
    doc["coverage"] = [{"source_id": f"SRC1:B{i}", "target_ids": targets,
        "reason": "保留事件/语义与渠道；母女责任改为主管委派，姓名、造型、场景本土化；不增加解决结果。"} for i, targets in target_map.items()]
    doc["issues"] = [{"id": "I1", "status": "resolved", "detail": "注入的初稿反例V7把明日才能查清改成明日肯定修好，越过信息与承诺边界。",
        "affected_ids": ["V7","G5"], "attempts": 1, "allowed_repair": "只修复V7意思和其声音片段，不改事件结局。",
        "resolution": "V7改为I can't find out until tomorrow.，版本2，更新G5音轨；重新查语义与声音覆盖。"},
        {"id":"I2", "status":"resolved", "detail":"run-v1场1知情记录提前包含第二场Owen推测。", "affected_ids":["S1"], "attempts":1,
         "resolution":"场1改为入/出场知识，Owen推测仅留第二场之后；复核全三场台词无提前泄密。"},
        {"id":"I3", "status":"resolved", "detail":"run-v1的put me in charge只表达委派，不能充分说明新的雇佣关系。", "affected_ids":["V2","G1","G2"], "attempts":1,
         "resolution":"改为You hired me to look after this place，在现有轮次中交代关系；V2版本2，更新两段字符范围及审读。"}]
    scopes = {"adaptation": ["PROJECT"] + [x["id"] for group in ("entities","scenes","events") for x in doc[group]],
              "english": [x["id"] for x in doc["voices"]], "feasibility": [x["id"] for x in doc["segments"]],
              "visual_storytelling": [x["id"] for x in doc["segments"]]}
    evidence = {
      "adaptation": "逐读原创15块：受雇委派替代母女照看，在V2呈现职责；钥匙原已持有，只有一把；右手不用；缺页内容不揭示；明日查而非修。见READING_REVIEW.md。",
      "english": "逐核V1—V8和源义：V4保留last，V5保留might与need to check，V7恢复until tomorrow；无新增旁白。单模型自审，非母语盲评。",
      "feasibility": "G1—G6合计62秒；语音规划非测量。V2跨段字符连续；V3跨SH4/5但仍画外对白。开锁、取簿、收钥匙各有独立时间。",
      "visual_storytelling": "12片段逐读：钥匙、木闩、纸茬各有可见画面；SH2/3为同一长镜接续，非重复动作；无新增线索。未生成视频。"}
    doc["reviews"] = [review_record(doc, f"R{i}", category, scope, "当前助手单模型文字自审", evidence[category])
                      for i, (category, scope) in enumerate(scopes.items(), 1)]
    return doc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="New directory only")
    args = parser.parse_args()
    out = Path(args.out)
    if out.exists():
        parser.error("Output directory already exists; originals will not be overwritten")
    final = build()
    draft = copy.deepcopy(final)
    draft["project"]["revision"], draft["project"]["status"] = 1, "draft"
    draft["voices"][6].update(text="I'll have it fixed by tomorrow.", meaning="明天一定修好。", version=1)
    draft["reviews"] = []
    draft["issues"][0].update(status="open")
    draft["issues"][0].pop("resolution")
    # Keep initial voice/production consistency, so the defect is genuinely semantic.
    clip = draft["segments"][4]["audio"][0]
    clip.update(text=draft["voices"][6]["text"], char_end=len(draft["voices"][6]["text"]), voice_version=1)
    out.mkdir(parents=True)
    save_new(out / "initial-draft.json", draft)
    save_new(out / "project.json", final)
    save_new(out / "check.json", validate(final))
    print(out)


if __name__ == "__main__":
    main()
