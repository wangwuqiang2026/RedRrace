"""阶段三的默认路径不变量与闸门常量（plan 步骤 3b-1、5b-3）。

为什么单独成模块：步骤 3b-1 要求「默认值合法性写成可断言的常量关系，而不是口头约定」
——参考实现的 `default()` 模式不在可选项集合里、用户 id 哨兵 `-1`，两条都悄悄落到
「空文档列表 → 跳过检索」分支，界面照常出答案（专业、完整、带具体数字，唯独没有引用）。
把这些关系集中一处后，`test_defaults_are_legal_constants_not_hand_waved` 能一次性钉死。
"""

from __future__ import annotations

# 身份：AskRequest.role 的闭集；默认学生必须是其中之一（步骤 3b-1）。
IDENTITY_CHOICES: tuple[str, str, str] = ("学生", "教师", "馆员")
DEFAULT_IDENTITY = "学生"

# 召回条数：默认 8 必须落在允许区间内；区间下界 ≥1，避免「0 条召回」被当成合法范围（步骤 3b-1）。
TOP_K_RANGE: tuple[int, int] = (1, 32)
DEFAULT_TOP_K = 8

# 送重排/证据组装的最大候选数，必须大于默认召回数（保证默认路径不会被窗口截断成空集）。
DEFAULT_MAX_DOCS = 60

# 拒答闸门默认阈值：阶段二 threshold.json 实测 tau=0.41（试点语料，可分性「重叠」未达标）。
# 运行时由 refusal.load_threshold() 从该 JSON 读取并比对标定条件；此常量只是「文件缺失时的
# 明示回退值 + 断言基准」，不得在文件存在时静默覆盖文件里的值（D12 / 步骤 5b-2）。
DEFAULT_THRESHOLD = 0.41

# 结构化语料放宽的 term_floor 起点（步骤 5b-3）：必须低于主阈值，否则放宽永远不会生效；
# 同时 >0，因为 0 表示关闭放宽（边界实测要求）。与主阈值一样由曲线自标定，不抄外部值。
TERM_FLOOR = 0.33

# 提示词版本号：每次改 prompt.py 必须递增并写入 qa_logs.prompt_version（plan 接口约定）。
PROMPT_VERSION = "v1-2026-11-19"


def is_unrestricted(source_ids: list[str], media_types: list[str]) -> bool:
    """来源范围为空的语义是「不限制」，不是「搜 0 个来源」（步骤 3b-1）。

    参考实现把空选择当成「搜 0 个来源」，于是用「知识库没有依据」回答一个根本没检索的问题
    （审计日志里 `best_score: 0.0` 就是这么来的）。这里把判定收成单一函数，供流水线与测试共用。
    """
    return not source_ids and not media_types
