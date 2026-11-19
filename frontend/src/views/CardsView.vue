<script setup lang="ts">
// 来源档案库：5 件已登记来源的 3D 翻转卡片网格。
// 正面=来源标题/发布机构/日期/媒体类型徽标；背面=license_note 摘要 + 核验状态徽标。
// hover / focus-within 翻转（键盘可访问）；入场走 createStagger + motionContext。
// 所有色值走 --dm-* token，reduced-motion 下内容照常显示（工厂返回 null）。
import { onMounted, onUnmounted, ref } from 'vue'
import { createStagger, motionContext } from '../lib/motion'
import { SAMPLE_SOURCES, SOURCE_ARCHIVE } from '../data/samples'
import type { SourceCardModel } from '../api/model'

const gridRef = ref<HTMLElement | null>(null)
let ctx: ReturnType<typeof motionContext> = null

const cards = SAMPLE_SOURCES.map((src, i) => ({
  src,
  archive: SOURCE_ARCHIVE[i],
  // 摘要只做长度截断显示，不改写原文字句（可点「展开」切换全文）。
  noteShort: SOURCE_ARCHIVE[i].licenseNote.slice(0, 78),
}))

const expanded = ref<Record<string, boolean>>({})
function toggleNote(id: string) {
  expanded.value[id] = !expanded.value[id]
}

function noteText(card: (typeof cards)[number]): string {
  return expanded.value[card.src.sourceId] ? card.archive.licenseNote : card.noteShort
}

function mediaLabelText(src: SourceCardModel): string {
  return src.mediaLabel
}

onMounted(() => {
  const grid = gridRef.value
  if (!grid) return
  ctx = motionContext(grid)
  if (!ctx) return
  const items = Array.from(grid.querySelectorAll('.archive-card'))
  if (items.length) {
    ctx.add(() => {
      createStagger(items, { y: 20, stagger: 0.09 })
    })
  }
})

onUnmounted(() => {
  ctx?.revert()
  ctx = null
})
</script>

<template>
  <section class="cards-page" aria-labelledby="cards-title">
    <header class="page-head">
      <h1 id="cards-title" class="page-title">来源档案库 / Source Archive</h1>
      <p class="page-sub">{{ SAMPLE_SOURCES.length }} 件已登记来源</p>
      <p class="page-hint">悬停或用键盘聚焦卡片，翻转查看许可核验信息。</p>
    </header>

    <div ref="gridRef" class="cards-grid">
      <article
        v-for="card in cards"
        :key="card.src.sourceId"
        class="archive-card"
        :data-source-id="card.src.sourceId"
        tabindex="0"
        :aria-label="`来源 ${card.src.sourceId} ${card.src.title}，聚焦可翻转查看核验信息`"
      >
        <div class="card-inner">
          <!-- 正面：标题 / 发布机构 / 日期 / 媒体类型徽标 -->
          <div class="card-face card-front">
            <div class="card-top">
              <span class="media-badge">
                <svg
                  v-if="card.src.mediaKind === 'book'"
                  viewBox="0 0 24 24"
                  width="15"
                  height="15"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  aria-hidden="true"
                >
                  <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
                  <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
                </svg>
                <svg
                  v-else
                  viewBox="0 0 24 24"
                  width="15"
                  height="15"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  aria-hidden="true"
                >
                  <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                  <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
                </svg>
                <span>{{ mediaLabelText(card.src) }}</span>
              </span>
              <span class="source-no tabular">{{ card.src.sourceId }}</span>
            </div>

            <h2 class="card-title">{{ card.src.title }}</h2>

            <p class="card-meta">{{ card.src.publisher }}</p>
            <p class="card-meta tabular">{{ card.src.dateText }}</p>

            <div class="card-bottom">
              <span class="tier-badge" :class="`tier-${card.archive.corpusTier}`">
                {{ card.archive.corpusTier }}语料
              </span>
              <span class="flip-cue">悬停 / 聚焦翻转 →</span>
            </div>
          </div>

          <!-- 背面：license_note 摘要 + 核验状态徽标（颜色+图标+文字三通道） -->
          <div class="card-face card-back">
            <div class="card-top">
              <span class="back-label">核验记录</span>
              <span class="source-no tabular">{{ card.src.sourceId }}</span>
            </div>

            <span
              class="verify-badge"
              :class="card.archive.verified ? 'verify-pass' : 'verify-pending'"
              role="status"
            >
              <svg
                v-if="card.archive.verified"
                viewBox="0 0 24 24"
                width="15"
                height="15"
                fill="none"
                stroke="currentColor"
                stroke-width="2.2"
                aria-hidden="true"
              >
                <path d="M20 6 9 17l-5-5" />
              </svg>
              <svg
                v-else
                viewBox="0 0 24 24"
                width="15"
                height="15"
                fill="none"
                stroke="currentColor"
                stroke-width="2.2"
                aria-hidden="true"
              >
                <circle cx="12" cy="12" r="9" />
                <path d="M12 8v5M12 16.5v.01" />
              </svg>
              <span>{{ card.archive.verified ? '已直连核验' : '电子版待采集' }}</span>
            </span>

            <p class="license-note">{{ noteText(card) }}</p>

            <div class="card-bottom">
              <button type="button" class="note-toggle" @click="toggleNote(card.src.sourceId)">
                {{ expanded[card.src.sourceId] ? '收起' : '展开全文' }}
              </button>
              <span class="flip-cue">← 返回正面</span>
            </div>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.cards-page {
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
  font-size: var(--text-body);
  color: var(--dm-red);
}
.page-hint {
  margin: 0;
  font-size: var(--text-meta);
  color: var(--dm-ink-dim);
}

.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: var(--space-6);
  perspective: 1400px;
}

.archive-card {
  min-height: 290px;
  perspective: 1200px;
  outline: none;
  cursor: default;
}
.archive-card:focus-visible {
  outline: var(--focus-ring-width) solid var(--dm-red);
  outline-offset: var(--focus-ring-offset);
  border-radius: var(--dm-radius);
}
.card-inner {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 290px;
  transform-style: preserve-3d;
  transition: transform 0.7s cubic-bezier(0.2, 0.75, 0.2, 1);
}
.archive-card:hover .card-inner,
.archive-card:focus-within .card-inner {
  transform: rotateY(180deg);
}

.card-face {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-6);
  background: var(--dm-bg-glass);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border: 1px solid var(--dm-line);
  border-radius: var(--dm-radius);
  box-shadow: var(--dm-shadow);
  backface-visibility: hidden;
  -webkit-backface-visibility: hidden;
}
.card-back {
  transform: rotateY(180deg);
  background: var(--dm-bg-elev);
}
.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.media-badge,
.back-label {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--dm-cyan);
  font-size: var(--text-caption);
  font-weight: var(--fw-medium);
}
.source-no {
  color: var(--dm-ink-dim);
  font-size: var(--text-caption);
}
.card-title {
  margin: 0;
  font-family: var(--dm-font-display);
  font-size: var(--text-h2);
  line-height: var(--line-height-h2);
  font-weight: var(--fw-semibold);
  color: var(--dm-ink);
}
.card-meta {
  margin: 0;
  font-size: var(--text-meta);
  line-height: var(--line-height-meta);
  color: var(--dm-ink-dim);
}
.card-bottom {
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.tier-badge,
.verify-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-1);
  font-size: var(--text-caption);
  font-weight: var(--fw-medium);
  border: 1px solid var(--dm-line);
}
.tier-核心 {
  color: var(--dm-amber);
}
.tier-补充 {
  color: var(--dm-cyan);
}
.verify-pass {
  align-self: flex-start;
  color: var(--dm-green);
  box-shadow: 0 0 12px var(--dm-glow-red);
}
.verify-pending {
  align-self: flex-start;
  color: var(--dm-amber);
  box-shadow: 0 0 12px var(--dm-glow-amber);
}
.license-note {
  margin: 0;
  font-size: var(--text-meta);
  line-height: var(--line-height-meta);
  color: var(--dm-ink);
  overflow-y: auto;
  flex: 1;
}
.flip-cue {
  font-size: var(--text-caption);
  color: var(--dm-ink-dim);
}
.note-toggle {
  font: inherit;
  font-size: var(--text-caption);
  color: var(--dm-red);
  background: none;
  border: none;
  padding: var(--space-1) 0;
  cursor: pointer;
}
.note-toggle:hover {
  color: var(--dm-ink);
}

@media (max-width: 767px) {
  .cards-grid {
    grid-template-columns: 1fr;
    gap: var(--space-4);
  }
  .card-face {
    padding: var(--space-4);
  }
}
</style>
