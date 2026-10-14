"""Conservative TXT/MD/DOCX text reader; never executes material instructions."""
import hashlib
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from drama_core import ContractError

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract_source(path, source_id="SRC1"):
    path = Path(path)
    if path.stat().st_size > 40_000_000:
        raise ContractError("Source exceeds 40 MB safety limit; split explicitly")
    raw = path.read_bytes()
    limitations, blocks = [], []
    def add(text, locator):
        if text.strip():
            blocks.append({"id": f"{source_id}:B{len(blocks)+1}", "locator": locator,
                           "text": text, "read": False, "kind": "other"})
    if path.suffix.lower() in (".txt", ".md"):
        for line, text in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
            add(text, f"line:{line}")
    elif path.suffix.lower() == ".docx":
        with zipfile.ZipFile(path) as archive:
            if sum(x.file_size for x in archive.infolist()) > 80_000_000:
                raise ContractError("Expanded DOCX exceeds 80 MB safety limit")
            root = ET.fromstring(archive.read("word/document.xml"))
            flags = {"txbxContent": "文本框", "drawing": "图片/绘图及其文字", "pict": "旧式图片",
                     "ins": "修订插入", "del": "修订删除", "altChunk": "嵌入内容", "fldChar": "动态域"}
            for tag, description in flags.items():
                if root.find(".//" + W + tag) is not None:
                    limitations.append("未完整解释：" + description)
            if root.find(".//{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath") is not None:
                limitations.append("未读取：公式文字")
            for part, description in (("footnotes", "脚注"), ("endnotes", "尾注"), ("comments", "批注")):
                if f"word/{part}.xml" in archive.namelist():
                    limitations.append("未读取：" + description)
            if any(x.startswith(("word/header", "word/footer")) and x.endswith(".xml") for x in archive.namelist()):
                limitations.append("未读取页眉页脚；请确认是否包含剧情正文")
            body = root.find(W + "body")
            if body is None:
                raise ContractError("DOCX has no main body")
            def walk(node, prefix):
                for i, child in enumerate(node, 1):
                    locator = f"{prefix}/{child.tag.split('}')[-1]}:{i}"
                    if child.tag == W + "p":
                        # Textboxes are deliberately excluded, with an explicit partial status.
                        chunks = []
                        def inline(element):
                            if element.tag == W + "txbxContent":
                                return
                            if element.tag == W + "t":
                                chunks.append(element.text or "")
                            elif element.tag == W + "tab":
                                chunks.append("\t")
                            elif element.tag == W + "br":
                                chunks.append("\n")
                            else:
                                for descendant in element:
                                    inline(descendant)
                        inline(child)
                        add("".join(chunks), locator)
                    elif child.tag in (W+"tbl", W+"tr", W+"tc", W+"sdt", W+"sdtContent"):
                        walk(child, locator)
                    elif child.tag not in {W + tag for tag in ("sectPr", "tblPr", "tblGrid", "trPr", "tcPr", "sdtPr", "bookmarkStart", "bookmarkEnd")}:
                        limitations.append("未遍历的正文结构：" + locator)
            walk(body, "body")
            limitations = list(dict.fromkeys(limitations))
    else:
        raise ContractError("Only UTF-8 TXT/MD and DOCX are supported; video/audio/image reading is not implemented")
    if not blocks:
        raise ContractError("No readable text; cannot declare full reading")
    return {"id": source_id, "name": path.name, "sha256": hashlib.sha256(raw).hexdigest(),
            "extraction_status": "partial" if limitations else "complete", "reading_status": "unread",
            "limitations": limitations, "blocks": blocks}
