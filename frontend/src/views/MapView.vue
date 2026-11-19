<script setup lang="ts">
// 事件地理分布：程序化 SVG 中国示意轮廓（viewBox 0 0 800 600，无任何外链图片），
// MAP_POINTS 点位双层脉冲（dm-pulse），hover/focus 显示含来源标题的详情 tooltip，
// 点击点位高亮并把来源详情固定在侧栏。图例颜色对应 corpus_tier 核心/补充。
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { createReveal, motionContext } from '../lib/motion'
import { MAP_POINTS, SOURCE_ARCHIVE, SAMPLE_SOURCES } from '../data/samples'

const mapRef = ref<HTMLElement | null>(null)
const activeId = ref<string | null>(null)
const hoverId = ref<string | null>(null)
let ctx: ReturnType<typeof motionContext> = null

const sourceById = new Map(SAMPLE_SOURCES.map((s) => [s.sourceId, s]))
const archiveById = new Map(SOURCE_ARCHIVE.map((a) => [a.sourceId, a]))

const points = MAP_POINTS.map((p) => ({
  ...p,
  tier: archiveById.get(p.sourceId)?.corpusTier ?? '补充',
  title: sourceById.get(p.sourceId)?.title ?? p.name,
}))

const activePoint = computed(() => points.find((p) => p.sourceId === activeId.value) ?? null)
const hoveredPoint = computed(() => points.find((p) => p.sourceId === hoverId.value) ?? null)

function select(id: string) {
  activeId.value = activeId.value === id ? null : id
}

function tierClass(tier: string): string {
  return tier === '核心' ? 'tier-core' : 'tier-supplement'
}

// SVG viewBox 0-100 的百分比 → 800x600 画布坐标
function px(x: number): number {
  return (x / 100) * 800
}
function py(y: number): number {
  return (y / 100) * 600
}

onMounted(() => {
  const map = mapRef.value
  if (!map) return
  ctx = motionContext(map)
  if (!ctx) return
  ctx.add(() => {
    createReveal(map, { y: 16 })
  })
})

onUnmounted(() => {
  ctx?.revert()
  ctx = null
})
</script>

<template>
  <section ref="mapRef" class="map-page" aria-labelledby="map-title">
    <header class="page-head">
      <h1 id="map-title" class="page-title">事件地理分布 / Map</h1>
      <p class="page-sub">点位为登记来源中可考的地名/主题落点，轮廓为程序化 SVG 示意图。</p>
    </header>

    <div class="map-layout">
      <div class="map-frame">
        <svg viewBox="0 0 800 600" class="map-svg" role="img" aria-label="中国示意轮廓与来源点位分布">
          <!-- 抽象的中国轮廓：西北—华北—东北—东南沿海—西南的折线闭环，非精确测绘 -->
          <path
            class="land"
            d="M138 150 L196 104 L262 120 L318 92 L372 116 L430 96 L492 118 L548 96 L604 132 L652 150 L676 196 L640 224 L666 262 L628 300 L650 344 L604 372 L586 420 L540 452 L508 500 L466 486 L430 518 L390 488 L346 508 L304 470 L262 452 L226 410 L184 386 L160 340 L132 300 L150 258 L116 220 L138 150 Z"
          />
          <path
            class="land-ridge"
            d="M196 104 L262 120 L318 92 L372 116 L430 96 L492 118 L548 96"
            fill="none"
          />
          <path
            class="land-ridge"
            d="M226 410 L262 452 L304 470 L346 508 L390 488 L430 518"
            fill="none"
          />

          <g
            v-for="p in points"
            :key="p.sourceId"
            class="point"
            :class="[tierClass(p.tier), { active: p.sourceId === activeId }]"
            :transform="`translate(${px(p.x)} ${py(p.y)})`"
            tabindex="0"
            role="button"
            :aria-label="`${p.name}：${p.title}，来源 ${p.sourceId}，点击高亮`"
            @mouseenter="hoverId = p.sourceId"
            @mouseleave="hoverId = null"
            @focus="hoverId = p.sourceId"
            @blur="hoverId = null"
            @click="select(p.sourceId)"
            @keydown.enter.prevent="select(p.sourceId)"
            @keydown.space.prevent="select(p.sourceId)"
          >
            <circle class="pulse pulse-outer" r="22" />
            <circle class="pulse pulse-inner" r="14" />
            <circle class="dot" r="6" />
            <text class="point-label" x="12" y="-10">{{ p.name }}</text>
          </g>
        </svg>

        <!-- hover/focus tooltip：跟随最近点位的简化固定角标，含来源标题 -->
        <div v-if="hoveredPoint" class="tooltip" role="tooltip">
          <strong>{{ hoveredPoint.title }}</strong>
          <span>{{ hoveredPoint.detail }}</span>
          <span class="tooltip-id tabular">{{ hoveredPoint.sourceId }}</span>
        </div>
      </div>

      <aside class="detail-pane" aria-live="polite">
        <h2 class="pane-title">点位出处</h2>
        <template v-if="activePoint">
          <article class="detail-card">
            <span class="source-badge tabular">{{ activePoint.sourceId }} · {{ activePoint.tier }}语料</span>
            <h3>{{ activePoint.title }}</h3>
            <p>{{ activePoint.detail }}</p>
            <a
              v-if="sourceById.get(activePoint.sourceId)?.url"
              :href="sourceById.get(activePoint.sourceId)?.url ?? ''"
              target="_blank"
              rel="noopener noreferrer"
              class="source-link"
            >
              打开来源原文／核验页 →
            </a>
          </article>
        </template>
        <p v-else class="pane-empty">点击地图上的点位，查看对应来源档案。</p>

        <div class="legend">
          <h3 class="legend-title">图例</h3>
          <p class="legend-row"><span class="legend-dot tier-core"></span>核心语料</p>
          <p class="legend-row"><span class="legend-dot tier-supplement"></span>补充语料</p>
          <p class="legend-note">点位颜色取自登记表 corpus_tier；坐标为示意位置。</p>
        </div>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.map-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
}
.page-head {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.page-title {
  font-family: var(--dm-font-display);
  font-size: var(--text-display);
  line-height: var(--line-height-display);
  font-weight: var(--fw-bold);
  color: var(--dm-ink);
  margin: 0;
  text-shadow: 0 0 18px var(--dm-glow-red);
}
.page-sub {
  margin: 0;
  font-size: var(--text-meta);
  color: var(--dm-ink-dim);
}

.map-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: var(--space-6);
  align-items: start;
}
.map-frame {
  position: relative;
  background: var(--dm-bg-glass);
  border: 1px solid var(--dm-line);
  border-radius: var(--dm-radius);
  box-shadow: var(--dm-shadow);
  overflow: hidden;
}
.map-svg {
  width: 100%;
  height: auto;
  display: block;
}
.land {
  fill: var(--dm-bg-elev);
  stroke: var(--dm-line);
  stroke-width: 2;
  filter: drop-shadow(0 12px 32px var(--dm-glow-red));
}
.land-ridge {
  stroke: var(--dm-line);
  stroke-width: 1;
  stroke-dasharray: 4 6;
  opacity: 0.6;
}

.point {
  cursor: pointer;
  outline: none;
}
.point .pulse {
  transform-box: fill-box;
  transform-origin: center;
  animation: dm-pulse 2s ease-in-out infinite;
}
.point .pulse-outer {
  fill: var(--dm-glow-red);
}
.point .pulse-inner {
  fill: var(--dm-glow-amber);
  animation-delay: 0.4s;
}
.point .dot {
  fill: var(--dm-red);
  stroke: var(--dm-ink);
  stroke-width: 1.5;
}
.point.tier-supplement .dot {
  fill: var(--dm-cyan);
}
.point.active .dot {
  stroke: var(--dm-ink);
  stroke-width: 3;
  filter: drop-shadow(0 0 8px var(--dm-glow-red));
}
.point:focus-visible .dot {
  stroke: var(--dm-ink);
  stroke-width: 3;
}
.point-label {
  fill: var(--dm-ink);
  font-size: 14px;
  font-family: var(--dm-font-display);
  pointer-events: none;
}
.point.active .point-label {
  fill: var(--dm-red);
}

.tooltip {
  position: absolute;
  left: var(--space-4);
  bottom: var(--space-4);
  right: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  background: var(--dm-bg-elev);
  border: 1px solid var(--dm-red-dim);
  border-radius: var(--dm-radius);
  padding: var(--space-4);
  box-shadow: var(--dm-shadow);
  font-size: var(--text-meta);
  color: var(--dm-ink);
}
.tooltip strong {
  font-family: var(--dm-font-display);
  font-size: var(--text-body);
}
.tooltip-id {
  color: var(--dm-cyan);
  font-size: var(--text-caption);
}

.detail-pane {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  background: var(--dm-bg-glass);
  border: 1px solid var(--dm-line);
  border-radius: var(--dm-radius);
  padding: var(--space-6);
}
.pane-title {
  margin: 0;
  font-family: var(--dm-font-display);
  font-size: var(--text-h2);
  color: var(--dm-ink);
}
.detail-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--dm-line);
  border-radius: var(--dm-radius);
  background: var(--dm-bg-elev);
}
.source-badge {
  align-self: flex-start;
  font-size: var(--text-caption);
  color: var(--dm-cyan);
  border: 1px solid var(--dm-line);
  border-radius: var(--radius-1);
  padding: var(--space-1) var(--space-2);
}
.detail-card h3 {
  margin: 0;
  font-family: var(--dm-font-display);
  font-size: var(--text-body);
  color: var(--dm-ink);
  line-height: var(--line-height-h2);
}
.detail-card p {
  margin: 0;
  font-size: var(--text-meta);
  line-height: var(--line-height-meta);
  color: var(--dm-ink-dim);
}
.source-link {
  color: var(--dm-red);
  font-size: var(--text-meta);
  text-decoration: none;
}
.source-link:hover {
  color: var(--dm-ink);
}
.pane-empty {
  margin: 0;
  font-size: var(--text-meta);
  color: var(--dm-ink-dim);
}
.legend {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  border-top: 1px solid var(--dm-line);
  padding-top: var(--space-4);
}
.legend-title {
  margin: 0;
  font-size: var(--text-meta);
  font-weight: var(--fw-semibold);
  color: var(--dm-ink);
}
.legend-row {
  margin: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-caption);
  color: var(--dm-ink-dim);
}
.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}
.legend-dot.tier-core {
  background: var(--dm-red);
  box-shadow: 0 0 8px var(--dm-glow-red);
}
.legend-dot.tier-supplement {
  background: var(--dm-cyan);
}
.legend-note {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--dm-ink-dim);
}

@media (max-width: 1023px) {
  .map-layout {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 767px) {
  .map-layout {
    gap: var(--space-4);
  }
  .detail-pane {
    padding: var(--space-4);
  }
  .point-label {
    font-size: 18px;
  }
}
</style>
