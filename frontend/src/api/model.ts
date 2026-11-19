// 前端 props 模型：组件只认识这里的 camelCase 形状，**不接受后端原始字段名**。
// lead 设计约束（2026-11-13）：字段名读取收敛到 src/api/adapter.ts 唯一一层；
// 阶段三/四/六接真接口或契约再变时，返工范围只有适配层，不烧组件模板与测试。
export type MediaKind = 'book' | 'article' | 'unknown'

export interface SourceCardModel {
  sourceId: string
  mediaKind: MediaKind
  /** 徽标文字（R4：电子书/文章/原始载体值），与图标、颜色并列的第二、三通道 */
  mediaLabel: string
  title: string
  /** 出版社或发布机构 */
  publisher: string
  /** 已按 §8 格式化：年份 4 位、日期 YYYY年M月D日；缺失为「出版年份不详/发布日期不详」 */
  dateText: string
  /** 页码或章节（电子书）／原文链接文字（文章）；null → 组件显示「定位待补」 */
  locatorText: string | null
  /** 可跳转链接（原文或核验页）；null → 回链区显示「来源链接未登记」 */
  url: string | null
  /** 逐字引文（契约 Locator.quote 必填）；演示态为契约样例占位文本 */
  quote: string
}

export interface CitationModel {
  index: number
  /** 该引用支撑的结论句（演示态为契约样例文本） */
  claim: string
  source: SourceCardModel
}

export interface ConflictModel {
  subject: string
  /** 受控谓词中文名 */
  predicate: string
  sides: [SourceCardModel, SourceCardModel]
}

// 阶段三扩第三种原因码：证据有但逐句校验后无保留句（后端 plan 步骤 5b-2）。
export type RefusalReason = 'not_covered' | 'no_evidence' | 'all_claims_rejected' | null

export interface AnswerModel {
  refusal: boolean
  refusalReason: RefusalReason
  answer: string
  citations: CitationModel[]
  conflicts: ConflictModel[]
  suggestions: string[]
  elapsedMs: number
  /** 闸门审计数字（阶段三）：拒答时可解释「最高匹配 x / 阈值 y」，正常回答时为空串 */
  retrievedCount: number
  topScore: number | null
  threshold: number | null
  gateNote: string
}
