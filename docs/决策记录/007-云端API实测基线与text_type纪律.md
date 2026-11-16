# 007 — 云端 API 实测基线、`text_type` 纪律与思考模式

日期：2026-11-16
状态：生效。取代 005 第七节与 006 第一、二节中**与本轮实测冲突的数字口径**（条文不删，按纪律在原文处追加更正指向本记录）。
触发：用户提供 API Key，并指定向量模型 `qwen3.7-text-embedding-flash`、问答模型 `qwen3.8-flash`。本记录只记结论与纪律，**不含密钥明文**。

## 一、取证方式

三轮最小调用探测，脚本与输出全部落在 `%TEMP%\dsh-redtrace-api-smoke\`（探测结束即删，不入库、不入项目目录），密钥从 `backend/.env` 读取，不写进脚本源码。

- 第一轮：三类能力可达性 + 响应形态（12 项）
- 第二轮：专打第一轮暴露的口径冲突（批量、超长、`text_type`、端点等价、思考模式、JSON 抽取，8 组）
- 第三轮：`text_type` 语义与端点默认值、非法值行为、MRL 截断关系、批量边界精确定位、6 文档 × 3 查询的排序 A/B

**全部为 200/400 的真实返回，不是文档推断。** 依「外部数字不作验收依据」纪律，官方文档在本轮的作用是**被实测检验的对象**，凡冲突处一律以实测为准，并保留"厂商可能变更"的失效声明（见第七节）。

## 二、三类能力定稿（原问题：模型名是否真的存在）

| 能力 | 定稿模型名 | 端点 | 实测 |
|---|---|---|---|
| 生成 / 抽取 | `qwen3.8-flash` | `…/compatible-mode/v1/chat/completions` | 200，`finish_reason=stop`，可稳定输出严格 JSON |
| 向量化 | `qwen3.7-text-embedding-flash` | `…/compatible-mode/v1/embeddings` | 200，dim=1024，1024 个分量全非零 |
| 重排 | `qwen3-rerank`（首选） | `…/compatible-api/v1/reranks` | 200，`relevance_score` ∈ (0,1)，排序符合直觉 |
| 重排备选 | `qwen3.7-text-rerank` | 同上 | 200，分布更极端（0.965 / 0.084 / 0.042 vs `qwen3-rerank` 的 0.851 / 0.322 / 0.224） |

`gte-rerank-v2` 已下线（006 第二节更正 2），维持禁用。同一把 key 通吃三类能力，无需第二把。

## 三、实测推翻的六条既有口径（逐条列原口径）

| # | 原口径（出处） | 实测 | 后果 |
|---|---|---|---|
| 1 | 单次批量「最大 20 行」（005 第七节官方规格表） | **25**：25 条 OK、26 条 400 `batch size is invalid, it should not be larger than 25`；21 条与 40 条亦分别 OK/400 | `EMBEDDING_BATCH_SIZE=16` 仍安全，但校验逻辑与文档措辞要按 25 写；**不得**因"官方说 20"就把 21～25 条的批次判为非法 |
| 2 | 单行上限 128,000 token（005 第七节） | 服务端实际硬边界 **131,072** token，且**超长明确 400、不静默截断**：`This model's maximum context length is 131072 tokens. However, your request has 400047 input tokens` | 客户端预检阈值取 128,000 可保留（留 3,072 余量），但要写成"经验余量"而非"官方上限" |
| 3 | 一条超长可能污染同批（005 第五节担忧，未验证） | 同批内混入一条超长 → **整批 400、`count=0`**，服务端不做部分返回 | 好消息（无静默错位），坏消息（单条拖垮整批）：必须**逐条预检后再发批**，不能"先发再看" |
| 4 | 重排单文档 4,000 token（006 第 1.2 节规格表） | 该部署实际 **32,768** token：4 万汉字 400 `maximum context length is 32768 tokens`；1.2 万汉字 200 | 「超限返回 400 而非截断」这一结论**成立**（006 硬约束 3 不变），仅数字要更正；预检仍必需，因为一旦超限整次重排失败并触发回退 |
| 5 | 重排 documents ≤500（006 第 1.2 节） | **证实**：501 条 400 `batch size of documents … not be empty or larger than 500` | `RERANK_MAX_DOCS=60` 远低于上限，安全 |
| 6 | 「切 embedding 端点等于换向量空间，必须重建索引」（005 第三节第 1 条的推论，本轮前属推测） | **量级要大幅下修**：同 `text_type` 下兼容层与原生端点 cos = 0.998478 ~ 1.000000，差异约 1e-3；真正危险的是 `text_type`（下一节，差异 0.075） | 该纪律**保留但重新排序**：`text_type` 是主因，端点变更是次因（仍判索引过期，理由是阈值复现性而非"空间突变"） |

## 四、新增纪律：`text_type` 显式化并进入索引签名（本轮最重要发现）

实测默认值**不对称**，这是静默降质的入口：

| 调用 | 参照 | cos |
|---|---|---|
| 兼容层不传 `text_type` | 兼容层 `text_type=query` | **0.999095**（≈默认即 query） |
| 兼容层不传 `text_type` | 兼容层 `text_type=document` | **0.924648** |
| 原生端点不传 | 兼容层 `document` | **1.000000**（原生默认即 document） |
| 原生端点不传 | 兼容层 `query` | 0.925438 |

即：**同一个模型，走不同端点而不显式声明 `text_type`，拿到的向量相差 cos≈0.925（约 7.5% 的角度偏差）**，且两次调用都不报错。这属于参考实现 §2.1 那一类"通道在跑但结果不对"的事故形态。

对尺子的实际冲击（6 文档 × 3 查询 A/B，全部为本机自测数字）：

| 组合 | Hit@1 | top1 均分 | 全对相似度 mean | min |
|---|---|---|---|---|
| doc=document, q=query（**推荐**） | 3/3 | 0.7035 | 0.3928 | 0.2482 |
| doc=默认, q=默认 | 3/3 | 0.7309 | 0.3945 | 0.2524 |
| doc=document, q=document | 3/3 | 0.7473 | **0.4694** | **0.3328** |

两点必须如实写清，不得夸大：

1. **这个迷你样本区分不出命中率高低**（五种组合 Hit@1 全为 3/3）。因此本轮**不声称** `text_type` 提升了命中率；它证明的是**分数尺度被搬动**——`document-document` 把 mean 从 0.3945 抬到 0.4694、min 从 0.2524 抬到 0.3328。
2. 正因尺度被搬动，**同一条拒答阈值在不同 `text_type` 组合下切掉的候选比例完全不同**（例如 0.33 这条线，在推荐组合下会切掉一部分负例，在 `document-document` 下几乎全放行）。所以步骤 6b 标定的阈值**只在标定时所用的 `text_type` 组合下有效**，`text_type` 必须进向量配置签名（005 第三节第 1 条的签名从「model + dim + 基址哈希」扩为「model + dim + 基址哈希 + **document/query 两侧的 `text_type`**」）。

实现要求（写进 `retrieval/embedding.py`，非可选）：

- 入库调 `embed(documents, text_type="document")`，查询调 `embed(query, text_type="query")`，**两处都显式传参，禁止依赖默认值**；
- 非法值行为已实测：`text_type=Document` / `docs` / `quer` 一律 400 并回显 `its value should be in ['document', 'query']` —— **拼错会炸，不会静默降级**，所以启动时最小调用能兜住配置错误（阶段八步骤 3b 自检项）；
- 兜底档 `LocalEmbedder`（bge-m3）无此参数，故 `text_type` 组合必须作为签名的一部分参与跨档比较，避免"本地档建的索引被 API 档阈值判定"。

## 五、新增纪律：`qwen3.8-flash` 是混合思考模型，思考默认开着

实测证据：让它只回复"收到"两个字 → `completion_tokens=30`，其中 `reasoning_tokens=26`。即**默认形态下每个请求都为不产出的推理 token 付费**。

四种参数实测（同 prompt，temperature=0）：

| 参数 | HTTP | completion | reasoning | 耗时 |
|---|---|---|---|---|
| 不传（默认） | 200 | 18 | 14 | 1612 ms |
| `enable_thinking=false` | 200 | 1 | **None** | 1544 ms |
| `thinking={type:disabled}` | 200 | 1 | None | 1986 ms |
| `reasoning_effort=minimal` | 200 | 21 | 18 | 1821 ms（**反而更多**） |

结构化抽取场景（要求严格 JSON、双事实文本）：默认 `reasoning=98`、3897 ms，输出可解析 JSON 2 条；`enable_thinking=false` 无 reasoning、2698 ms，**同样输出可解析 JSON 2 条**。

纪律（阶段一抽取与阶段三生成共用）：

1. 默认 **`LLM_ENABLE_THINKING=false`**：本项目两条主链路都是「受约束抽取 / 只准用给定证据生成」，不需要自由推理；实测该档不降低 JSON 合规性、省约 1/3 时延与全部 reasoning token。
2. **不得**用 `reasoning_effort` 当关闭开关（实测无效且增加 token）。若将来要开启思考，须另立决策记录并说明为何受约束生成需要自由推理。
3. 该参数是**供应商扩展参数**，OpenAI 官方 schema 无此项 → 属对 005「供应商中立性」的一处修正：中立性现在只在 `chat` / `embeddings` 的**请求体核心字段**层面成立，`enable_thinking`、`text_type` 两处需 `LLM_*` / `EMBEDDING_*` 组内各自的开关承载，换供应商时按能力表逐项确认（记入阶段八运行手册的"换供应商必查清单"）。
4. 成本口径（阶段九 3b 第 ④ 类）：token 计费必须**分列 reasoning token**，否则阶段一 171 单元的抽取成本会被低估数倍。

## 六、向量侧其他三条实测事实

1. **不得断言两次调用向量逐位相等**：同文本同参数两次调用 cos = 0.999095（≈1 但非 1），服务端存在非确定性。步骤 3b 的响应完整性测试因此**只断言条数 / 维度 / 全零三分量检查**，不断言数值相等；索引重建的可复现性也只能按 cos 阈值（建议 ≥0.999）而非哈希一致来验。
2. **空串输入不报错且返回全非零向量**：`input=[""]` → 200，dim=1024、1024 个分量全非零。这类向量看似正常却无语义，是**垃圾进、正常出**的静默污染。要求：`embed()` 内对空 / 纯空白输入**先显式拒绝**，不得依赖服务端；空检索串的条目在建索引时报错而非跳过（与"宁可建索引失败"纪律同源）。
3. **`dimensions` 是 MRL 前缀截断，不是独立模型**：`dimensions=768` 生效且 `cos(v1024[:768], v768)=0.999114`；`dimensions=512` 同理 0.999086。所以改维度**不能**靠本地截断复用旧向量（数值虽近似但不等价，且相似度分布会挪动）：`EMBEDDING_DIM` 变更仍判索引过期并重标阈值。

## 七、失效声明（厂商侧可能变更，本记录不视为永久事实）

本轮全部数字来自**当日单一账户、单一地域端点**的探测。批量 25、上下文 131,072、rerank 32,768 三个"服务端真实边界"都可能随模型版本变更；`text_type` 的默认值不对称尤其可能是当前部署的实现细节。**阶段八步骤 3b 的 `doctor` 自检命令必须重新探一遍这三条边界并打印差异**，而不是引用本记录。

## 八、配置字段最终清单（12 → 14，含两处默认值定稿）

```ini
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=<注入，绝不入库>
LLM_MODEL=qwen3.8-flash
LLM_ENABLE_THINKING=false        # 新增，本记录第五节
EMBEDDING_BACKEND=api
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_API_KEY=<同上>
EMBEDDING_MODEL=qwen3.7-text-embedding-flash
EMBEDDING_DIM=1024
EMBEDDING_BATCH_SIZE=16          # 服务端硬边界实测 25
EMBEDDING_TIMEOUT_S=30
EMBEDDING_TEXT_TYPE_DOCUMENT=document   # 新增，第四节
EMBEDDING_TEXT_TYPE_QUERY=query         # 新增，第四节
RERANK_BACKEND=api
RERANK_BASE_URL=https://dashscope.aliyuncs.com/compatible-api/v1
RERANK_API_KEY=<同上>
RERANK_MODEL=qwen3-rerank
RERANK_TIMEOUT_S=15
RERANK_MAX_DOCS=60               # 服务端硬边界实测 500
```

`backend/.env` 已按此建立（`.gitignore:12` 覆盖，`git ls-files` 确认未被跟踪）。**待办**：`app/core/config.py` 现仅 8 个字段（`llm_*` 4 条、`retrieval_backend`、`ragflow_*` 2 条、`data_dir`），`extra="ignore"` 使上述键当前被静默忽略——新增 14 个字段是本记录落地的第一步代码改动。

## 九、安全与密钥处置

1. 密钥以聊天明文出现过：**建议按最小权限、可轮换的方式重新签发一把仅含所需模型的 key**，并在答辩材料中不出现 key。
2. key 三组字段（`LLM_API_KEY` / `EMBEDDING_API_KEY` / `RERANK_API_KEY`）保持分组、同值注入，用于逐组关闭的降级演练（005 第六节第 3 条不变）。
3. 云端外发的合规披露仍按 005 第 7.5 条：阶段七步骤 5 的「云端处理与数据边界」一节必须写明本轮实测确认的**地域端点**（`dashscope.aliyuncs.com`，中国大陆）与三类能力共用同一账户这一事实。

## 十、未决项

1. `qwen3.8-flash` 与 `qwen3.7-text-embedding-flash`、`qwen3-rerank` 的**单价**未取到（官方定价页本轮未核）→ 阶段九 3b 的 ④ 类成本只能按实测 token 数 ×「价格待查」记账，不得填估值。
2. 171 单元真实抽取的 token 总量与耗时未测 → 建议先取 3 个单元做试点外推，再决定是否一次性全量跑（全量属云端付费操作，需用户点头）。
3. `text_type` 对**本项目全量语料**命中率的影响未测（第四节迷你样本无区分度）→ 归阶段二步骤 6b / 6c，与阈值曲线一起出。
4. 思考模式开启后抽取质量是否更高（尤其多事实长文本）未测 → 属质量-成本权衡，须用阶段一抽检指标（引文定位率）判，不凭偏好定。
5. 限流实测（RPM 24,000 / TPM 1M 为官方口径）未做，并发批量建索引时的 429 行为未测 → 归阶段八步骤 4 冷启动与阶段九降级演练。

## 十一、回滚

- 关闭思考若引发质量问题：`LLM_ENABLE_THINKING=true`（单项可回滚，不影响其他）。
- `text_type` 若与兜底 `LocalEmbedder` 档冲突：`EMBEDDING_TEXT_TYPE_DOCUMENT` / `_QUERY` 置空表示不传该参数，但此时**签名仍记录"未声明"**，索引判过期、阈值重标——不得静默沿用。
- 整体回滚到「不下模型、不走 API」：按 005 第四节的 `local` 档与第五节的回滚路径，需自行下载权重，属离线场景专用。
