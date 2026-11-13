"""仓库卫生（审查 C2 的钉死用例）。

事实背景：`extract.py` 曾把人工补录表的默认路径硬编码成 `backend/data/待人工补录.csv`，
于是**每一次全量 pytest 都往项目目录追加若干行 fixture 噪声**——实测从 104 行涨到 115 行、
再涨到 147 行、186 行，真实待办被彻底埋掉，决策记录 002 第 8 条的「转人工补录」
在实操层面等于不存在。

修法是双层：① 默认路径改走 `Config.data_dir`；② `conftest.py` 的会话级 autouse fixture
把 `DATA_DIR` 指到临时目录。下面这些用例负责把结果钉死，而不是靠每条测试自己记得传参。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftest import GUARDED_DIR, dir_state
from helpers import row

from app.ingestion.extract import StubExtractor, extract_cards
from app.ingestion.parse import parse_document
from app.ingestion.registry import SourceRecord

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_suite_did_not_touch_project_data_dir(data_snapshot):
    """跑到这里，项目数据目录必须与会话开始时逐指纹一致（大小 + mtime）。"""
    now = dir_state(GUARDED_DIR)
    diff = sorted(k for k in set(data_snapshot) | set(now) if data_snapshot.get(k) != now.get(k))
    assert diff == [], f"测试改动或新建了 backend/data 下的文件：{diff}"


def test_default_backlog_lands_in_data_dir_not_repo(tmp_path, monkeypatch):
    """不传 backlog_path 时补录表只能落 DATA_DIR，仓库里那份一个字节都不许变。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    source = SourceRecord(**row(source_id="S001", media_type="文章"))
    doc = parse_document(source, FIXTURES / "示例文章.html")
    before = dir_state(GUARDED_DIR)

    quote = "讲习所于一九二五年创设，学员多为产业工人。"
    cards = extract_cards(
        doc,
        source,
        StubExtractor(
            {
                "S001": [
                    {
                        "type": "event",
                        "name": "噪声卡",
                        "summary": "演示",
                        "claims": [
                            {
                                "subject": "讲习所",
                                "predicate": "爱好",  # 受控表外 → 整条丢 → 该来源进补录
                                "value": "读书",
                                "quote": quote,
                                "locator": {"paragraph": 2, "quote": quote},
                                "confidence": 0.9,
                            }
                        ],
                    }
                ]
            }
        ),
    )
    assert cards == []
    assert (tmp_path / "待人工补录.csv").is_file(), "默认落点应在 DATA_DIR 里"
    assert dir_state(GUARDED_DIR) == before, "仓库数据目录被写脏了"


def test_backlog_table_is_ignored_by_git():
    """补录表是运行时数据，必须在 .gitignore 里（审查 C2 的 git 侧已处理，这条防回退）。"""
    text = (BACKEND_ROOT.parent / ".gitignore").read_text(encoding="utf-8")
    assert "backend/data/待人工补录.csv" in text


def test_match_quote_is_the_only_quote_gate():
    """引文闸门只剩一处实现：任何调用点都不该再直接比对 full_text（防两套口径）。"""
    src = (BACKEND_ROOT / "app/ingestion/extract.py").read_text(encoding="utf-8")
    assert "quote not in doc.full_text" not in src
    assert "match_quote(" in src
