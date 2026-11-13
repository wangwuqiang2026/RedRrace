"""语料解析与定位（阶段一步骤 3）。

产出三类结构：`Locator`（定位）、`Block`（文本块 + 定位）、`ParsedDoc`（某来源的全部块）。

定位口径（plan 全局约束 2、阶段一「接口约定」）：
- 电子书类（PDF / EPUB）→ 页码或章节序号写进 `Locator.page`；
- 文章类（HTML）与分段类（TXT / DOCX）→ 段落号写进 `Locator.paragraph`，
  标题层级写进 `heading_path`，HTML 额外保留 `url_anchor`；
- 每个块的 `quote` 等于块文本本身——逐字引文的最低要求是「块内可原样命中」。

**关于「按 media_type 分支」的实现选择**：简报写的是按 `record.media_type` 分支，本模块实际
按**文件扩展名**选解析器（`media_type` 只决定定位侧重与展示排版）。原因是载体类型只有
「电子书 / 文章」两个值，而解析器有五种，且电子书完全可能以 HTML 快照或 TXT 形式落地；
若强行让两者必须匹配，会误拒这类合法采集形态，而代码也没有别的依据去核对自报的 `media_type`。

任何块拿不到定位、整份文件解析不出可定位的块、文件不存在或是目录、扩展名不支持，
一律抛 `ValueError`，绝不静默产出无定位块——无定位的块一旦入库，阶段三的逐字引文校验
与阶段七的审核台都无从下手。
"""

from __future__ import annotations

import importlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_config
from app.ingestion.registry import SourceRecord
from app.qa.schemas import Locator

__all__ = ["Block", "Locator", "ParsedDoc", "parse_document", "save_parsed"]

# 章标题识别：`第一章 …` 与 markdown 式 `# …`，两者都要求整段只有一行
_CHAPTER_RE = re.compile(r"^第[0-9零〇一二三四五六七八九十百千]+[章篇部卷]\s*\S*")
_MARKDOWN_H_RE = re.compile(r"^#{1,6}\s+\S")


@dataclass
class Block:
    """一个文本块及其定位。"""

    text: str
    locator: Locator


@dataclass
class ParsedDoc:
    """某来源单位的解析结果。`full_text` 由块文本拼接，是逐字引文校验的比对底本。"""

    source_id: str
    blocks: list[Block]

    @property
    def full_text(self) -> str:
        return "\n".join(b.text for b in self.blocks)


def _clean(text: str) -> str:
    """压掉多余空白行与首尾空白，但**不改动字符本身**——引文要能逐字命中。"""
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _require(module: str, hint: str, why: str):
    """导入解析依赖；缺失时给出该装什么的明确提示，不吞异常。"""
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise ImportError(f"解析{why}需要依赖 {module}，请先安装：{hint}") from exc


def _ensure_readable(path: Path) -> None:
    if path.is_dir():
        raise ValueError(f"解析目标不是文件，是个目录：{path}")
    if not path.is_file():
        raise ValueError(f"解析目标文件不存在：{path}")


def _block(text: str, **locator_kwargs) -> Block:
    quote = text
    return Block(text=text, locator=Locator(quote=quote, **locator_kwargs))


# ── PDF：按页取文，页码写定位 ────────────────────────────────────────────────────────
def _parse_pdf(path: Path) -> list[Block]:
    pypdf = _require("pypdf", "pip install pypdf", " PDF 语料")
    reader = pypdf.PdfReader(str(path))
    blocks: list[Block] = []
    for page_no, page in enumerate(reader.pages, start=1):
        text = _clean(page.extract_text() or "")
        if not text:
            continue  # 空白页跳过；若整份都无内容，由 parse_document 统一报错
        blocks.append(_block(text, page=page_no, heading_path=[f"第 {page_no} 页"]))
    return blocks


# ── TXT：空行分段，章标题只作标题路径不单独成块 ────────────────────────────────────────
def _is_standalone_heading(paragraph: str) -> bool:
    if "\n" in paragraph:
        return False
    return bool(_CHAPTER_RE.match(paragraph) or _MARKDOWN_H_RE.match(paragraph))


def _parse_txt(path: Path) -> list[Block]:
    raw = path.read_text(encoding="utf-8-sig")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    blocks: list[Block] = []
    heading: list[str] = []
    for para in paragraphs:
        if _is_standalone_heading(para):
            heading = [para]
            continue
        blocks.append(_block(para, paragraph=len(blocks) + 1, heading_path=list(heading)))
    return blocks


# ── DOCX：按段取文，Heading 样式进标题路径 ────────────────────────────────────────────
def _parse_docx(path: Path) -> list[Block]:
    docx = _require("docx", "pip install python-docx", " Word 语料")
    document = docx.Document(str(path))
    blocks: list[Block] = []
    stack: list[tuple[int, str]] = []
    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = str(getattr(para.style, "name", "") or "")
        level = _docx_heading_level(style)
        if level is not None:
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text))
            continue
        blocks.append(
            _block(text, paragraph=len(blocks) + 1, heading_path=[t for _, t in stack])
        )
    return blocks


def _docx_heading_level(style_name: str) -> int | None:
    if style_name in ("Title",):
        return 1
    if style_name.startswith("Heading"):
        digits = "".join(ch for ch in style_name if ch.isdigit())
        return int(digits) if digits else 1
    return None


# ── HTML / EPUB：标题层级拼标题路径，段落号与锚点写定位 ────────────────────────────────
_CONTENT_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "pre"]
_HEADING_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6"]
_PROSE_TAGS = ("p", "li", "blockquote", "pre")

# 站点模板判据（审查 I8）。取值来自 171 篇真实快照的实测分布，不是拍脑袋：
# 模板导航项普遍是 4–5 字且整块几乎都是链接文字（占比 1.00），
# 而正文段落普遍 65–259 字、链接占比 0.00，两个维度分开得极干净。
# 刻意**不**按祖先 class/id 里的 header/menu/footer 关键字丢弃：
# 实测 S145（明嘉靖《长沙府志》）正文的祖先链里就有 div.i-main-header，
# 中国方志网的正文容器干脆叫 div.fzIndexBox——用命名黑名单会连真正文一起杀掉。
BOILERPLATE_SHORT_CHARS = 14
BOILERPLATE_LINK_RATIO = 0.5
LINK_RATIO_HARD = 0.85

# 不设「正文字数绝对下限」：171 篇真实快照按本模块清洗后最短 207 字（S160）、1% 分位 271 字，
# 「正文只剩几十个字」的空壳页在本批语料里并不存在；而「整页只有模板」的情形已被
# parse_document 的「未解析出任何带定位的文本块」守卫挡住，不需要再叠一层阈值。
# 若将来真的采到 JS 渲染的空壳页，再按当时实测分布引入下限，别把 200 这种数字写死在这里。


def _flat_text(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split())


def _link_ratio(el) -> float:
    """块内链接文字占可见文字的比例，用来识别菜单、侧栏列表、分页条。"""
    text = "".join(el.get_text(strip=True).split())
    if not text:
        return 1.0
    linked = sum(len("".join(a.get_text(strip=True).split())) for a in el.find_all("a"))
    return linked / len(text)


# 版式元信息判据（实测 171 篇残留的模板块全是这两类形态，与祖先命名无关）：
# ① 文末署名行「（责任编辑：×）」「（作者单位：×）」——同一编辑负责几十篇，
#    这类串就在几十篇里逐字相同，一旦被抽成事实条目就是假的交叉验证；
# ② 页脚版权/备案行「主办单位：…」「版权所有…」「×ICP备…号」。
_BYLINE_RE = re.compile(
    r"^[（(](责任编辑|校对|编辑|作者单位|记者|摄影|摄像)[：:][^）)]{1,30}[）)]$"
)
_FOOTER_RE = re.compile(
    r"^(主办单位|承办单位|协办单位|版权所有|网站标识码|备案号|地址[:：]|联系方式[:：])"
)
_ICP_RE = re.compile(r"ICP\s*[备证]?\s*\d{6,}")


def _is_boilerplate(el) -> bool:
    text = _flat_text(el)
    if not text:
        return True
    if _BYLINE_RE.match(text) or _FOOTER_RE.match(text) or _ICP_RE.search(text):
        return True
    ratio = _link_ratio(el)
    if ratio >= LINK_RATIO_HARD:
        return True
    return len(text) <= BOILERPLATE_SHORT_CHARS and ratio >= BOILERPLATE_LINK_RATIO


def _prose_run(node) -> tuple[int, int, int]:
    """返回 (最长连续正文块数, 正文块总数, 容器深度)，用于挑正文根。"""
    best = total = run = 0
    for el in node.find_all(_PROSE_TAGS):
        if el.find_parent(["script", "style"]) or el.find(_PROSE_TAGS):
            continue
        if _is_boilerplate(el):
            run = 0
            continue
        run += 1
        best = max(best, run)
        total += 1
    return best, total, len(list(node.parents))


def _content_root(soup):
    """挑正文容器：优先「连续正文块最多」的容器，并列时取更深的，避免抓到 body。

    先试语义标签（article/main），再用统计法——后者负责处理没有语义标签的老站点模板。
    """
    for tag in ("article", "main"):
        node = soup.find(tag)
        if node and _prose_run(node)[0] >= 2:
            return node
    candidates = [n for n in soup.find_all(["article", "main", "div", "section"]) if n.find(_PROSE_TAGS)]
    if not candidates:
        return soup.body or soup
    return max(candidates, key=_prose_run)


def _html_blocks(soup, base: list[str]) -> list[Block]:
    """遍历标题与正文标签，维护标题栈生成块。script/style 内的内容一律不进正文。

    两道去重（审查 I6，真实快照里 blockquote/嵌套段落常见）：
    ① 内层 `p`/`li` 若已被内容型祖先（`p`/`blockquote`/`li`/`pre`）覆盖，只出外层一块——
      否则同一句话拿到两个段落号，`full_text` 里还会出现重复文本，阶段三无法判定哪条是出处；
    ② 同一「标题路径 + 文本」只保留一次，防渲染脚本把正文复制进容器节点。
    """
    items: list[dict] = []
    seen: set[tuple[tuple[str, ...], str]] = set()
    stack: list[tuple[int, str]] = [(0, t) for t in base]
    for el in soup.find_all(_CONTENT_TAGS):
        if el.find_parent(["script", "style"]):
            continue
        text = _clean(el.get_text(" ", strip=True))
        if not text:
            continue
        if el.name in _HEADING_TAGS:
            level = int(el.name[1])
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text))
            continue
        if el.find_parent(["p", "blockquote", "li", "pre"]):
            continue  # 已被内容型祖先覆盖，不重复出块
        if el.name in ("p", "blockquote", "pre") and el.find(_HEADING_TAGS):
            continue  # 容器型段落（内嵌小标题）只让标题与内层文本出块
        key = (tuple(title for _, title in stack), text)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "text": text,
                "headings": [t for _, t in stack if t],
                "anchor": el.get("id"),
                "boilerplate": _is_boilerplate(el),
            }
        )

    blocks: list[Block] = []
    for item in items:
        if item["boilerplate"]:
            continue  # 站点模板项：导航、侧栏列表、分页条、署名行、页脚版权与备案号
        blocks.append(
            _block(
                item["text"],
                paragraph=len(blocks) + 1,
                heading_path=list(item["headings"]),
                url_anchor=item["anchor"],
            )
        )
    return blocks


def _parse_html(path: Path) -> list[Block]:
    bs4 = _require("bs4", "pip install beautifulsoup4", " 网页快照")
    soup = bs4.BeautifulSoup(path.read_text(encoding="utf-8-sig"), "html.parser")
    # 整页只剩模板时 blocks 为空，由 parse_document 的「未解析出任何带定位的文本块」守卫拒收；
    # 这里不再叠加字数阈值（依据与实测分布见上方注释）。
    return _html_blocks(_content_root(soup), base=[])


def _epub_spine_items(book) -> list:
    """按 spine 顺序取**正文**项，跳过导航与 NCX。

    `get_items_of_type(ITEM_DOCUMENT)` 会把 nav.xhtml 一起返回（审查 C1）：目录条目于是
    既占正文段号又占章号，还留下「第一章 创设」这种能在 full_text 逐字命中的假引文。
    所以这里显式按 spine 走，并且章号只对正文项递增。
    """
    from ebooklib import epub as epub_module

    items: list = []
    for entry in getattr(book, "spine", []) or []:
        # spine 元素在不同 ebooklib 版本里可能是 id 字符串、(id, properties) 元组或映射，
        # 这里三种形态都取一次 id（实测 0.20 是 ('chapter_0', 'yes') 这种元组）
        if isinstance(entry, tuple) and entry:
            item_id = entry[0]
        elif isinstance(entry, dict):
            item_id = entry.get("id")
        else:
            item_id = entry
        if not isinstance(item_id, str):
            continue
        item = book.get_item_with_id(item_id)
        if item is None or isinstance(item, (epub_module.EpubNav, epub_module.EpubNcx)):
            continue
        if not str(item.get_name()).lower().endswith((".xhtml", ".html", ".htm")):
            continue
        items.append(item)
    return items


def _parse_epub(path: Path) -> list[Block]:
    ebooklib = _require("ebooklib", 'pip install -e ".[ebook]"', " EPUB 电子书")
    book = ebooklib.epub.read_epub(str(path))
    items = _epub_spine_items(book)
    blocks: list[Block] = []
    for chapter_no, item in enumerate(items, start=1):
        soup = _bs4_beautifulsoup(item.get_content())
        # 章标题就在章节内容的 h1 里，交给 _html_blocks 自然压栈；
        # 只有「内容里一个标题都没有」的章节才用 spine 题名兜底，
        # 否则同一章名会被塞两次（base + 内容），标题路径出现重复。
        if soup.find(_HEADING_TAGS) is None:
            title = str(getattr(item, "title", "") or "").strip()
            base = [title or f"第 {chapter_no} 章"]
        else:
            base = []
        found = _html_blocks(soup, base=base)
        for block in found:
            blocks.append(
                _block(
                    block.text,
                    page=chapter_no,
                    paragraph=len(blocks) + 1,
                    heading_path=list(block.locator.heading_path),
                    url_anchor=block.locator.url_anchor,
                )
            )
    return blocks


def _bs4_beautifulsoup(payload):
    bs4 = _require("bs4", "pip install beautifulsoup4", " EPUB 章节正文")
    return bs4.BeautifulSoup(payload, "html.parser")


# ── 入口与落盘 ────────────────────────────────────────────────────────────────────────
_PARSERS: dict[str, Callable[[Path], list[Block]]] = {
    ".pdf": _parse_pdf,
    ".txt": _parse_txt,
    ".docx": _parse_docx,
    ".html": _parse_html,
    ".htm": _parse_html,
    ".epub": _parse_epub,
}


def parse_document(record: SourceRecord, path: Path) -> ParsedDoc:
    """按文件类型解析来源，返回带定位的文本块列表。"""
    path = Path(path)
    _ensure_readable(path)
    parser = _PARSERS.get(path.suffix.lower())
    if parser is None:
        supported = "、".join(sorted(_PARSERS))
        raise ValueError(f"不支持的语料格式 {path.suffix}（当前支持：{supported}）：{path}")
    blocks = parser(path)
    if not blocks:
        raise ValueError(
            f"来源 {record.source_id} 的 {path.name} 未解析出任何带定位的文本块，"
            f"可能是扫描版（需先 OCR）或正文选择器不匹配：{path}"
        )
    for block in blocks:
        if block.locator.page is None and block.locator.paragraph is None:
            raise ValueError(f"来源 {record.source_id} 存在无定位块，不得入库：{path}")
    return ParsedDoc(source_id=record.source_id, blocks=blocks)


def default_parsed_dir() -> Path:
    """解析产物默认目录：跟着 `Config.data_dir` 走（与 registry.default_whitelist_path 同一口径）。"""
    return get_config().data_dir / "parsed"


def save_parsed(doc: ParsedDoc, out_dir: Path | None = None) -> Path:
    """解析结果原样落 `<out_dir>/<source_id>.json`，供阶段三逐字比对与阶段七审核复算。

    目录默认 `data/parsed/`（审查 I5：简报要求的落盘此前没有任何调用点，等于没接上）；
    调用方可以传别处，测试就传 tmp_path，不污染仓库。
    """
    target_dir = default_parsed_dir() if out_dir is None else Path(out_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{doc.source_id}.json"
    payload = {
        "source_id": doc.source_id,
        "full_text": doc.full_text,
        "blocks": [
            {"text": block.text, "locator": block.locator.model_dump()} for block in doc.blocks
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
