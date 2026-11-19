// ============================================================================
// src/data/samples.ts —— 统一兜底数据（Task 4）
//
// 数据来源（逐字取自，不得改写成史实陈述）：
//  1. SAMPLE_SOURCES / SOURCE_ARCHIVE 逐字取自
//     frontend/src/api/mock/sources.ts（其自身逐字取自
//     backend/data/来源登记表-样例.csv 的 5 行）；其中 camelCase 映射复用
//     frontend/src/api/adapter.ts 的 toSourceCardModel，低温不自由发挥字段名。
//  2. TIMELINE_EVENTS 的 year/title/detail 逐字取自上述 5 条来源的
//     publish_date、title 与 license_note / 对应原文
//     （S001 → backend/data/raw/articles/S001.html；
//      S004 → backend/data/raw/articles/S004.html；
//      S005 → backend/data/raw/articles/S005.html）。
//  3. MAP_POINTS 的 name/detail 逐字取自上述来源标题/正文中的真实地名与描述；
//     x/y 为 SVG viewBox 0-100 的示意位置（非精确测绘坐标，仅用于可视化落点）。
//
// 说明：每条时间轴/地图数据均附 sourceId，指向登记表 S001-S005。
// 签名稳定，供 Task 5/6 复用。
// ============================================================================
import { toSourceCardModel } from '../api/adapter'
import type { SourceCardModel } from '../api/model'
import { SAMPLE_SOURCES as RAW_SOURCES } from '../api/mock/sources'

/** 5 条已登记来源，复用 adapter 做蛇形→camelCase 映射（真实语料，非编造）。 */
export const SAMPLE_SOURCES: SourceCardModel[] = RAW_SOURCES.map((s) => toSourceCardModel(s))

/**
 * 卡片背面档案元数据：与 SAMPLE_SOURCES 同序同源，逐字登记表字段。
 * SourceCardModel 不含 license_note / corpus_tier / verified，故单独导出。
 */
export const SOURCE_ARCHIVE: {
  sourceId: string
  licenseNote: string
  corpusTier: string
  mediaType: string
  verified: boolean
  publishDate: string
}[] = RAW_SOURCES.map((s) => ({
  sourceId: s.source_id,
  licenseNote: s.license_note,
  corpusTier: s.corpus_tier,
  mediaType: s.media_type,
  verified: s.verified,
  publishDate: s.publish_date,
}))

/**
 * 时间轴事件：年份取自来源 publish_date；标题/详情逐字取自来源 title 与 license_note。
 * 共 6 条，覆盖 5 条登记来源（S001 的「归集数量」与「数据库建成」分列两节点）。
 */
export const TIMELINE_EVENTS: { year: string; title: string; detail: string; sourceId: string }[] = [
  {
    year: '1942',
    title: '红军长征记',
    detail: '公开出版物（2026年修订再版，在2006年版基础上校订并增注释；1942年11月成书为党内参考资料）。',
    sourceId: 'S002',
  },
  {
    year: '2024',
    title: '中国共产党历史（第三卷上册）',
    detail: '经党中央批准由中央党史和文献研究院编写，2024年12月出版发行，记述1978年12月—1989年6月党史，约42万字。',
    sourceId: 'S003',
  },
  {
    year: '2025',
    title: '长沙现存最早的地方志——明·嘉靖《长沙府志》',
    detail: '页内记载点校版2017年9月由湖南师范大学出版社出版、29.7万字，可作该地方志整理本的出版依据。',
    sourceId: 'S005',
  },
  {
    year: '2026',
    title: '湖南郴州建成红军长征档案数据库',
    detail: '湖南省郴州市档案局、市档案馆于今年1月联合启动红军长征档案数据库建设。近日，该数据库全面建成，已正式对外开放。',
    sourceId: 'S001',
  },
  {
    year: '2026',
    title: '归集各类长征档案共2123件',
    detail: '涵盖文书、报刊、书信、地图、照片、音视频、实物、口述档案等多种类别，全面系统梳理了红军长征在郴州的历史轨迹。',
    sourceId: 'S001',
  },
  {
    year: '2026',
    title: '万里征途入诗行',
    detail: '原载《解放军报》2026年11月12日，作者朱延涛 张亚琼，载于人民网·中国共产党新闻网党史频道；2026-11-13 直连打开核验。',
    sourceId: 'S004',
  },
]

/**
 * 地图点位：地名与详情逐字取自来源标题/正文。
 * x/y 为 viewBox 0-100 的示意坐标：郴州（湖南南部）、长沙（湖南东部）、
 * 「甘肃会宁」与「宁夏西吉」不在此列——登记表无对应 sourceId，故不绘制。
 * 点位「核心/补充」语料层级取自登记表 corpus_tier，用于图例着色。
 */
export const MAP_POINTS: {
  name: string
  x: number
  y: number
  detail: string
  sourceId: string
}[] = [
  {
    name: '郴州',
    x: 62,
    y: 70,
    detail: '湖南郴州建成红军长征档案数据库，归集各类长征档案共2123件。（S001）',
    sourceId: 'S001',
  },
  {
    name: '长沙',
    x: 65,
    y: 63,
    detail: '长沙现存最早的地方志——明·嘉靖《长沙府志》，点校版2017年9月由湖南师范大学出版社出版。（S005）',
    sourceId: 'S005',
  },
  {
    name: '红军长征记',
    x: 38,
    y: 46,
    detail: '公开出版物，1942年11月成书为党内参考资料，2026年修订再版。（S002）',
    sourceId: 'S002',
  },
  {
    name: '中国共产党历史',
    x: 30,
    y: 38,
    detail: '经党中央批准由中央党史和文献研究院编写，2024年12月出版发行。（S003）',
    sourceId: 'S003',
  },
  {
    name: '万里征途',
    x: 55,
    y: 42,
    detail: '原载《解放军报》2026年11月12日，载于人民网·中国共产党新闻网党史频道。（S004）',
    sourceId: 'S004',
  },
]
