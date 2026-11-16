# 决策记录 004 —— 问答与检索模块参考 citeask（2026-11-16）

- **日期**：2026-11-16
- **触发**：用户指令「问答模块可以参考 https://github.com/wangwuqiang2026/citeask，现在先修改计划文档」。本轮**只改文档，不改代码、不加依赖**。
- **决定**：**参考其工程做法与已量化踩坑，不引入其依赖、不复制其代码进本仓。** 借鉴内容按阶段落成 plan.md 里能失败的测试（见第四节），外部数字一律标注为「外部语料实测，不作本项目达标依据」。
- **变更性质**：不换技术栈、不动契约。plan「需求 → 阶段追踪表」与五条不变契约（全局约束 10）未改动；阶段二/三/八/九的原有步骤编号未重排，新增项用 `3b / 4b / 5b / 6b / 6c / 3b` 插入式编号（既有文档对「阶段二步骤 1」「阶段三步骤 4」「阶段三步骤 5」等存在交叉引用，重排会打断引用链）。
- **一处实质口径修正**：plan 阶段三步骤 5 原文「最高**重排分**低于阈值」改为「最高**综合分**低于阈值」。依据见第三节第 3 条——重排改写参与闸门判定的分数会让已标定阈值静默失效。本条为本记录里唯一的**原计划文字改写**，理由与影响已在 plan 阶段二步骤 4b 同步写明。

---

## 一、取证事实（2026-11-16 本机与在线实测，均可复核）

| 项 | 实测值 | 取数方式 |
|---|---|---|
| 仓库 | `wangwuqiang2026/citeask`，公开，默认分支 `main`，创建 2026-10-17，最后推送 2026-10-20，`size` 20,226 KB | GitHub API `repos/...` |
| 许可 | **Apache License 2.0** | API `license.spdx_id`；仓库根 `LICENSE.txt` + `NOTICE` |
| topics | `document-qa`、`fastapi`、`ocr`、`rag`、`rag-evaluation`、`react` | API `topics` |
| 本机位置 | `D:\Code\VibeCoding\kotaemon` —— 即该仓库的完整 clone | `git -C ... remote -v`：`origin` = citeask，`upstream` = `Cinnamon/kotaemon` |
| 上游基线 | kotaemon `v0.12.0`（commit `9ad3e4e`，上游 main） | 其 `MODIFICATIONS.md` 首部声明 |
| 改造记录 | `MODIFICATIONS.md` **2888 行 / 90 个小节**，逐条含现象、定位过程、修复、实测表 | `(Get-Content ...).Count` |
| 本地 HEAD | `3b6afdc docs: 记录 §5.38…并同步当前用例数 446` | `git log --oneline -3` |
| 关键文件存在性 | `libs/kotaemon/kotaemon/abstain.py`(17,222B)、`rerankings/local_lexical.py`(4,820B)、`libs/ktem/ktem/utils/selector.py`(4,437B)、`tools/eval_retrieval.py`(30,582B)、`tools/doctor.py`(18,835B)、`tools/trace_report.py`(4,633B)、`libs/kotaemon/tests/test_docstore_cjk_fts.py`(3,985B)、`libs/ktem/ktem_tests/test_stored_paths.py`(3,985B)、`ktem_tests/test_file_selector.py`(5,399B) | `Test-Path` + 文件大小逐项实测 |
| 拒答常量 | `abstain.py:51 NO_SIMILARITY = -1.0`；`:56 DEFAULT_TERM_FLOOR = 0.33`；`:375 def should_refuse(scores, threshold, documents, question, term_floor)`；`threshold <= 0` 关闭分数闸门（空召回仍拒答）；配套 `entity_terms()`、`row_looks_tabular(min_numbered_share=0.6)`、`specific_term_evidence()`、`named_file_evidence()` | `Select-String` 读原文行号 |
| 技术栈不同构 | 它：FastAPI `/api/v1`（43 接口、SSE、HttpOnly Cookie、RBAC）+ **React 18 SPA** + LanceDB + Chroma + SQLite + theflow + Gradio 兜底界面；本项目：FastAPI + **Vue3/Vite** + SQLite + FAISS 自研管线 | 其 README「它是怎么工作的」表 + 本项目 `backend/app/` 实测目录树 |

> 说明：`raw.githubusercontent.com` 与 GitHub API 匿名限额在本机网络下均失败过（`403 rate limit exceeded`），最终经 `cdn.jsdelivr.net` 取 README 原文、经本机 clone 取全部细节。**参考取证以本机文件为准**，网络材料只作补充。

## 二、为什么不接入（准入条件逐条判）

| 准入条件 | 判 | 依据 |
|---|---|---|
| 1 不破坏引用链 | ⚠️ 有条件 | 它的引用定位粒度是文档块 + 页码，**没有「主体—谓词—取值」事实条目**，也没有冲突两来源并列；接进来仍需本项目自建这两层，与决策记录 001 对 RAGFlow 的反证同理 |
| 2 不越硬件档 | ✅ | 它本身 CPU 可跑、离线可跑；不构成排除理由 |
| 3 有降级路径 | ⚠️ | 它的默认向量后端在 `DASHSCOPE_API_KEY` 缺失时回落本地 FastEmbed，而 `MODIFICATIONS.md` §4.3 实测「FastEmbed 的中文模型在其本机不可用」；降级链在本项目未验证 |
| 4 接口向后兼容 | ❌ | 接入即整体替换 `retrieval/backend.py` 之上的证据结构，与五条不变契约的「字段名与路径」相冲；前端从 Vue3 换 React 直接推翻阶段零F 已关账成果（118 vitest + 19 e2e 红线） |
| 5 可回滚 | ❌ | 依赖树含 LanceDB/Chroma/theflow/Gradio，删依赖即删代码不彻底（其数据目录 `ktem_app_data/` 实测曾达 7.1 GB，§6.3） |

**结论**：4、5 两条不满足 → 按「五条全满足才可加」的准入纪律，**不引入**；只吸收方法学与踩坑（第三节）。远期若真要整体接引擎，走 `search(问题, 条数) -> list[Hit]` 适配器 + 新决策记录 **008**（005 已被向量化选型、**006 重排、007 API 实测基线占用**，2026-11-16 顺延），上层不动（与 001 第六节同一钩子）。

## 三、吸收进计划的内容（每条都要能失败）

1. **检索静默失效 = 最危险失败模式**（其 §2.1–2.5、§5.16）。默认值不在合法集合内、State 哨兵 `-1`、空文件列表三种写法都落到「跳过检索」，模型凭预训练知识作答且**格式完整、数字具体**，只有引用栏空。对应新增：plan 阶段三**步骤 3b**（默认路径端到端用例 + 常量可断言 + 空选择语义为「不限制」）。
2. **中文稀疏通道恒 0 条**（其 §5.15，`tokenizer_name="en_stem"` → 整句一个 token，`Got 0 from docstore` 长期无人注意）。对应新增：plan 阶段二**步骤 3b**（`search_bm25_only` 必须有非 0 命中；`build_index.py` 打印两条通道各自命中数）。
3. **两把尺子不得混用**（其 §5.9：重排保留原相似度、词法分另存 `metadata["rerank_score"]`，否则阈值静默失效；§5.15 第 3 点：关键词命中无相似度、占满上下文则闸门全放行；§5.23/§5.32：面板把两种尺子混在一列，出现「0% 却被引用」）。对应新增：plan 阶段二**步骤 4b**（`Hit.score` 唯一参与闸门、新增 `Hit.rerank_score`、`sparse_score` 用 `None` 不用 `-1`、稀疏名额 `k//2`）+ 阶段三步骤 5 措辞修正。
4. **阈值靠曲线选点，不靠抄**（其 §5.8：0.42→75%、0.45→91.7% 且误拒 0%、0.53 误伤最低正分 0.473；表格行相似度天然 0.28–0.42，故加「罕见实体词 + 表格式行 + 少数候选（≤30%）+ floor 0.33」放宽；关掉表格式行会把 91.7% 拉到 83.3%）。对应新增：plan 阶段二**步骤 6b**、阶段三**步骤 5b**（第 3 条边界要求实测两个方向）。
5. **拒答必须可审计**（其被拒查询写 `abstained_queries.jsonl`：时间、问题、最高分、阈值、`reason`）。对应新增：plan 阶段三**步骤 5b** 第 2 条（`retrieved_count` / 最高综合分 / 阈值 / 三个原因码，含 `all_claims_rejected`）。
6. **回链路径要持久**（其 §5.12：裸哈希无扩展名 + 指向会被删的工作副本 → 预览永久失效，日志刷 `does not exist`）。对应新增：plan 阶段三**步骤 4b**（回链由 `source_id` 现算 `data/raw/`、`data/parsed/`，禁止存绝对/临时路径，配重建后仍存在的测试）。
7. **检索层零 token 评测**（其 §9.1–9.3：Hit@k / MRR / 关键事实覆盖率三指标；匹配细节两处坑——文件名标点被洗、OCR 任意换行需去空白；§9.3 实测加一个无关文件后 Hit@5 从 100% 掉到 81.5% 而 Hit@1 基本不变）。对应新增：plan 阶段二**步骤 6b**（第 1、3 点）与**步骤 6c**（迷你库 vs 全量库对照口径）、阶段九**步骤 3b**（两层评测 + 每数字配复现命令）。
8. **自检命令**（其 `tools/doctor.py` 回答「文件是否真进索引、配置是否真生效」；§2.7–2.10 修「上传成功但索引 0 块」的幽灵文件）。对应新增：plan 阶段八**步骤 3b**（五项打印，任一为 0 判失败）。
9. **隐性成本要显式开关**（其 §5.10：默认开的「每块调一次 LLM 打分」使 1 次/3291 token/P50 2564ms → 11 次/9043 token/2955ms）。对应新增：plan 阶段八步骤 4 与阶段九步骤 3b 第 3 点（默认关闭、开关进 `.env.example`）。
10. **切块粒度靠 A/B**（其 §5.7：按页成块 55.6%/0.707 → 512/64 88.9%/0.933；§5.9 同时诚实记录小语料上重排「无收益、P95 略升」）。对应新增：plan 阶段二**步骤 3c**（两档对比 + 允许写「无收益」）。

## 四、代码落地清单（本轮未动代码，留给阶段二/三）

| 计划新增项 | 要新建的测试/脚本 | 断言要点 |
|---|---|---|
| 阶段二 3b | `backend/tests/test_search_recall.py` 增例 | 只走稀疏仍命中；专名走精确匹配命中；词典吃进 `aliases.yml` |
| 阶段二 3c | `scripts/build_index.py` + 开发集 | 两档切块的 Hit@1/MRR 对照表落评测报告 |
| 阶段二 4b | `backend/tests/test_search_recall.py` 增例 | 重排前后 `Hit.score` 逐题相同；`sparse_score is None` 不进分数列 |
| 阶段二 6b | `app/retrieval/calibrate.py` | 阈值曲线表（拒答率/误拒率）；三指标；复现命令写 RUNBOOK |
| 阶段二 6c | 同上 | 迷你库 / 全量库两口径 Hit@8 同时记录 |
| 阶段三 3b | `backend/tests/test_ask_examples.py` 增例 | 不带可选字段提问 → `citations` 非空、`verified` 全真、`retrieved_count > 0` |
| 阶段三 4b | `backend/tests/test_citation_verify.py` 增例 | 重建索引后回链目标文件仍存在；两类载体不混用 |
| 阶段三 5b | `backend/tests/test_refusal.py` 增例 | 拒答路径 LLM 调用次数为 0；`term_floor=0` 关闭放宽；实体词放宽两向边界 |
| 阶段八 3b | `backend/scripts/doctor.py` | 五项实测打印；三表计数与索引计数一致；中文问句双通道命中数 |
| 阶段九 3b | `backend/scripts/eval_run.py --layer retrieval` | 与阶段二 6b 同一评测集；检索层不调模型 |

## 五、对既有记录的补充与未决项

- **决策记录 001 未决项 3（Python 3.13.5 与基线依赖的 wheel 兼容性）—— 2026-11-16 本机实测收口，结论：不需要降级 Python**。
  参考实现的 §6.1 结论（`onnxruntime 1.19.2` 无 cp313 轮子 → 只能用 3.10）源于**其上游把 onnxruntime 钉在 `<1.20`** 这一约束；本项目无此约束，因此结论不可照搬。本机 `python -m pip install --dry-run` 实测（Python 3.13.5）：

  | 包 | dry-run 结果 | 备注 |
  |---|---|---|
  | `faiss-cpu` | Would install **1.16.0** | 且 `--only-binary=:all:` 通过，确为轮子 |
  | `rank-bm25` | Would install **0.2.2** | 纯 Python |
  | `jieba` | Would install **0.42.1** | **仅 sdist**（`--only-binary=:all:` 报 no matching distribution，与 2019 年后未发轮子一致），安装需构建 |
  | `sentence-transformers` | Would install **6.3.0** | — |
  | `torch` | Would install **2.15.0** | — |
  | `onnxruntime` | 本机**已安装 1.31.0** | `pip list` 实测，非推算 |
  | `llama-cpp-python` | Would install **0.3.37** | 与其 §5.2「无 Windows 轮子」不同：本项目无版本钉死 |

  **取证边界（必须如实标注）**：以上为 `--dry-run` 与已装包清单级证据，**证明「解析与轮子可得」，尚未证明「装完能 import」**。真实安装与 import 冒烟仍按 plan 阶段二步骤 3 前置执行；未决项 3 由「是否存在轮子」降级为「装完是否可用」。**2026-11-16 追加：因决策记录 005 取消默认下载模型权重，本表的 `faiss-cpu` / `sentence-transformers` / `torch` / `llama-cpp-python` 四项降级为「兜底路线才需要」的可选项，默认路径只安装主依赖（`jieba` + `rank_bm25` + `httpx` + `numpy`）。**
- **决策记录 002 的可验证边界不变**：本轮新增项都不依赖 LLM key（稀疏通道自检、阈值标定、回链持久性、不调模型断言均可用桩件测）；凡涉及真实抽取质量的达标判定，仍按 002 表格第 157 行「拿到 key 前不得宣布达标」。

| # | 未决项 | 处理时点 |
|---|---|---|
| 1 | 本项目自己的拒答阈值与 `term_floor` 工作点（外部值只作起点） | 阶段二步骤 6b、阶段三步骤 5b |
| 2 | BM25 + jieba 在本项目中文语料上是否真的非 0 命中（外部事故的同类风险） | 阶段二步骤 3b |
| 3 | ~~cp313 轮子可用性~~ → 轮子已实测齐（上表）；**剩余**为真实安装后的 import 与 CPU 推理冒烟，含 bge-m3 经 hf-mirror 的下载稳定性（原 001 未决项 6） | 阶段二步骤 3 前置、阶段八步骤 3b |
| 4 | 检索串切块两档的收益差（本项目按条目拼装，与外部按页分块不可比） | 阶段二步骤 3c |
| 5 | 稀疏名额上限取 `k//2` 是否过松/过紧 | 阶段二步骤 4b 实测后在 002 追加口径 |
| 6 | 方志类条目行的「表格式行」判据（≥3 字段、≥60% 含数字）是否适配本项目快照结构 | 阶段三步骤 5b 第 3 条实测 |
| 7 | ~~生成后端仍未选定~~ **已裁决（2026-11-16，见决策记录 005）**：生成走**在线 API**、向量化亦走 **API 且不下载模型权重**，本地 bge-m3 / GGUF 降为兜底档，BM25-only 为离线降级线。本机浅层扫描未见 `.gguf` 文件（实测），默认路径不需要它 | 具体 `LLM_*` 与 `EMBEDDING_*` 配置值待用户提供，见 005 第六节 |

## 六、回滚方式

1. 文档回滚：`git revert <本轮提交>`，plan.md 的阶段二/三/八/九新增步骤与本记录一并撤销，阶段三步骤 5 恢复原文「最高重排分」；
2. 无副作用面：本轮**未改代码、未改 `pyproject.toml`、未改 `.env.example`、未引入依赖**，因此运行时行为零变化，前端契约与 `openapi.json` 不受影响（阶段三步骤 5b 新增的 `retrieved_count` 等字段是**计划要求**，尚未实现，实现时按契约优先流程改 `qa/schemas.py` 后重跑 `pnpm gen:api`）；
3. 若将来改判为「接入」：走准入五条 + 新增决策记录 **008**（005 向量化、006 重排、007 API 实测基线均已占用编号）+ 保留 Apache-2.0 许可与 `NOTICE` 归属，且**不得替换五条不变契约与 Vue3 前端**。
