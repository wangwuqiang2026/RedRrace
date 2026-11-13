"""来源登记表读取与校验的测试（阶段零步骤 2–4）。"""

import pytest
from helpers import row, whitelist_entry, write_registry, write_whitelist

from app.ingestion.registry import (
    DEFAULT_WHITELIST_PATH,
    load_registry,
    load_whitelist,
    normalize_org,
)


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


def test_registry_rejects_missing_publication_date(tmp_path):
    csv = tmp_path / "reg.csv"
    csv.write_text(
        "source_id,title,publisher,publish_date,url_or_path,access_date,"
        "license_note,corpus_tier,media_type\n"
        "S001,红色文化读本（第三卷）,某人民出版社,,/data/raw/ebook_001.pdf,"
        "2026-11-13,公开出版物,核心,电子书\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="publish_date"):
        load_registry(csv)


def test_registry_rejects_ebook_without_publisher(tmp_path, whitelist_file):
    # 电子书必须有出版社；扫描电子书无出版社信息则不得入库
    csv_path = write_registry(tmp_path, row(media_type="电子书", publisher="", publish_date="1985"))
    with pytest.raises(ValueError, match="publisher"):
        load_registry(csv_path, whitelist_path=whitelist_file)


def test_registry_rejects_source_off_whitelist(tmp_path, whitelist_file):
    csv_path = write_registry(tmp_path, row(publisher="某个人自媒体", media_type="文章"))
    with pytest.raises(ValueError, match="whitelist"):
        load_registry(csv_path, whitelist_path=whitelist_file)


# 规则 1：编号唯一
def test_registry_rejects_duplicate_source_id(tmp_path, whitelist_file):
    csv_path = write_registry(tmp_path, row(), row(title="另一读本"))
    with pytest.raises(ValueError, match="source_id"):
        load_registry(csv_path, whitelist_path=whitelist_file)


# 规则 2：标题、链接或路径、获取日期非空
@pytest.mark.parametrize("column", ["title", "url_or_path", "access_date"])
def test_registry_rejects_empty_required_column(tmp_path, whitelist_file, column):
    csv_path = write_registry(tmp_path, row(**{column: ""}))
    with pytest.raises(ValueError, match=column):
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
    with pytest.raises(ValueError, match="publish_date"):
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
    assert DEFAULT_WHITELIST_PATH.name == "来源白名单.yml"
    assert DEFAULT_WHITELIST_PATH.parent.name == "data"


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
    with pytest.raises(ValueError, match="publish_date"):
        load_registry(csv_path, whitelist_path=whitelist_file)


@pytest.mark.parametrize("publish_date", ["1839", "2101", "1000"])
def test_registry_rejects_ebook_year_out_of_range(tmp_path, whitelist_file, publish_date):
    csv_path = write_registry(tmp_path, row(media_type="电子书", publish_date=publish_date))
    with pytest.raises(ValueError, match="publish_date"):
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
