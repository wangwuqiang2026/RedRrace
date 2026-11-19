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

/**
 * 研学路线途经点（Task 5）：6 站，名称与 detail 均取自 S001-S005 语料原文中
 * 真实出现的地名/主题节点，逐条附 sourceId；x/y 为 800×600 示意图 viewBox
 * 0-100 百分比示意坐标（非精确测绘坐标，仅用于可视化落点与路径绘制）。
 *
 * 真实性核对：
 *  - 红军长征记 → S002 来源标题（1942年11月成书、2026年修订再版）。
 *  - 娄山关 → S004 原文「攻克娄山关」「苍山如海，残阳如血」「雄关漫道真如铁，而今迈步从头越」。
 *  - 金沙江 → S004 原文「巧渡金沙江」「金沙水拍云崖暖」。
 *  - 泸定桥 → S004 原文「飞夺泸定桥」「大渡桥横铁索寒」（原文并称「大渡桥」）。
 *  - 六盘山 → S004 原文「六盘山上高峰，红旗漫卷西风」「不到长城非好汉」。
 *  - 郴州 → S001 原文「全面系统梳理了红军长征在郴州的历史轨迹」「归集各类长征档案共2123件」；
 *    该站为当代档案归集地，作为叙事终点，非当年行军途经地，detail 中如实说明。
 */
export const ROUTE_STOPS: {
  name: string
  detail: string
  sourceId: string
  x: number
  y: number
}[] = [
  {
    name: '红军长征记',
    detail: '公开出版物，1942年11月成书为党内参考资料，2026年修订再版——由此翻开长征的亲历书写。',
    sourceId: 'S002',
    x: 38,
    y: 46,
  },
  {
    name: '娄山关',
    detail: '「苍山如海，残阳如血」艺术化再现红军攻克娄山关的悲壮情景；「雄关漫道真如铁，而今迈步从头越」写尽征服雄关后的豪迈。',
    sourceId: 'S004',
    x: 50,
    y: 56,
  },
  {
    name: '金沙江',
    detail: '「金沙水拍云崖暖」——巧渡金沙江成功、摆脱追兵的喜悦，被一个「暖」字定格。',
    sourceId: 'S004',
    x: 34,
    y: 60,
  },
  {
    name: '泸定桥',
    detail: '「大渡桥横铁索寒」——飞夺泸定桥战斗中的艰辛与牺牲，蕴含对烈士牺牲的哀悼。',
    sourceId: 'S004',
    x: 32,
    y: 50,
  },
  {
    name: '六盘山',
    detail: '「六盘山上高峰，红旗漫卷西风」——红旗高高飘扬在六盘山上，象征红军旗帜更加鲜艳、信念更加坚定。',
    sourceId: 'S004',
    x: 26,
    y: 34,
  },
  {
    name: '郴州',
    detail: '叙事终点：湖南郴州建成红军长征档案数据库，归集各类长征档案共2123件，全面系统梳理红军长征在郴州的历史轨迹——这是当代的档案归集地，而非当年行军途经地。',
    sourceId: 'S001',
    x: 62,
    y: 70,
  },
]
