<script setup lang="ts">
// 研学素材包：把 samples.ts 的真实语料聚合成可筛选的素材瀑布流。
// 素材 = 5 条登记来源 + 6 条时间轴事件 + 5 个地图点位 + 6 个路线站点 = 22 项，
// 全部逐字取自 samples.ts，不编造、不放假下载按钮。
// 分类 chips 切换时通过 :key 触发网格重挂载，createStagger 重新浮入；
// 入场与重挂载动画都收进 motionContext，卸载时 revert。
// 所有色值走 --dm-* token；reduced-motion 下工厂返回 null，内容照常完整显示。
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { createReveal, createStagger, motionContext } from '../lib/motion'
import {
  MAP_POINTS,
  ROUTE_STOPS,
  SAMPLE_SOURCES,
  SOURCE_ARCHIVE,
  TIMELINE_EVENTS,
} from '../data/samples'
import type { SourceCardModel } from '../api/model'

type CategoryKey = 'all' | 'article' | 'book' | 'timeline' | 'map' | 'route'

interface PackItem {
  id: string
  /** 分类键，同时是 chips 的筛选目标 */
  category: Exclude<CategoryKey, 'all'>
  /** 徽标文字（颜色 + 图标 + 文字三通道中的文字通道） */
  typeLabel: string
  title: string
  summary: string
  sourceId: string
  /** 卡片强调色 token，按类别取色 */
  accent: 'red' | 'cyan' | 'amber' | 'green'
}

const archiveById = new Map(SOURCE_ARCHIVE.map((a) => [a.sourceId, a]))

function licenseSummary(sourceId: string): string {
  const note = archiveById.get(sourceId)?.licenseNote ?? ''
  return note.length > 88 ? `${note.slice(0, 88)}…` : note
}

function mediaCategory(src: SourceCardModel): 'article' | 'book' {
  return src.mediaKind === 'book' ? 'book' : 'article'
}

// 真实语料 → 素材条目；id 用「类别-条目序号」保证 key 稳定唯一。
const allItems: PackItem[] = [
  ...SAMPLE_SOURCES.map((src, i) => ({
    id: `source-${i}`,
    category: mediaCategory(src),
    typeLabel: src.mediaLabel,
    title: src.title,
    summary: licenseSummary(src.sourceId),
    sourceId: src.sourceId,
    accent: (src.mediaKind === 'book' ? 'amber' : 'red') as PackItem['accent'],
  })),
  ...TIMELINE_EVENTS.map((ev, i) => ({
    id: `timeline-${i}`,
    category: 'timeline' as const,
    typeLabel: '时间轴',
    title: ev.title,
    summary: ev.detail,
    sourceId: ev.sourceId,
    accent: 'cyan' as const,
  })),
  ...MAP_POINTS.map((pt, i) => ({
    id: `map-${i}`,
    category: 'map' as const,
    typeLabel: '地图点位',
    title: pt.name,
    summary: pt.detail,
    sourceId: pt.sourceId,
    accent: 'green' as const,
  })),
  ...ROUTE_STOPS.map((stop, i) => ({
    id: `route-${i}`,
    category: 'route' as const,
    typeLabel: '路线站点',
    title: stop.name,
    summary: stop.detail,
    sourceId: stop.sourceId,
    accent: 'red' as const,
  })),
]

const totalCount = allItems.length

const chips: { key: CategoryKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'article', label: '文章' },
  { key: 'book', label: '电子书' },
  { key: 'timeline', label: '时间轴' },
  { key: 'map', label: '地图' },
  { key: 'route', label: '路线' },
]

const active = ref<CategoryKey>('all')
const gridRef = ref<HTMLElement | null>(null)
const headRef = ref<HTMLElement | null>(null)
let ctx: ReturnType<typeof motionContext> = null

const visibleItems = computed(() =>
  active.value === 'all'
    ? allItems
    : allItems.filter((item) => item.category === active.value),
)

function selectCategory(key: CategoryKey) {
  if (active.value === key) return
  active.value = key
  void nextTick(() => animateGrid())
}

function animateGrid() {
  const grid = gridRef.value
  if (!grid || !ctx) return
  const cards = Array.from(grid.querySelectorAll('.pack-card'))
  if (cards.length) ctx.add(() => createStagger(cards, { y: 20, stagger: 0.055 }))
}

onMounted(() => {
  const head = headRef.value
  const grid = gridRef.value
  if (!head || !grid) return
  ctx = motionContext(grid)
  if (!ctx) return
  ctx.add(() => {
    createReveal(head, { y: -16 })
    const cards = Array.from(grid.querySelectorAll('.pack-card'))
    if (cards.length) createStagger(cards, { y: 20, stagger: 0.055 })
  })
})

onUnmounted(() => {
  ctx?.revert()
  ctx = null
})
</script>

<template>
  <section class="lesson-page" aria-labelledby="lesson-title">
    <header ref="headRef" class="page-head">
      <h1 id="lesson-title" class="page-title">研学素材包 / Lesson Pack</h1>
      <p class="page-sub">共 {{ totalCount }} 项素材，逐条关联已登记来源 S001–S005</p>
    </header>

    <!-- 诚实的纯展示统计条：不放假下载按钮 -->
    <div class="registry-bar" role="status" aria-live="polite">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <path d="M4 7h16M4 7l2-3h12l2 3M4 7v13h16V7M9 11h6M9 15h6" />
      </svg>
      <span>已登记 <strong class="tabular">{{ totalCount }}</strong> 项素材</span>
      <span class="registry-note">全部取自本地来源登记表与逐字语料 · 无外链图片</span>
    </div>

    <div class="chip-row" role="group" aria-label="素材分类筛选">
      <button
        v-for="chip in chips"
        :key="chip.key"
        type="button"
        class="chip"
        :class="[
          `chip-${chip.key}`,
          active === chip.key ? 'chip-active' : '',
        ]"
        :aria-pressed="active === chip.key"
        @click="selectCategory(chip.key)"
      >
        {{ chip.label }}
      </button>
    </div>

    <p class="result-note" aria-live="polite">
      当前显示 <strong class="tabular">{{ visibleItems.length }}</strong> / {{ totalCount }} 项
    </p>

    <!-- key 随筛选变化 → 重挂载 → createStagger 重新浮入 -->
    <div :key="active" ref="gridRef" class="pack-grid">
      <article v-for="item in visibleItems" :key="item.id" class="pack-card" :class="`accent-${item.accent}`">
        <div class="card-top">
          <span class="type-badge">
            <!-- 颜色 + SVG 图标 + 文字三通道；图标随类别切换 -->
            <svg v-if="item.category === 'article'" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path d="M4 4h16v16H4zM8 8h8M8 12h8M8 16h5" />
            </svg>
            <svg v-else-if="item.category === 'book'" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
            </svg>
            <svg v-else-if="item.category === 'timeline'" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
            </svg>
            <svg v-else-if="item.category === 'map'" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path d="M12 21s7-6.2 7-11a7 7 0 1 0-14 0c0 4.8 7 11 7 11z" /><circle cx="12" cy="10" r="2.5" />
            </svg>
            <svg v-else viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <circle cx="5" cy="18" r="2" /><circle cx="19" cy="6" r="2" /><path d="M7 18h5a4 4 0 0 0 4-4v-6" />
            </svg>
            <span>{{ item.typeLabel }}</span>
          </span>
          <span class="source-no tabular">{{ item.sourceId }}</span>
        </div>

        <h2 class="card-title">{{ item.title }}</h2>
        <p class="card-summary">{{ item.summary }}</p>
        <p class="card-foot">关联来源 <span class="tabular">{{ item.sourceId }}</span> · 逐字节选</p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.lesson-page {
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

/* 统计条：纯展示，无下载按钮 */
.registry-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--dm-line);
  border-left: 3px solid var(--dm-red);
  border-radius: var(--dm-radius);
  background: var(--dm-bg-glass);
  color: var(--dm-ink);
  font-size: var(--text-meta);
}
.registry-bar strong {
  color: var(--dm-red);
  font-size: var(--text-h2);
}
.registry-note {
  margin-left: auto;
  color: var(--dm-ink-dim);
  font-size: var(--text-caption);
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 44px;
  padding: 0 var(--space-4);
  font: inherit;
  font-size: var(--text-meta);
  color: var(--dm-ink-dim);
  background: var(--dm-bg-glass);
  border: 1px solid var(--dm-line);
  border-radius: var(--dm-radius);
  cursor: pointer;
  transition: color 0.2s, border-color 0.2s, box-shadow 0.2s, background 0.2s;
}
.chip:hover {
  color: var(--dm-ink);
  border-color: var(--dm-red-dim);
}
.chip:focus-visible {
  outline: var(--focus-ring-width) solid var(--dm-red);
  outline-offset: var(--focus-ring-offset);
}
.chip-active {
  color: var(--dm-ink);
  font-weight: var(--fw-medium);
  border-color: var(--dm-red);
  background: var(--dm-bg-elev);
  box-shadow: inset 0 -3px 0 var(--dm-red), 0 0 12px var(--dm-glow-red);
}
.result-note {
  margin: 0;
  font-size: var(--text-meta);
  color: var(--dm-ink-dim);
}
.result-note strong {
  color: var(--dm-cyan);
}

.pack-grid {
  columns: 3;
  column-gap: var(--space-4);
}
.pack-card {
  break-inside: avoid;
  display: inline-block;
  width: 100%;
  margin: 0 0 var(--space-4);
  padding: var(--space-4);
  border: 1px solid var(--dm-line);
  border-top: 3px solid var(--dm-red);
  border-radius: var(--dm-radius);
  background: var(--dm-bg-glass);
  box-shadow: var(--dm-shadow);
  transition: transform 0.25s, border-color 0.25s;
}
.pack-card:hover {
  transform: translateY(-4px);
}
.accent-red { border-top-color: var(--dm-red); }
.accent-cyan { border-top-color: var(--dm-cyan); }
.accent-amber { border-top-color: var(--dm-amber); }
.accent-green { border-top-color: var(--dm-green); }

.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}
.type-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-caption);
  font-weight: var(--fw-medium);
  color: var(--dm-cyan);
}
.accent-red .type-badge { color: var(--dm-red); }
.accent-amber .type-badge { color: var(--dm-amber); }
.accent-green .type-badge { color: var(--dm-green); }
.source-no {
  font-size: var(--text-caption);
  color: var(--dm-ink-dim);
}
.card-title {
  margin: 0 0 var(--space-2);
  font-family: var(--dm-font-display);
  font-size: var(--text-h2);
  line-height: var(--line-height-h2);
  font-weight: var(--fw-semibold);
  color: var(--dm-ink);
}
.card-summary {
  margin: 0 0 var(--space-3);
  font-size: var(--text-meta);
  line-height: var(--line-height-meta);
  color: var(--dm-ink-dim);
}
.card-foot {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--dm-cyan);
}

@media (max-width: 1023px) {
  .pack-grid { columns: 2; }
  .registry-note { margin-left: 0; width: 100%; }
}
@media (max-width: 767px) {
  .pack-grid { columns: 1; }
  .chip { padding: 0 var(--space-3); font-size: var(--text-caption); }
}
</style>
