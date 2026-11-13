"""来源登记表读取与校验的测试（阶段零步骤 2–4）。"""

import pytest
from helpers import COLUMNS, CONFIG_ENV_KEYS, row, whitelist_entry, write_registry, write_whitelist

from app.ingestion.registry import (
    default_whitelist_path,
    load_registry,
    load_whitelist,
    normalize_org,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """宿主设过 DATA_DIR 会改变默认白名单路径，默认路径类断言必须先清干净。"""
    for key in CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_registry_accepts_valid_row(tmp_path, whitelist_file):
    csv_path = tmp_path / "reg.csv"
    csv_path.write_text(
        "source_id,title,publisher,publish_date,url_or_path,access_date,"
        "license_note,corpus_tier,media_type\n"
        "S001,红色文化读本（第三卷）,人民出版社,1985,/data/raw/ebook_001.pdf,"
        "2026-11-13,公开出版物,核心,电子书\n",
        encoding="utf-8",
    )
    records = load_registry(csv_path, whitelist_path=whitelist_file)
    assert len(records) == 1
    assert records[0].source_id == "S001"
    assert records[0].publisher == "人民出版社"
    assert records[0].media_type == "电子书"
    assert records[0].corpus_tier == "核心"


def test_registry_rejects_missing_publication_date(tmp_path, whitelist_file):
    """M-4：显式传白名单 fixture，不靠规则顺序侥幸不碰真实 backend/data/来源白名单.yml。"""
    csv = tmp_path / "reg.csv"
    csv.write_text(
        "source_id,title,publisher,publish_date,url_or_path,access_date,"
        "license_note,corpus_tier,media_type\n"
        "S001,红色文化读本（第三卷）,某人民出版社,,/data/raw/ebook_001.pdf,"
        "2026-11-13,公开出版物,核心,电子书\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="publish_date 不得留空"):
        load_registry(csv, whitelist_path=whitelist_file)


def test_registry_rejects_ebook_without_publisher(tmp_path, whitelist_file):
    # 电子书必须有出版社；扫描电子书无出版社信息则不得入库
    csv_path = write_registry(tmp_path, row(media_type="电子书", publisher="", publish_date="1985"))
    # 断言用规则 6 独有的短语：旧的 match="publisher" 会同时命中规则 7 的报错，
    # 删掉规则 6 的检查测试照样绿（终审 I-6 的突变实验已证明）
    with pytest.raises(ValueError, match="电子书必须填写 publisher"):
        load_registry(csv_path, whitelist_path=whitelist_file)


def test_registry_rejects_source_off_whitelist(tmp_path, whitelist_file):
    csv_path = write_registry(tmp_path, row(publisher="某个人自媒体", media_type="文章"))
    with pytest.raises(ValueError, match="whitelist"):
        load_registry(csv_path, whitelist_path=whitelist_file)


# 规则 1：编号唯一
def test_registry_rejects_duplicate_source_id(tmp_path, whitelist_file):
    csv_path = write_registry(tmp_path, row(), row(title="另一读本"))
    # 独有短语：旧断言 match="source_id" 会同时命中规则 2 的「source_id 不得留空」
    with pytest.raises(ValueError, match="与第 2 行重复"):
        load_registry(csv_path, whitelist_path=whitelist_file)


# 规则 2：标题、链接或路径、获取日期非空
@pytest.mark.parametrize("column", ["title", "url_or_path", "access_date"])
def test_registry_rejects_empty_required_column(tmp_path, whitelist_file, column):
    csv_path = write_registry(tmp_path, row(**{column: ""}))
    with pytest.raises(ValueError, match=f"{column} 不得留空"):
        load_registry(csv_path, whitelist_path=whitelist_file)


# 规则 3：文章允许「年代不详」这一字面值（电子书不允许，见规则 6）
def test_registry_allows_article_with_unknown_date(tmp_path, whitelist_file):
    csv_path = write_registry(
        tmp_path, row(media_type="文章", publisher="新华网", publish_date="年代不详")
    )
    records = load_registry(csv_path, whitelist_path=whitelist_file)
    assert records[0].publish_date == "年代不详"


# 规则 4：语料层级枚举
def test_registry_rejects_unknown_corpus_tier(tmp_path, whitelist_file):
    csv_path = write_registry(tmp_path, row(corpus_tier="待定"))
    with pytest.raises(ValueError, match="corpus_tier"):
        load_registry(csv_path, whitelist_path=whitelist_file)


# 规则 5：载体类型枚举
def test_registry_rejects_unknown_media_type(tmp_path, whitelist_file):
    csv_path = write_registry(tmp_path, row(media_type="视频"))
    with pytest.raises(ValueError, match="media_type"):
        load_registry(csv_path, whitelist_path=whitelist_file)


# 规则 6：电子书必须有非「年代不详」的四位年份出版年
def test_registry_rejects_ebook_with_unknown_date(tmp_path, whitelist_file):
    csv_path = write_registry(tmp_path, row(media_type="电子书", publish_date="年代不详"))
    with pytest.raises(ValueError, match="必须是四位出版年"):
        load_registry(csv_path, whitelist_path=whitelist_file)


# 规则 7：机构名做别名归一后命中白名单
def test_registry_accepts_publisher_alias(tmp_path, whitelist_file):
    csv_path = write_registry(tmp_path, row(publisher=" 人民版社 "))
    records = load_registry(csv_path, whitelist_path=whitelist_file)
    assert records[0].publisher == "人民版社"


# 规则 8：授权或公开获取说明非空
def test_registry_rejects_empty_license_note(tmp_path, whitelist_file):
    csv_path = write_registry(tmp_path, row(license_note=""))
    with pytest.raises(ValueError, match="license_note"):
        load_registry(csv_path, whitelist_path=whitelist_file)


# 白名单文件缺失时，错误信息同样要含 whitelist
def test_load_whitelist_missing_file_mentions_whitelist(tmp_path):
    with pytest.raises(ValueError, match="whitelist"):
        load_whitelist(tmp_path / "不存在的白名单.yml")


# 默认白名单路径指向 backend/data/来源白名单.yml（只断言路径，不读文件）
def test_default_whitelist_path_points_to_data_dir():
    path = default_whitelist_path()
    assert path.name == "来源白名单.yml"
    assert path.parent.name == "data"


# ── I-5：默认白名单路径必须跟随 Config.data_dir，否则 DATA_DIR 迁移后闸门读旧名单 ──────
def test_default_whitelist_path_follows_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert default_whitelist_path() == tmp_path / "来源白名单.yml"


def test_load_registry_uses_whitelist_from_data_dir(tmp_path, monkeypatch):
    """不显式传 whitelist_path 时（阶段一 cli 最顺手的写法），闸门要读迁移后的名单。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    write_whitelist(tmp_path, whitelist_entry("人民出版社", verified=False))
    csv_path = write_registry(tmp_path, row())
    with pytest.raises(ValueError, match="verified"):
        load_registry(csv_path)


def test_load_registry_honours_explicit_whitelist_over_data_dir(
    tmp_path, monkeypatch, whitelist_file
):
    """显式传参优先于 DATA_DIR，避免两个来源互相遮蔽。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "该目录不存在"))
    csv_path = write_registry(tmp_path, row())
    assert load_registry(csv_path, whitelist_path=whitelist_file)


# ── C-1：未核验条目的名字被已核验条目「借道」收录时，不得放行 ──────────────────────
# 形态 1：已核验条目把未核验条目的主名写成自己的别名
_PRIMARY_BORROWED = [
    {
        "name": "甲机构",
        "aliases": ["危险自媒体"],
        "verified": True,
        "verified_at": "2026-11-13",
    },
    {
        "name": "危险自媒体",
        "aliases": [],
        "verified": False,
        "verified_at": "2026-11-13",
    },
]


def test_load_whitelist_rejects_unverified_primary_name_claimed_as_alias(tmp_path):
    """未核验条目的主名被任一已核验条目写成 alias → 名单自相矛盾，必须人工裁决。"""
    with pytest.raises(ValueError, match="人工裁决") as exc:
        load_whitelist(write_whitelist(tmp_path, _PRIMARY_BORROWED))
    msg = str(exc.value)
    assert "whitelist" in msg and "危险自媒体" in msg


def test_load_whitelist_rejects_alias_borrowed_from_unverified_entry(tmp_path):
    """终审举的实例形态：已核验条目收录「党史网」，而它是未核验条目中共党史网的别名。

    只按「主名」判冲突堵不住这条，别名同样不得借道放行。
    """
    entries = [
        {
            "name": "中央党史和文献研究院",
            "aliases": ["党史网"],
            "verified": True,
            "verified_at": "2026-11-13",
        },
        {
            "name": "中共党史网（中国共产党历史和文献网）",
            "aliases": ["党史网"],
            "verified": False,
            "verified_at": "2026-11-13",
        },
    ]
    with pytest.raises(ValueError, match="人工裁决"):
        load_whitelist(write_whitelist(tmp_path, entries))


def test_load_whitelist_rejects_same_primary_name_verified_and_unverified(tmp_path):
    """同名两条、一真一假：不能靠条目顺序侥幸放行。"""
    entries = [
        {"name": "乙机构", "aliases": [], "verified": True, "verified_at": "2026-11-13"},
        {"name": "乙机构", "aliases": [], "verified": False, "verified_at": "2026-11-13"},
    ]
    with pytest.raises(ValueError, match="人工裁决"):
        load_whitelist(write_whitelist(tmp_path, entries))


def test_load_whitelist_allows_alias_shared_by_two_verified_entries(tmp_path):
    """重复只发生在两条已核验条目之间时，属正常共用简称，不报错、照常放行。"""
    entries = [
        {"name": "甲机构", "aliases": ["共用简称"], "verified": True, "verified_at": "2026-11-13"},
        {"name": "乙机构", "aliases": ["共用简称"], "verified": True, "verified_at": "2026-11-13"},
    ]
    wl = load_whitelist(write_whitelist(tmp_path, entries))
    assert "共用简称" in wl.approved
    assert not wl.pending


def test_registry_rejects_borrowed_name_end_to_end(tmp_path):
    """端到端：借道注入后，登记表里那一行既不能通过，也不能被静默放行。"""
    wl_path = write_whitelist(tmp_path, _PRIMARY_BORROWED)
    csv_path = write_registry(tmp_path, row(publisher="危险自媒体", media_type="文章"))
    with pytest.raises(ValueError, match="人工裁决"):
        load_registry(csv_path, whitelist_path=wl_path)


# ── I-1：source_id 留空必须拒绝（README §一 承诺必填，阶段一按编号落盘）──────────────
def test_registry_rejects_empty_source_id(tmp_path, whitelist_file):
    csv_path = write_registry(tmp_path, row(source_id=""))
    with pytest.raises(ValueError, match="source_id 不得留空"):
        load_registry(csv_path, whitelist_path=whitelist_file)


def test_registry_rejects_whitespace_only_source_id(tmp_path, whitelist_file):
    csv_path = write_registry(tmp_path, row(source_id="   "))
    with pytest.raises(ValueError, match="source_id 不得留空"):
        load_registry(csv_path, whitelist_path=whitelist_file)


# ── I-3 / M-7：非 UTF-8 CSV、坏 YAML、传目录都要归一为可操作的 ValueError ─────────────
def test_registry_rejects_non_utf8_csv_with_actionable_error(tmp_path, whitelist_file):
    """Excel 中文版「另存为 CSV」得到 GBK 文件：不能抛裸 UnicodeDecodeError，
    否则阶段一 cli 的 except ValueError 拦不住，且报错不带文件名。"""
    path = tmp_path / "gbk.csv"
    header = ",".join(COLUMNS)
    body = "S001,红色文化读本（第三卷）,人民出版社,1985,data/raw/a.pdf,2026-11-13,公开出版物,核心,电子书"
    # Excel 中文版「另存为 CSV」得到的是 GBK 且不带 BOM（BOM 也无法用 GBK 表示）
    path.write_bytes((header + "\n" + body + "\n").encode("gbk"))
    with pytest.raises(ValueError, match="编码") as exc:
        load_registry(path, whitelist_path=whitelist_file)
    msg = str(exc.value)
    assert str(path) in msg and "UTF-8" in msg


def test_load_whitelist_rejects_broken_yaml_as_value_error(tmp_path):
    """手改坏的 YAML 不能抛裸 ParserError，且要指出是哪个文件。"""
    path = tmp_path / "坏名单.yml"
    path.write_text("- name: 甲机构\n  aliases: [a, b\n  verified: true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="语法") as exc:
        load_whitelist(path)
    assert str(path) in str(exc.value)


def test_registry_rejects_directory_as_csv_path(tmp_path, whitelist_file):
    """csv_path 传目录：归一为 ValueError，而不是 PermissionError / IsADirectoryError。"""
    d = tmp_path / "不是文件"
    d.mkdir()
    with pytest.raises(ValueError, match="不是文件"):
        load_registry(d, whitelist_path=whitelist_file)


def test_load_whitelist_rejects_directory_path(tmp_path):
    d = tmp_path / "名单目录"
    d.mkdir()
    with pytest.raises(ValueError, match="不是文件"):
        load_whitelist(d)


# ── I-7：年份只认 ASCII 数字，月日给出就要检查范围；入库仍存原值 ──────────────────────
@pytest.mark.parametrize("publish_date", ["１９８５", "١٩٨٥", "１９８５年", "１985"])
def test_registry_rejects_non_ascii_ebook_year(tmp_path, whitelist_file, publish_date):
    """全角与非 ASCII 数字不得原样入库：阶段一的元数据比对与阶段五时间轴都按 ASCII 解析。"""
    csv_path = write_registry(tmp_path, row(media_type="电子书", publish_date=publish_date))
    with pytest.raises(ValueError, match="必须是四位出版年"):
        load_registry(csv_path, whitelist_path=whitelist_file)


@pytest.mark.parametrize(
    "publish_date", ["1985年13月", "1985/13/45", "1985年10月32日", "1985-00", "1985.0.1"]
)
def test_registry_rejects_out_of_range_month_or_day(tmp_path, whitelist_file, publish_date):
    csv_path = write_registry(tmp_path, row(media_type="电子书", publish_date=publish_date))
    with pytest.raises(ValueError, match="不合法"):
        load_registry(csv_path, whitelist_path=whitelist_file)


@pytest.mark.parametrize("publish_date", ["1985年1月", "1985-12-31", "1985.1.1", "1985年12月1日"])
def test_registry_accepts_valid_month_and_day(tmp_path, whitelist_file, publish_date):
    csv_path = write_registry(tmp_path, row(media_type="电子书", publish_date=publish_date))
    assert load_registry(csv_path, whitelist_path=whitelist_file)[0].publish_date == publish_date


def test_registry_stores_publish_date_verbatim(tmp_path, whitelist_file):
    """归一只用于校验，入库字段保持采编写下的原文（展示口径不变）。"""
    csv_path = write_registry(tmp_path, row(media_type="电子书", publish_date="1985年10月"))
    assert load_registry(csv_path, whitelist_path=whitelist_file)[0].publish_date == "1985年10月"


# ── I-8：Whitelist 契约必须保留原始条目，阶段四冲突展示与阶段七审核台不得各自重解析 YAML ──
def test_whitelist_keeps_original_entries(whitelist_file):
    wl = load_whitelist(whitelist_file)
    entry = wl.entries["人民出版社"]
    assert entry["name"] == "人民出版社"
    assert entry["verified"] is True
    assert entry["domain"] == "www.example-pub.com"
    assert "People's Publishing House" in entry["aliases"]
    # 别名指向同一条目：审核台按 publisher 反查即可拿到域名与栏目
    assert wl.entries["人民版社"] == entry


def test_whitelist_entries_keep_unverified_rows_fields(tmp_path):
    """未核验条目的字段同样要留在契约里，审核台得能说明「为什么被拦」。"""
    wl = load_whitelist(write_whitelist(tmp_path, whitelist_entry("新华网", verified=False)))
    assert wl.entries["新华网"]["verified"] is False
    assert wl.entries["新华通讯社"]["domain"] == "www.news.cn"


def test_whitelist_entries_cover_every_listed_name(whitelist_file):
    """凡进入 approved/pending 的名字都必须在 entries 里有对应条目，不得有名字无信息。"""
    wl = load_whitelist(whitelist_file)
    for name in wl.approved | set(wl.pending):
        assert name in wl.entries


# ── M-2：借道场景的报错不得再说成「不在 whitelist」──
def test_borrowed_name_message_is_not_the_off_list_message(tmp_path):
    with pytest.raises(ValueError) as exc:
        load_whitelist(write_whitelist(tmp_path, _PRIMARY_BORROWED))
    msg = str(exc.value)
    assert "不在权威来源 whitelist 内" not in msg
    assert "自相矛盾" in msg and "人工裁决" in msg


# ── M-9：helpers 写 None 的埋雷 ──
def test_write_registry_writes_none_as_empty_cell(tmp_path):
    """字段值给 None 必须落成空单元格，否则会写出字面量 "None" 混过后续校验。"""
    csv_path = write_registry(tmp_path, row(publisher=None))
    assert "None" not in csv_path.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="publisher"):
        load_registry(csv_path, whitelist_path=write_whitelist(tmp_path))


# ── I-6 补覆盖：README §一 承诺「CSV UTF-8（带 BOM）」可用，此前零测试 ──
def test_registry_accepts_csv_with_bom(tmp_path, whitelist_file):
    plain = write_registry(tmp_path, row(), name="plain.csv")
    bom_path = tmp_path / "bom.csv"
    bom_path.write_bytes(b"\xef\xbb\xbf" + plain.read_bytes())
    assert len(load_registry(bom_path, whitelist_path=whitelist_file)) == 1


# 规则 6 收紧：出版年必须是恰好四位、且落在 1840–2100 的年份，混写一律拒绝
@pytest.mark.parametrize(
    "publish_date",
    [
        "19850",  # 五位数字，内含 1985
        "198510",  # 年+月但不带分隔符
        "年代不详1985",  # 占位字面值拼年份钻空子
        "公元前1985",  # 年份前带其他文字
        "1985 内部资料",  # 年份后带无关文字
    ],
)
def test_registry_rejects_ambiguous_ebook_year(tmp_path, whitelist_file, publish_date):
    csv_path = write_registry(tmp_path, row(media_type="电子书", publish_date=publish_date))
    with pytest.raises(ValueError, match="必须是四位出版年"):
        load_registry(csv_path, whitelist_path=whitelist_file)


@pytest.mark.parametrize("publish_date", ["1839", "2101", "1000"])
def test_registry_rejects_ebook_year_out_of_range(tmp_path, whitelist_file, publish_date):
    csv_path = write_registry(tmp_path, row(media_type="电子书", publish_date=publish_date))
    with pytest.raises(ValueError, match="不在合理区间"):
        load_registry(csv_path, whitelist_path=whitelist_file)


@pytest.mark.parametrize("publish_date", ["1840", "2100"])
def test_registry_accepts_year_at_range_boundary(tmp_path, whitelist_file, publish_date):
    csv_path = write_registry(tmp_path, row(media_type="电子书", publish_date=publish_date))
    records = load_registry(csv_path, whitelist_path=whitelist_file)
    assert records[0].publish_date == publish_date


@pytest.mark.parametrize(
    "publish_date", ["1985", "1985年", "1985年10月", "1985-10", "1985.10.05", "2026"]
)
def test_registry_accepts_clean_ebook_date(tmp_path, whitelist_file, publish_date):
    csv_path = write_registry(tmp_path, row(media_type="电子书", publish_date=publish_date))
    records = load_registry(csv_path, whitelist_path=whitelist_file)
    assert records[0].publish_date == publish_date


# 规则 9：白名单条目必须 verified: true 才算有效准入
def test_registry_rejects_unverified_whitelist_entry(tmp_path):
    wl = write_whitelist(tmp_path, whitelist_entry("人民出版社", verified=False))
    csv_path = write_registry(tmp_path, row())
    with pytest.raises(ValueError, match="verified") as exc:
        load_registry(csv_path, whitelist_path=wl)
    msg = str(exc.value)
    # 错误信息要能告诉用户下一步做什么：机构名 + verified_at + 补核口径
    assert "whitelist" in msg
    assert "人民出版社" in msg
    assert "2026-11-13" in msg
    assert "待核验" in msg and "补核后改 true" in msg


def test_registry_rejects_whitelist_entry_missing_verified(tmp_path):
    wl = write_whitelist(tmp_path, whitelist_entry("新华网", verified=None))
    csv_path = write_registry(
        tmp_path, row(media_type="文章", publisher="新华网", publish_date="2026-11-12")
    )
    with pytest.raises(ValueError, match="verified") as exc:
        load_registry(csv_path, whitelist_path=wl)
    assert "whitelist" in str(exc.value)


@pytest.mark.parametrize("value", ["true", 1, "yes"])
def test_registry_rejects_non_boolean_verified(value, tmp_path):
    wl = write_whitelist(tmp_path, whitelist_entry("中共党史出版社", verified=value))
    csv_path = write_registry(
        tmp_path, row(publisher="中共党史出版社", media_type="电子书", publish_date="2024")
    )
    with pytest.raises(ValueError, match="verified"):
        load_registry(csv_path, whitelist_path=wl)


def test_registry_alias_of_unverified_entry_is_also_rejected(tmp_path):
    """未核验条目的别名同样不得放行，否则换个写法就绕过闸门。"""
    wl = write_whitelist(tmp_path, whitelist_entry("人民出版社", verified=False))
    csv_path = write_registry(tmp_path, row(publisher="人民版社"))
    with pytest.raises(ValueError, match="verified"):
        load_registry(csv_path, whitelist_path=wl)


def test_registry_distinguishes_off_whitelist_from_unverified(tmp_path, whitelist_file):
    """机构根本不在名单里时，报「不在 whitelist」而不是「未核验」。"""
    csv_path = write_registry(tmp_path, row(publisher="某个人自媒体", media_type="文章"))
    with pytest.raises(ValueError, match="whitelist") as exc:
        load_registry(csv_path, whitelist_path=whitelist_file)
    assert "verified" not in str(exc.value)


# 正向对照：同一条目 verified: true 时必须放行，证明规则 9 不是无条件拒绝
def test_registry_accepts_verified_whitelist_entry(tmp_path):
    csv_path = write_registry(tmp_path, row())
    records = load_registry(csv_path, whitelist_path=write_whitelist(tmp_path))
    assert records[0].publisher == "人民出版社"


def test_load_whitelist_splits_approved_and_pending(tmp_path):
    """未核验条目的全称与别名都进 pending；已核验条目进 approved。"""
    entries = whitelist_entry("新华网", verified=False)
    wl = load_whitelist(write_whitelist(tmp_path, entries))
    assert "人民出版社" in wl.approved
    assert "新华网" in wl.pending and "新华通讯社" in wl.pending
    assert "新华网" not in wl.approved


# 机构名带全角句点「。」时也要能命中白名单（NFKC 不映射 U+3002，需单独去掉）
def test_normalize_org_strips_fullwidth_period():
    assert normalize_org("人民出版社。") == "人民出版社"
    assert normalize_org("人民出版社．") == "人民出版社"


def test_registry_accepts_publisher_with_fullwidth_period(tmp_path, whitelist_file):
    csv_path = write_registry(tmp_path, row(publisher="人民出版社。"))
    records = load_registry(csv_path, whitelist_path=whitelist_file)
    # 归一只用于比对，展示仍保留原文
    assert records[0].publisher == "人民出版社。"
