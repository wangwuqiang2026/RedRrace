"""测试辅助：登记行构造、CSV 与白名单样例的写入。

放在本模块而不是 conftest.py：conftest 是 pytest 的插件文件，不应被测试模块 import
（当前能 import 成功只是 rootdir 恰好进了 sys.path，属反模式）。
"""

import copy
import csv

import yaml

# .env / 环境变量里的 8 个键。测试前用它清理宿主环境，否则外部设了 RETRIEVAL_BACKEND
# 之类会让默认值断言误报（终审 M-5）。
CONFIG_ENV_KEYS = [
    "LLM_BACKEND",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "RETRIEVAL_BACKEND",
    "RAGFLOW_BASE_URL",
    "RAGFLOW_API_KEY",
    "DATA_DIR",
]

# 登记表九列，顺序与 load_registry 要求一致
COLUMNS = [
    "source_id",
    "title",
    "publisher",
    "publish_date",
    "url_or_path",
    "access_date",
    "license_note",
    "corpus_tier",
    "media_type",
]

# 一行完整合法的登记数据，可用关键字覆盖任一字段
VALID_ROW = {
    "source_id": "S001",
    "title": "红色文化读本（第三卷）",
    "publisher": "人民出版社",
    "publish_date": "1985",
    "url_or_path": "data/raw/ebook_001.pdf",
    "access_date": "2026-11-13",
    "license_note": "公开出版物",
    "corpus_tier": "核心",
    "media_type": "电子书",
}

# 测试用白名单条目（形态与 backend/data/来源白名单.yml 一致：顶层列表 + name/aliases）。
# registry.py 的规则 9 只放行 verified 为布尔 true 的条目——false、字段缺失、非布尔值
# （"true" / 1 / "yes"）都按未核验拒绝，全称与别名一起拒。故这里三个机构均标 verified=True；
# 需要未核验变体时用 whitelist_entry(name, verified=False) 或 verified=None（删键）构造。
WHITELIST_ENTRIES = [
    {
        "name": "人民出版社",
        "domain": "www.example-pub.com",
        "aliases": ["人民版社", "People's Publishing House"],
        "verified": True,
        "verified_at": "2026-11-13",
        "note": "测试用条目",
    },
    {
        "name": "中共党史出版社",
        "domain": "",
        "aliases": ["中央党史出版社"],
        "verified": True,
        "verified_at": "2026-11-13",
        "note": "测试用条目",
    },
    {
        "name": "新华网",
        "domain": "www.news.cn",
        "aliases": ["新华通讯社", "新华社"],
        "verified": True,
        "verified_at": "2026-11-13",
        "note": "测试用条目",
    },
]


def row(**overrides):
    """返回一行合法登记表数据，可用关键字覆盖任一字段。"""
    merged = dict(VALID_ROW)
    merged.update(overrides)
    return merged


def write_registry(tmp_path, *rows, name="reg.csv"):
    """把若干行数据写成 UTF-8 CSV，返回路径。"""
    path = tmp_path / name
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for item in rows:
            # 字段值给 None 要落成空单元格：str(None) 会写出字面量 "None"，
            # 既骗不过真实采编，也会让「留空被拒」的用例悄悄变形。
            writer.writerow({col: "" if item.get(col) is None else str(item[col]) for col in COLUMNS})
    return path


def write_whitelist(tmp_path, entries=None, name="来源白名单.yml"):
    """写白名单 YAML（顶层机构列表），返回路径。

    entries 为 None 时用默认条目；需要变体（未核验、缺字段、非布尔）时先
    deepcopy(WHITELIST_ENTRIES) 再改，传给本函数。
    """
    data = WHITELIST_ENTRIES if entries is None else entries
    path = tmp_path / name
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    path.write_text(text, encoding="utf-8")
    return path


def write_yaml(tmp_path, data, name="aliases.yml"):
    """把 dict 写成 YAML 文件并返回路径（别名表之类的测试数据）。"""
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def whitelist_entry(name, **changes):
    """改默认白名单里某个条目的字段，返回新的条目列表（用于构造变体）。

    值传 None 表示删除该键，例如 whitelist_entry("新华网", verified=None)。
    """
    entries = copy.deepcopy(WHITELIST_ENTRIES)
    for entry in entries:
        if entry.get("name") == name:
            for key, value in changes.items():
                if value is None:
                    entry.pop(key, None)
                else:
                    entry[key] = value
    return entries
