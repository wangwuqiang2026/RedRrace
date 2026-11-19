// mock 问答场景：形状严格用契约类型 components['schemas']['AnswerOut'] 构造。
// 纪律（简报 S6/lead 裁决）：
//  - 演示的是版式与信息层级，不是问答能力；answer/claim/quote 一律使用「契约样例」占位文本，
//    不得编写任何看似真实史实陈述的句子（避免假实现/假事实）。
//  - RefusalNotice 的「相近条目参考」卡片 mock 层暂取登记表前 3 条；
//    阶段三接真接口时该列表来源需与后端确认（AnswerOut.suggestions 只是文本数组）。
import type { components } from '../types'
import { SAMPLE_SOURCES } from './sources'

type AnswerOut = components['schemas']['AnswerOut']
type SourceOut = components['schemas']['SourceOut']

const SAMPLE_QUOTE = '〔契约样例引文——演示引用版式；逐字原文随阶段三语料接入后替换〕'

// N-1（review-F2）：不用 `!` 非空断言——source_id 打错必须运行期即炸，
// 而不是带着 undefined 过编译（Citation.source 契约必填）。
const sourceById: Record<string, SourceOut> = {}
for (const s of SAMPLE_SOURCES) sourceById[s.source_id] = s
function byId(id: string): SourceOut {
  const s = sourceById[id]
  if (!s) throw new Error(`mock 场景引用了登记表外的 source_id：${id}`)
  return s
}

/** 示例问题快捷入口（4 个，覆盖 正常/冲突/未收录拒答/无证据拒答 四种版式）。
 * 提问区静态入口 + 拒答场景 suggestions 供数。 */
export const SAMPLE_QUESTIONS: string[] = [
  '湖南郴州建成的长征档案数据库收录情况如何？',
  '关于红军长征参加人数，来源之间有怎样的不同记载？',
  '关于飞夺泸定桥的细节，知识库有什么记载？',
  '关于长征进入四川后的会议记录，知识库有什么可用记载？',
]

/** ① 正常回答场景：两句各带上标编号 [1][2]（AskView 解析渲染 CitationMark）。 */
export const ANSWER_OK: AnswerOut = {
  refusal: false,
  answer:
    '〔契约样例结论句，仅演示句末引用版式，非真实回答〕 [1]。' +
    '〔契约样例第二句——真实回答与引用校验流水线在阶段三接入〕 [2]。',
  citations: [
    {
      index: 1,
      claim: '〔契约样例结论句一〕',
      locator: { quote: SAMPLE_QUOTE, paragraph: 2 },
      source: byId('S001'),
      verified: true,
    },
    {
      index: 2,
      claim: '〔契约样例结论句二〕',
      locator: { quote: SAMPLE_QUOTE, page: 237, heading_path: ['第三章'] },
      source: byId('S002'),
      verified: true,
    },
  ],
  conflicts: [],
  suggestions: [],
  elapsed_ms: 0,
  retrieved_count: 2,
  top_score: 0.72,
  threshold: 0.41,
  gate_note: '',
}

/** 冲突场景：同一主体+谓词两种记载。
 * I-4（review-F2）：sides **故意乱序**（S003 在前）——测试名「mock 数据即乱序输入」名实相符，
 * C3 的卡序断言必须依赖排序代码才成立（删排序即红）。真实契约的 sides 由后端保证升序，
 * 前端排序是双保险；乱序样例正是那层保险唯一可被验证的输入形态。 */
export const ANSWER_CONFLICT: AnswerOut = {
  refusal: false,
  answer: '〔契约样例冲突句——两处记载不一致时该句以存疑样式呈现并并列两个上标〕 [1][2]。',
  citations: [
    {
      index: 1,
      claim: '〔契约样例记载一〕',
      locator: { quote: SAMPLE_QUOTE, page: 12 },
      source: byId('S002'),
      verified: true,
    },
    {
      index: 2,
      claim: '〔契约样例记载二〕',
      locator: { quote: SAMPLE_QUOTE, page: 34 },
      source: byId('S003'),
      verified: true,
    },
  ],
  conflicts: [
    {
      subject: '红军长征',
      predicate: '参加人数',
      sides: [
        {
          index: 2,
          claim: '〔契约样例取值 B——非史实陈述〕',
          locator: { quote: SAMPLE_QUOTE, page: 34 },
          source: byId('S003'),
          verified: true,
        },
        {
          index: 1,
          claim: '〔契约样例取值 A——非史实陈述〕',
          locator: { quote: SAMPLE_QUOTE, page: 12 },
          source: byId('S002'),
          verified: true,
        },
      ],
    },
  ],
  suggestions: [],
  elapsed_ms: 0,
  retrieved_count: 2,
  top_score: 0.72,
  threshold: 0.41,
  gate_note: '',
}

/** ③ 拒答场景：未收录（R3：像说明不像报错；answer 必须空串——契约 model_validator 约束）。
 * J-2：suggestions 即拒答区 chips 的唯一数据源，必须是「点了能问」的示例问题（mock 由本层供同名数据，
 * 真实模式该字段来自后端；阶段三契约将升级为带出处的参考项结构，届时随 gen:api 适配，不手改字段名）。 */
export const ANSWER_REFUSED: AnswerOut = {
  refusal: true,
  refusal_reason: 'not_covered',
  answer: '',
  citations: [],
  conflicts: [],
  suggestions: [SAMPLE_QUESTIONS[0], SAMPLE_QUESTIONS[1]],
  elapsed_ms: 0,
  retrieved_count: 5,
  top_score: 0.28,
  threshold: 0.41,
  gate_note: '当前最高匹配 0.28，低于工作阈值 0.41。',
}

/** ④ 拒答场景之二：无证据（主题有相关材料，但不足以支撑结论）——D4 封闭集补全（lead 2026-11-13）。
 * 句子本体由 RefusalNotice 按 refusal_reason 取封闭集句渲染；本场景只提供契约形态数据。 */
export const ANSWER_REFUSED_NO_EVIDENCE: AnswerOut = {
  refusal: true,
  refusal_reason: 'no_evidence',
  answer: '',
  citations: [],
  conflicts: [],
  suggestions: [SAMPLE_QUESTIONS[0], SAMPLE_QUESTIONS[2]],
  elapsed_ms: 0,
  retrieved_count: 0,
  top_score: null,
  threshold: 0.41,
  gate_note: '未检索到任何候选：检索或范围可能有问题，不调用生成模型。',
}

/**
 * 壳阶段 mock 路由：仅按关键词把请求分发到上述四个版式场景，
 * 不含任何检索/生成逻辑（假检索/假回答生成是全阶段纪律红线）。
 */
export function mockAsk(question: string): AnswerOut {
  if (question.includes('可用记载')) return ANSWER_REFUSED_NO_EVIDENCE
  if (question.includes('不同记载') || question.includes('人数')) return ANSWER_CONFLICT
  if (question.includes('郴州') || question.includes('数据库')) return ANSWER_OK
  return ANSWER_REFUSED
}
