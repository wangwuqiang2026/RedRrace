<script setup lang="ts">
// 来源审核台：从 samples.ts 真实数据计算 KPI 的仪表盘。
// KPI 口径（全部运行时计算，不写死）：
//   已登记来源 = SAMPLE_SOURCES.length
//   已核验数   = SOURCE_ARCHIVE 中 verified === true 的数量
//   核心语料数 = SOURCE_ARCHIVE 中 corpusTier === '核心' 的数量
//   关联条目数 = TIMELINE_EVENTS + MAP_POINTS + ROUTE_STOPS + SAMPLE_SOURCES 的总条目数
// 环形进度图用 SVG circle + stroke-dasharray 分段显示核验通过率；
// 数字卡走 createCounter，表格入场走 createStagger，全部收进 motionContext。
// 状态徽标 = 颜色 + SVG 图标 + 文字三通道；行可点击展开 license_note 全文。
// 所有色值走 --dm-* token；reduced-motion 下工厂返回 null，内容完整显示。
import { onMounted, onUnmounted, ref } from 'vue'
import { createCounter, createStagger, motionContext } from '../lib/motion'
import {
  MAP_POINTS,
  ROUTE_STOPS,
  SAMPLE_SOURCES,
  SOURCE_ARCHIVE,
  TIMELINE_EVENTS,
} from '../data/samples'

// —— KPI：全部从真实数据计算 ——
const totalSources = SAMPLE_SOURCES.length
const verifiedCount = SOURCE_ARCHIVE.filter((a) => a.verified).length
const coreCount = SOURCE_ARCHIVE.filter((a) => a.corpusTier === '核心').length
const relatedCount =
  TIMELINE_EVENTS.length + MAP_POINTS.length + ROUTE_STOPS.length + SAMPLE_SOURCES.length

const passRate = totalSources ? verifiedCount / totalSources : 0
const passPercent = Math.round(passRate * 100)

const kpis = [
  { key: 'total', label: '已登记来源', value: totalSources, hint: '来源登记表条目', accent: 'red' },
  { key: 'verified', label: '已核验', value: verifiedCount, hint: '官网直连核验通过', accent: 'green' },
  { key: 'core', label: '核心语料', value: coreCount, hint: 'corpus_tier = 核心', accent: 'amber' },
  { key: 'related', label: '关联条目', value: relatedCount, hint: '时间轴 + 地图 + 路线 + 来源', accent: 'cyan' },
] as const

const tableRows = SAMPLE_SOURCES.map((src, i) => ({
  src,
  archive: SOURCE_ARCHIVE[i],
}))

const expandedRows = ref<Record<string, boolean>>({})
function toggleRow(id: string) {
  expandedRows.value[id] = !expandedRows.value[id]
}

// 环形进度：周长 2πr，r=52 → 约 326.73；两段分别对应已核验与待核。
const radius = 52
const circumference = 2 * Math.PI * radius
const passDash = `${passRate * circumference} ${circumference}`
const pendingDash = `${(1 - passRate) * circumference} ${circumference}`

const pageRef = ref<HTMLElement | null>(null)
let ctx: ReturnType<typeof motionContext> = null

onMounted(() => {
  const page = pageRef.value
  if (!page) return
  ctx = motionContext(page)
  if (!ctx) return
  ctx.add(() => {
    // 数字卡逐个滚动到真实值
    page.querySelectorAll<HTMLElement>('[data-counter]').forEach((el, i) => {
      const to = Number(el.dataset.counter)
      if (!Number.isNaN(to)) createCounter(el, to, { duration: 1 + i * 0.12 })
    })
    // 环形中心百分比
    const pct = page.querySelector<HTMLElement>('[data-counter-percent]')
    if (pct) createCounter(pct, passPercent, { duration: 1.4, suffix: '%' })
    // 表格行错峰浮入
    const rows = Array.from(page.querySelectorAll('.audit-row'))
    if (rows.length) createStagger(rows, { y: 14, stagger: 0.07 })
  })
})

onUnmounted(() => {
  ctx?.revert()
  ctx = null
})
</script>

<template>
  <section ref="pageRef" class="audit-page" aria-labelledby="audit-title">
    <header class="page-head">
      <h1 id="audit-title" class="page-title">来源审核台 / Audit Console</h1>
      <p class="page-sub">
        基于 {{ totalSources }} 条已登记来源的实时核验概览 · 数据取自本地来源登记表
      </p>
    </header>

    <!-- 4 个 KPI 数字卡，值由真实数据计算，数字滚动由 createCounter 驱动 -->
    <div class="kpi-grid">
      <article v-for="kpi in kpis" :key="kpi.key" class="kpi-card" :class="`kpi-${kpi.accent}`">
        <p class="kpi-label">{{ kpi.label }}</p>
        <p class="kpi-value tabular" :data-counter="kpi.value">{{ kpi.value }}</p>
        <p class="kpi-hint">{{ kpi.hint }}</p>
      </article>
    </div>

    <div class="dashboard-row">
      <!-- 环形进度图：绿=已核验，红=待核；颜色+中心百分比数字双通道 -->
      <div class="panel ring-panel">
        <h2 class="panel-title">核验通过率</h2>
        <div class="ring-wrap">
          <svg viewBox="0 0 120 120" width="150" height="150" role="img" :aria-label="`核验通过率 ${passPercent}%`">
            <circle class="ring-track" cx="60" cy="60" :r="radius" fill="none" stroke-width="10" />
            <circle
              class="ring-pass"
              cx="60" cy="60" :r="radius" fill="none" stroke-width="10"
              :stroke-dasharray="passDash" stroke-dashoffset="0"
              transform="rotate(-90 60 60)"
            />
            <circle
              class="ring-pending"
              cx="60" cy="60" :r="radius" fill="none" stroke-width="10"
              :stroke-dasharray="pendingDash"
              :stroke-dashoffset="-passRate * circumference"
              transform="rotate(-90 60 60)"
            />
          </svg>
          <div class="ring-center">
            <span class="ring-percent tabular" data-counter-percent>{{ passPercent }}%</span>
            <span class="ring-caption">{{ verifiedCount }} / {{ totalSources }} 已核验</span>
          </div>
        </div>
        <div class="ring-legend">
          <span><i class="legend-dot legend-pass"></i>已核验 {{ verifiedCount }}</span>
          <span><i class="legend-dot legend-pending"></i>待核 {{ totalSources - verifiedCount }}</span>
        </div>
      </div>

      <!-- 核验说明：纯文字叙事，非装饰 -->
      <div class="panel note-panel">
        <h2 class="panel-title">核验口径</h2>
        <ul class="note-list">
          <li>已核验 = 官网公开文章且 2026-11-13 直连打开核验，正文数字与《数据来源清单.md》一致。</li>
          <li>待核 = 公开出版物，电子版文件待采集，本列先填出版信息核验页；系统只展示逐字引文片段。</li>
          <li>核心语料 = 登记表 corpus_tier 为「核心」的条目；「补充」条目同样逐字挂源，不参与核心计数。</li>
        </ul>
        <p class="note-foot">点击右侧表格任意行，展开该来源的授权说明全文。</p>
      </div>
    </div>

    <!-- 来源核验表格：窄屏可横向滚动 -->
    <div class="panel table-panel">
      <h2 class="panel-title">来源核验明细</h2>
      <div class="table-scroll">
        <table class="audit-table">
          <thead>
            <tr>
              <th scope="col">source_id</th>
              <th scope="col">标题</th>
              <th scope="col">发布机构</th>
              <th scope="col">核验状态</th>
              <th scope="col">授权说明摘要</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="row in tableRows" :key="row.src.sourceId">
              <tr
                class="audit-row"
                :class="expandedRows[row.src.sourceId] ? 'row-expanded' : ''"
                :aria-expanded="!!expandedRows[row.src.sourceId]"
                tabindex="0"
                @click="toggleRow(row.src.sourceId)"
                @keydown.enter="toggleRow(row.src.sourceId)"
                @keydown.space.prevent="toggleRow(row.src.sourceId)"
              >
                <td class="tabular id-cell">{{ row.src.sourceId }}</td>
                <td class="title-cell">{{ row.src.title }}</td>
                <td>{{ row.src.publisher }}</td>
                <td>
                  <!-- 三通道：颜色 + SVG 图标 + 文字 -->
                  <span
                    class="verify-badge"
                    :class="row.archive.verified ? 'verify-pass' : 'verify-pending'"
                    role="status"
                  >
                    <svg v-if="row.archive.verified" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true">
                      <path d="M20 6 9 17l-5-5" />
                    </svg>
                    <svg v-else viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true">
                      <circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16.5v.01" />
                    </svg>
                    <span>{{ row.archive.verified ? '通过' : '待核' }}</span>
                  </span>
                </td>
                <td class="note-cell">{{ row.archive.licenseNote.slice(0, 52) }}…</td>
              </tr>
              <tr v-if="expandedRows[row.src.sourceId]" class="detail-row">
                <td colspan="5">
                  <p class="detail-label">授权说明全文 · {{ row.src.sourceId }}</p>
                  <p class="detail-text">{{ row.archive.licenseNote }}</p>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<style scoped>
.audit-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}
.page-head {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.page-title {
  margin: 0;
  font-family: var(--dm-font-display);
  font-size: var(--text-display);
  line-height: var(--line-height-display);
  font-weight: var(--fw-bold);
  color: var(--dm-ink);
  text-shadow: 0 0 18px var(--dm-glow-red);
}
.page-sub {
  margin: 0;
  font-size: var(--text-body);
  color: var(--dm-red);
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-4);
}
.kpi-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-4);
  border: 1px solid var(--dm-line);
  border-top: 3px solid var(--dm-red);
  border-radius: var(--dm-radius);
  background: var(--dm-bg-glass);
  box-shadow: var(--dm-shadow);
}
.kpi-green { border-top-color: var(--dm-green); }
.kpi-amber { border-top-color: var(--dm-amber); }
.kpi-cyan { border-top-color: var(--dm-cyan); }
.kpi-label {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--dm-ink-dim);
}
.kpi-value {
  margin: 0;
  font-family: var(--dm-font-display);
  font-size: var(--text-display);
  line-height: var(--line-height-display);
  font-weight: var(--fw-bold);
  color: var(--dm-ink);
  text-shadow: 0 0 14px var(--dm-glow-red);
}
.kpi-hint {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--dm-ink-dim);
}

.dashboard-row {
  display: grid;
  grid-template-columns: minmax(280px, 340px) 1fr;
  gap: var(--space-4);
}
.panel {
  padding: var(--space-4) var(--space-6);
  border: 1px solid var(--dm-line);
  border-radius: var(--dm-radius);
  background: var(--dm-bg-glass);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}
.panel-title {
  margin: 0 0 var(--space-4);
  font-family: var(--dm-font-display);
  font-size: var(--text-h2);
  line-height: var(--line-height-h2);
  font-weight: var(--fw-semibold);
  color: var(--dm-ink);
}

.ring-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.ring-wrap {
  position: relative;
  width: 150px;
  height: 150px;
}
.ring-track { stroke: var(--dm-line); }
.ring-pass { stroke: var(--dm-green); stroke-linecap: round; }
.ring-pending { stroke: var(--dm-red); stroke-linecap: round; }
.ring-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
}
.ring-percent {
  font-family: var(--dm-font-display);
  font-size: var(--text-h1);
  font-weight: var(--fw-bold);
  color: var(--dm-green);
}
.ring-caption {
  font-size: var(--text-caption);
  color: var(--dm-ink-dim);
}
.ring-legend {
  display: flex;
  gap: var(--space-4);
  margin-top: var(--space-3);
  font-size: var(--text-caption);
  color: var(--dm-ink-dim);
}
.legend-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: var(--space-1);
}
.legend-pass { background: var(--dm-green); }
.legend-pending { background: var(--dm-red); }

.note-list {
  margin: 0;
  padding-left: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  font-size: var(--text-meta);
  line-height: var(--line-height-meta);
  color: var(--dm-ink);
}
.note-foot {
  margin: var(--space-4) 0 0;
  font-size: var(--text-caption);
  color: var(--dm-cyan);
}

.table-scroll {
  overflow-x: auto;
}
.audit-table {
  width: 100%;
  min-width: 720px;
  border-collapse: collapse;
  font-size: var(--text-meta);
  color: var(--dm-ink);
}
.audit-table th {
  text-align: left;
  padding: var(--space-2) var(--space-3);
  font-weight: var(--fw-medium);
  font-size: var(--text-caption);
  color: var(--dm-ink-dim);
  border-bottom: 1px solid var(--dm-line);
  white-space: nowrap;
}
.audit-table td {
  padding: var(--space-3);
  border-bottom: 1px solid var(--dm-line);
  vertical-align: top;
  line-height: var(--line-height-meta);
}
.audit-row {
  cursor: pointer;
  transition: background 0.2s, box-shadow 0.2s;
}
.audit-row:hover,
.audit-row:focus-visible,
.row-expanded {
  background: var(--dm-bg-elev);
  box-shadow: inset 3px 0 0 var(--dm-red);
}
.audit-row:focus-visible {
  outline: var(--focus-ring-width) solid var(--dm-red);
  outline-offset: var(--focus-ring-offset);
}
.id-cell { color: var(--dm-cyan); white-space: nowrap; }
.title-cell { font-weight: var(--fw-medium); max-width: 260px; }
.note-cell { color: var(--dm-ink-dim); max-width: 300px; }

.verify-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-1);
  font-size: var(--text-caption);
  font-weight: var(--fw-medium);
  border: 1px solid var(--dm-line);
  white-space: nowrap;
}
.verify-pass { color: var(--dm-green); box-shadow: 0 0 10px var(--dm-glow-red); }
.verify-pending { color: var(--dm-amber); box-shadow: 0 0 10px var(--dm-glow-amber); }

.detail-row td {
  background: var(--dm-bg-elev);
  padding-left: var(--space-6);
}
.detail-label {
  margin: 0 0 var(--space-1);
  font-size: var(--text-caption);
  color: var(--dm-cyan);
}
.detail-text {
  margin: 0;
  font-size: var(--text-meta);
  line-height: var(--line-height-meta);
  color: var(--dm-ink);
}

@media (max-width: 1023px) {
  .kpi-grid { grid-template-columns: repeat(2, 1fr); }
  .dashboard-row { grid-template-columns: 1fr; }
  .ring-panel { align-items: flex-start; }
}
@media (max-width: 767px) {
  .kpi-grid { grid-template-columns: repeat(2, 1fr); gap: var(--space-2); }
  .panel { padding: var(--space-4); }
}
</style>
