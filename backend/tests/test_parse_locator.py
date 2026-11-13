"""解析与定位（阶段一步骤 1–3）的测试：引用可追溯的前提。

plan 的原话是「每个文本块必须带定位」——无定位的块一旦入库，阶段三的逐字引文校验与
阶段七的审核台都无从下手，所以这里既测「有什么定位」，也测「拿不到定位就必须失败」。
"""

import json
import sys
from pathlib import Path

import pytest
from helpers import row

from app.ingestion.parse import Block, Locator, ParsedDoc, parse_document, save_parsed
from app.ingestion.registry import SourceRecord
from app.qa.schemas import Locator as ContractLocator

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def record(media_type="电子书", source_id="S001", **overrides):
    """造一行来源记录用于解析（解析不做准入校验，发布者无需在白名单内）。"""
    return SourceRecord(**row(media_type=media_type, source_id=source_id, **overrides))


def make_epub(tmp_path, documents, name="示例电子书.epub", with_toc=False):
    """用 ebooklib 现造 EPUB（不落进仓库，避免二进制膨胀）；documents 是每章的 XHTML。

    with_toc=True 时写入真实目录（book.toc），因为 EPUB 的 nav.xhtml 与正文章节同属
    ITEM_DOCUMENT——不设目录的用例永远看不见「导航条目被当正文」这类缺陷（审查 C1）。
    """
    pytest.importorskip("ebooklib")
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("fixture")
    book.set_title("示例电子书")
    book.set_language("zh")
    chapters = []
    for idx, html in enumerate(documents, start=1):
        chapter = epub.EpubHtml(title=f"第 {idx} 章", file_name=f"chap_{idx}.xhtml", lang="zh")
        chapter.set_content(html)
        book.add_item(chapter)
        chapters.append(chapter)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *chapters]
    if with_toc:
        book.toc = [
            epub.Link(f"chap_{idx}.xhtml", title, f"c{idx}")
            for idx, title in enumerate(["第一章 创设", "第二章 解放"], start=1)
        ]
    path = tmp_path / name
    epub.write_epub(str(path), book)
    return path


def test_parse_pdf_keeps_page_numbers():
    """plan 阶段一步骤 1 的原始用例，断言逐字保留。"""
    doc = parse_document(record(), FIXTURES / "校史片段.pdf")
    assert doc.blocks[0].locator.page == 1
    assert all(b.locator.heading_path for b in doc.blocks)
    assert "1925" in doc.blocks[-1].text


def test_parse_pdf_one_block_per_page_and_source_id():
    doc = parse_document(record(source_id="S042"), FIXTURES / "校史片段.pdf")
    assert doc.source_id == "S042"
    assert [b.locator.page for b in doc.blocks] == [1, 2]


def test_parse_txt_splits_by_blank_line_and_keeps_chapter_path():
    doc = record(media_type="文章")
    parsed = parse_document(doc, FIXTURES / "示例章节.txt")
    # 章标题本身不成块，只作为后续正文的标题路径
    assert len(parsed.blocks) == 4
    assert parsed.blocks[0].locator.heading_path == ["第一章 校史沿革"]
    assert parsed.blocks[2].locator.heading_path == ["第二章 解放前后"]
    assert [b.locator.paragraph for b in parsed.blocks] == [1, 2, 3, 4]


def test_parse_docx_promotes_heading_to_path_and_numbers_paragraphs():
    parsed = parse_document(record(), FIXTURES / "示例文档.docx")
    assert [b.locator.paragraph for b in parsed.blocks] == [1, 2]
    assert parsed.blocks[0].locator.heading_path == ["示例文档标题"]
    assert "一九四九年四月" in parsed.blocks[1].text


def test_parse_html_builds_heading_path_and_drops_script():
    parsed = parse_document(record(media_type="文章"), FIXTURES / "示例文章.html")
    texts = [b.text for b in parsed.blocks]
    assert all("脚本噪声" not in t for t in texts), "script 内容不得进入正文"
    assert all("#111111" not in t for t in texts), "style 内容不得进入正文"
    assert parsed.blocks[0].locator.heading_path == ["示例文章标题", "第一节 创设"]
    assert parsed.blocks[-1].locator.heading_path == ["示例文章标题", "第二节 解放前后"]
    assert parsed.blocks[0].locator.url_anchor == "p-1"


def test_parse_html_ignores_footer_outside_article():
    parsed = parse_document(record(media_type="文章"), FIXTURES / "示例文章.html")
    assert all("页脚说明文字" not in b.text for b in parsed.blocks)


@pytest.mark.parametrize(
    "name,media_type",
    [
        ("校史片段.pdf", "电子书"),
        ("示例章节.txt", "文章"),
        ("示例文档.docx", "电子书"),
        ("示例文章.html", "文章"),
    ],
)
def test_every_block_carries_a_locator(name, media_type):
    """不变式：每个块都要有「页码或段落号」之一 + 标题路径 + 逐字引文。"""
    parsed = parse_document(record(media_type=media_type), FIXTURES / name)
    assert parsed.blocks, f"{name} 应当解析出内容"
    for block in parsed.blocks:
        assert block.locator.page is not None or block.locator.paragraph is not None
        assert block.locator.heading_path, "标题路径不得为空，否则引用无法归位"
        assert block.locator.quote == block.text


def test_full_text_is_blocks_joined_by_newline():
    parsed = parse_document(record(), FIXTURES / "校史片段.pdf")
    assert parsed.full_text == "\n".join(b.text for b in parsed.blocks)
    assert "1925" in parsed.full_text


def test_parse_rejects_unknown_extension(tmp_path):
    bad = tmp_path / "材料.md"
    bad.write_text("# 标题\n\n正文。", encoding="utf-8")
    with pytest.raises(ValueError, match="\\.md"):
        parse_document(record(), bad)


def test_parse_returns_parsed_doc_of_blocks():
    parsed = parse_document(record(), FIXTURES / "校史片段.pdf")
    assert isinstance(parsed, ParsedDoc)
    assert parsed.source_id == "S001"
    assert all(isinstance(b, Block) for b in parsed.blocks)


def test_parse_rejects_file_without_locatable_text(tmp_path):
    empty = tmp_path / "空.txt"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="定位"):
        parse_document(record(media_type="文章"), empty)


def test_parse_missing_file_raises_value_error(tmp_path):
    with pytest.raises(ValueError, match="不存在"):
        parse_document(record(), tmp_path / "没有这个文件.pdf")


def test_parse_locator_is_the_openapi_contract_model():
    """解析层与问答契约共用同一个 Locator 类，避免两处字段漂移。"""
    assert Locator is ContractLocator
    assert Block(text="正文", locator=ContractLocator(quote="正文")).locator.quote == "正文"


def test_epub_branch_gives_actionable_hint_when_extra_missing(tmp_path, monkeypatch):
    """未装 ebook extra 时要明确提示装什么，而不是吞成 ImportError: No module named ebooklib。"""
    monkeypatch.setitem(sys.modules, "ebooklib", None)
    path = tmp_path / "书.epub"
    path.write_bytes(b"PK\x03\x04 placeholder")
    with pytest.raises(ImportError, match=r"pip install.*ebook"):
        parse_document(record(), path)


def test_parse_epub_keeps_chapter_heading(tmp_path):
    """EPUB 分支：章节标题进标题路径，章节序号写进定位。"""
    path = make_epub(
        tmp_path,
        [
            (
                "<html><body><h1>第一章 创设</h1>"
                "<p>讲习所于一九二五年创设，学员多为产业工人。</p></body></html>"
            )
        ],
    )
    parsed = parse_document(record(), path)
    assert parsed.blocks
    assert parsed.blocks[0].locator.heading_path[:1] == ["第一章 创设"]
    assert parsed.blocks[0].locator.page == 1


def test_parse_epub_numbers_chapters_as_pages(tmp_path):
    """电子书按章节给定位：第二章的块 page 必须是 2，不能全是 1。"""
    path = make_epub(
        tmp_path,
        [
            "<html><body><h1>第一章 创设</h1><p>讲习所于一九二五年创设。</p></body></html>",
            "<html><body><h1>第二章 解放</h1><p>一九四九年四月本地解放。</p></body></html>",
        ],
    )
    parsed = parse_document(record(), path)
    assert [b.locator.page for b in parsed.blocks] == [1, 2]
    assert parsed.blocks[0].locator.heading_path == ["第一章 创设"]
    assert parsed.blocks[1].locator.heading_path == ["第二章 解放"]


def test_parse_epub_paragraph_numbers_are_continuous_across_chapters(tmp_path):
    """段落号跨章连续递增，供阶段三把引文精确落回某一段。"""
    path = make_epub(
        tmp_path,
        [
            "<html><body><h1>第一章</h1><p>a1</p><p>a2</p></body></html>",
            "<html><body><h1>第二章</h1><p>b1</p></body></html>",
        ],
    )
    parsed = parse_document(record(), path)
    assert [b.locator.paragraph for b in parsed.blocks] == [1, 2, 3]
    assert [b.text for b in parsed.blocks] == ["a1", "a2", "b1"]


def test_parse_epub_keeps_nested_heading_levels(tmp_path):
    """章节内还有小标题时，标题路径要保留层级，而不是只剩章名。"""
    path = make_epub(
        tmp_path,
        [
            (
                "<html><body><h1>第一章 创设</h1><h2>一、办学缘起</h2><p>正文甲。</p>"
                "<h2>二、学员构成</h2><p>正文乙。</p></body></html>"
            )
        ],
    )
    parsed = parse_document(record(), path)
    assert parsed.blocks[0].locator.heading_path == ["第一章 创设", "一、办学缘起"]
    assert parsed.blocks[1].locator.heading_path == ["第一章 创设", "二、学员构成"]


def test_parse_epub_skips_chapter_without_locatable_text(tmp_path):
    """封面/版权页这类无正文章节不得产出空块；整本都没有则报错。"""
    path = make_epub(
        tmp_path,
        [
            "<html><body><h1>封面</h1></body></html>",
            "<html><body><h1>第一章</h1><p>有内容的正文。</p></body></html>",
        ],
    )
    parsed = parse_document(record(), path)
    assert [b.text for b in parsed.blocks] == ["有内容的正文。"]
    assert parsed.blocks[0].locator.page == 2


def test_parse_epub_ignores_navigation_document(tmp_path):
    """审查 C1：nav.xhtml 与正文章节同属 ITEM_DOCUMENT。

    目录条目一旦被当成正文，「第一章 创设」就成了**可在 full_text 逐字命中的假引文**，
    还被编上一个不存在的章号——出处卡片会印着与实体书目录差一位的定位。
    错误的定位比空定位危险，因为它在「每块带定位」这道闸门上是绿的。
    """
    path = make_epub(
        tmp_path,
        [
            "<html><body><h1>第一章 创设</h1><p>讲习所于一九二五年创设。</p></body></html>",
            "<html><body><h1>第二章 解放</h1><p>一九四九年四月本地解放。</p></body></html>",
        ],
        with_toc=True,
    )
    parsed = parse_document(record(), path)
    assert [b.text for b in parsed.blocks] == ["讲习所于一九二五年创设。", "一九四九年四月本地解放。"]
    assert [b.locator.page for b in parsed.blocks] == [1, 2], "章号只能给正文章节，导航不得占位"
    assert "目录" not in parsed.full_text


# ── 审查 I6：嵌套结构不得重复出块 ─────────────────────────────────────────────────────
def test_parse_html_does_not_duplicate_nested_paragraph(tmp_path):
    """<blockquote><p>…</p></blockquote> 里的一句话只能是一个块。

    重复出块会让段落号虚增、full_text 出现重复文本，阶段三逐字比对就无法判定哪条才是出处。
    """
    page = tmp_path / "嵌套.html"
    page.write_text(
        "<html><body><article><h1>标题</h1>"
        '<blockquote><p id="q1">引文段落。</p></blockquote>'
        '<p id="p2">另一段。</p></article></body></html>',
        encoding="utf-8",
    )
    parsed = parse_document(record(media_type="文章"), page)
    assert [b.text for b in parsed.blocks] == ["引文段落。", "另一段。"]
    assert [b.locator.paragraph for b in parsed.blocks] == [1, 2]
    assert parsed.full_text == "引文段落。\n另一段。"


def test_parse_html_nested_list_item_is_not_duplicated(tmp_path):
    page = tmp_path / "列表.html"
    page.write_text(
        "<html><body><article><h1>标题</h1><ul><li id=l1>第一项</li></ul>"
        '<p id="p2">另一段。</p></article></body></html>',
        encoding="utf-8",
    )
    parsed = parse_document(record(media_type="文章"), page)
    assert [b.text for b in parsed.blocks] == ["第一项", "另一段。"]


# ── 审查 I4：三个守卫此前零测试（变异后全绿，等于没锁）────────────────────────────────
def test_block_without_any_locator_position_is_rejected(tmp_path, monkeypatch):
    """「无定位块不得入库」这条守卫本身要有用例守着：构造一个既无页码又无段落号的块。"""
    from app.ingestion import parse as parse_module

    def fake_parser(path):
        return [parse_module.Block(text="无定位的块", locator=Locator(quote="无定位的块"))]

    monkeypatch.setitem(parse_module._PARSERS, ".txt", fake_parser)
    target = tmp_path / "无定位.txt"
    target.write_text("内容", encoding="utf-8")
    with pytest.raises(ValueError, match="无定位"):
        parse_document(record(media_type="文章"), target)


def test_parse_rejects_directory_as_path(tmp_path):
    """parse 侧的目录入参守卫（此前只有 registry 侧被测，M10 变异后 parse 全绿）。"""
    folder = tmp_path / "当成文件传的目录"
    folder.mkdir()
    with pytest.raises(ValueError, match="不是文件"):
        parse_document(record(), folder)


# ── 审查 I8：真实快照里的站点模板公共块不得进正文 ─────────────────────────────────────
BOILERPLATE_HTML = """<!DOCTYPE html><html><body>
<div class="header"><ul class="menu clearfix">
  <li><a href="/">首页</a></li><li><a href="/news">资讯</a></li><li><a href="/search">站内搜索</a></li>
</ul></div>
<div class="main clearfix">
  <div class="side">
    <h3>图片新闻</h3>
    <ul class="list">
      <li><a href="/1">某省举办红色文化展览活动综述</a></li>
      <li><a href="/2">纪念长征胜利九十周年学术研讨会在京召开</a></li>
      <li><a href="/3">各地开展主题党日活动情况通报一则较长文字</a></li>
    </ul>
    <h3>最新更新</h3>
    <ul class="list">
      <li><a href="/4">湘籍早期中国共产党人活动考察报告</a></li>
      <li><a href="/5">某地地方志书编纂工作推进会召开情况通报</a></li>
      <li><a href="/6">红色档案数字化实践与思考一则较长说明文字</a></li>
    </ul>
  </div>
  <div class="content">
    <h1 id="t">讲习所创设记</h1>
    <p id="p1">讲习所于一九二五年创设，学员多为产业工人，课程以社会科学与军事训练为主。</p>
    <p id="p2">一九四九年四月本地解放后，该所旧址被改为纪念场所并对外开放供人参观。</p>
  </div>
</div>
<div class="footer"><p>版权所有：某某网 京ICP备12345678号 本站点内容未经授权不得转载</p></div>
</body></html>
"""


def test_parse_html_drops_site_boilerplate(tmp_path):
    """跨篇逐字相同的模板块（导航、侧栏「图片新闻/最新更新」、页脚版权）必须被剔除。

    危害与 C1 同构而更危险：模板块出现在每一篇里，抽取器一旦从中「抽」出一条事实，
    那条引文能在全部快照里逐字命中，多来源交叉验证就被凭空造了出来。
    """
    page = tmp_path / "带模板.html"
    page.write_text(BOILERPLATE_HTML, encoding="utf-8")
    parsed = parse_document(record(media_type="文章"), page)
    texts = [b.text for b in parsed.blocks]
    assert texts == [
        "讲习所于一九二五年创设，学员多为产业工人，课程以社会科学与军事训练为主。",
        "一九四九年四月本地解放后，该所旧址被改为纪念场所并对外开放供人参观。",
    ]
    for banned in ("图片新闻", "最新更新", "首页", "站内搜索", "版权所有", "京ICP备"):
        assert banned not in parsed.full_text, f"模板文本 {banned} 混进了正文"


def test_boilerplate_filter_keeps_body_whose_ancestor_is_named_header(tmp_path):
    """反向防误杀（实测取证结论）：真实站点的正文外层就叫 div.i-main-header。

    「祖先 class/id 含 header/menu/footer 就整块丢弃」会把 S145 那 36 段真正文全杀掉，
    所以判据必须落在块本身（长度与链接密度），不能落在祖先命名上。
    """
    page = tmp_path / "祖先叫header.html"
    page.write_text(
        """<html><body><div class="i-main-header"><div class="tyl-main"><div id="j-show-body">
        <h1>明嘉靖长沙府志</h1>
        <p>编者按：明嘉靖《长沙府志》六卷，明嘉靖十二年修，为现存第一部长沙府志，原藏于日本国会图书馆。</p>
        <p>序曰：古者地理有图、有志，盖周官职方氏与小史外史所掌，而道以诏王者，非徒备一方之记载而已。</p>
        </div></div></div></body></html>""",
        encoding="utf-8",
    )
    parsed = parse_document(record(media_type="电子书"), page)
    assert len(parsed.blocks) == 2
    assert all(len(b.text) > 30 for b in parsed.blocks)


def test_parse_rejects_page_without_real_body(tmp_path):
    """只剩模板的页面必须拒收，而不是产出一堆「可逐字命中」的模板卡片。

    这条走的是既有守卫（未解析出任何带定位的文本块即报错），不另设字数阈值：
    171 篇真实快照清洗后最短 207 字，「正文只有几十个字」的空壳页在本批语料里不存在。
    """
    page = tmp_path / "只有模板.html"
    page.write_text(
        """<html><body>
        <div class="header"><ul class="menu">
          <li><a href="/">首页</a></li><li><a href="/c">资讯</a></li><li><a href="/s">站内搜索</a></li>
        </ul></div>
        <div class="footer"><p>版权所有：某某网 京ICP备12345678号</p></div>
        </body></html>""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="未解析出"):
        parse_document(record(media_type="文章"), page)


def test_parse_html_drops_byline_and_copyright_lines(tmp_path):
    """署名行与页脚版权行也是模板：同一编辑负责几十篇，这类串就在几十篇里逐字相同。

    实测 171 篇里「（责任编辑：×）」出现在 21 篇、「主办单位：…」页脚 148 字出现在 9 篇，
    若被抽成事实条目，交叉验证信号就是凭空造的。
    """
    page = tmp_path / "署名页.html"
    page.write_text(
        """<html><body><article><h1>长征档案整理记</h1>
        <p id="p1">本次数字化共归集长征档案两千余件，涵盖行军文电、补充材料等类别，整理工作历时两年完成。</p>
        <p id="p2">项目组对照原件逐条核验目录，发现三处年代记载不一致，均已按档案原件更正后重新归档入库。</p>
        <p>（责任编辑：李瑞环）</p>
        <p>主办单位：某某档案馆 网站标识码：0000000017 京ICP备16005727号</p>
        </article></body></html>""",
        encoding="utf-8",
    )
    parsed = parse_document(record(media_type="文章"), page)
    texts = [b.text for b in parsed.blocks]
    assert all("责任编辑" not in t for t in texts)
    assert all("ICP备" not in t for t in texts)
    assert len(texts) == 2


# ── 审查 I5：解析结果要落 data/parsed，且目录跟着 DATA_DIR ─────────────────────────────
def test_save_parsed_defaults_to_data_dir_parsed(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    doc = parse_document(record(media_type="文章"), FIXTURES / "示例文章.html")
    out = save_parsed(doc)
    assert out == tmp_path / "parsed" / "S001.json"
    assert json.loads(out.read_text(encoding="utf-8"))["source_id"] == "S001"


def test_save_parsed_writes_json_per_source_id(tmp_path):
    parsed = parse_document(record(source_id="S007"), FIXTURES / "校史片段.pdf")
    out = save_parsed(parsed, tmp_path)
    assert out == tmp_path / "S007.json"
    text = out.read_text(encoding="utf-8")
    assert "\\u" not in text, "解析产物不得转义中文，人工核对应直接可读"
    data = json.loads(text)
    assert data["source_id"] == "S007"
    assert data["blocks"][0]["locator"]["page"] == 1
    assert "1925" in data["blocks"][-1]["text"]
    assert data["blocks"][0]["locator"]["quote"] == data["blocks"][0]["text"]
