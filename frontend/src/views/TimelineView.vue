<script setup lang="ts">
// 历史时间轴：SVG 竖直曲线随滚动描绘（createPathDraw + ScrollTrigger），
// 事件节点沿路径分布，IntersectionObserver 逐个点亮；纯数字年份用 createCounter 滚动。
// 动效全部走 motion 工厂；reduced-motion / 测试环境下工厂返回 null，节点内容照常完整可见。
import { onMounted, onUnmounted, ref } from 'vue'
import {
  createCounter,
  createPathDraw,
  motionContext,
  prefersReducedMotion,
} from '../lib/motion'
import { TIMELINE_EVENTS } from '../data/samples'

const containerRef = ref<HTMLElement | null>(null)
const pathRef = ref<SVGPathElement | null>(null)
const nodeRefs = ref<HTMLElement[]>([])
const activeIndex = ref<number>(-1)
let ctx: ReturnType<typeof motionContext> = null
let observer: IntersectionObserver | null = null

function setNodeRef(el: HTMLElement | null, i: number) {
  if (el) nodeRefs.value[i] = el
}

function isNumericYear(year: string): boolean {
  return /^\d{4}$/.test(year)
}

onMounted(() => {
  const container = containerRef.value
  if (!container) return
  ctx = motionContext(container)
  if (!ctx) return

  const path = pathRef.value
  if (path) {
    ctx.add(() => {
      createPathDraw(path, { trigger: container })
    })
  }

  // 纯数字年份：只对已点亮节点做数字滚动，避免一进来全部同时归零抖动。
  const counters: { el: HTMLElement; to: number }[] = []
  nodeRefs.value.forEach((node, i) => {
    const ev = TIMELINE_EVENTS[i]
    if (ev && isNumericYear(ev.year)) {
      const el = node.querySelector<HTMLElement>('.year-value')
      if (el) counters.push({ el, to: Number(ev.year) })
    }
  })

  const lit = new Set<number>()
  if (typeof IntersectionObserver !== 'undefined' && !prefersReducedMotion()) {
    observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const idx = Number((entry.target as HTMLElement).dataset.index)
          if (!entry.isIntersecting || lit.has(idx)) continue
          lit.add(idx)
          activeIndex.value = Math.max(activeIndex.value, idx)
          ;(entry.target as HTMLElement).classList.add('is-lit')
          const counter = counters.find((c) => nodeRefs.value[idx]?.contains(c.el))
          if (counter) ctx?.add(() => createCounter(counter.el, counter.to, { duration: 1 }))
          observer?.unobserve(entry.target)
        }
      },
      { threshold: 0.35, rootMargin: '0px 0px -8% 0px' },
    )
    nodeRefs.value.forEach((node) => observer?.observe(node))
  } else {
    // 降级：内容完整显示，不做点亮状态切换。
    nodeRefs.value.forEach((node) => node.classList.add('is-lit'))
    activeIndex.value = TIMELINE_EVENTS.length - 1
  }
})

onUnmounted(() => {
  observer?.disconnect()
  observer = null
  ctx?.revert()
  ctx = null
})
</script>

<template>
  <section ref="containerRef" class="timeline-page" aria-labelledby="timeline-title">
    <header class="page-head">
      <h1 id="timeline-title" class="page-title">历史时间轴 / Timeline</h1>
      <p class="page-sub">按登记来源的出版/发布年份排列，节点可回链出处 ID。</p>
    </header>

    <div class="timeline-body">
      <!-- 竖直曲线：程序化 SVG，不依赖任何外链图片 -->
      <svg
        class="timeline-spine"
        viewBox="0 0 120 1000"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <path
          ref="pathRef"
          class="spine-path"
          d="M60 10 C 40 110, 86 210, 64 320 C 42 430, 90 540, 60 650 C 30 760, 84 870, 60 990"
          fill="none"
          stroke="var(--dm-line)"
          stroke-width="2"
        />
        <path
          class="spine-glow"
          d="M60 10 C 40 110, 86 210, 64 320 C 42 430, 90 540, 60 650 C 30 760, 84 870, 60 990"
          fill="none"
          stroke="var(--dm-red)"
          stroke-width="1"
          stroke-dasharray="2 10"
          opacity="0.55"
        />
      </svg>

      <ol class="event-list">
        <li
          v-for="(ev, i) in TIMELINE_EVENTS"
          :key="`${ev.sourceId}-${i}`"
          :ref="(el) => setNodeRef(el as HTMLElement | null, i)"
          class="event-node"
          :class="{ 'is-lit': i === 0 }"
          :data-index="i"
        >
          <span class="node-dot" aria-hidden="true"></span>
          <article class="event-card">
            <div class="event-top">
              <span class="year-badge tabular">
                <span v-if="isNumericYear(ev.year)" class="year-value">{{ ev.year }}</span>
                <span v-else>{{ ev.year }}</span>
              </span>
              <span class="source-badge">{{ ev.sourceId }}</span>
            </div>
            <h2 class="event-title">{{ ev.title }}</h2>
            <p class="event-detail">{{ ev.detail }}</p>
          </article>
        </li>
      </ol>
    </div>
  </section>
</template>

<style scoped>
.timeline-page {
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

.timeline-body {
  position: relative;
  padding-left: var(--space-8);
}
.timeline-spine {
  position: absolute;
  left: 26px;
  top: 0;
  bottom: 0;
  width: 68px;
  height: 100%;
  pointer-events: none;
}
.spine-path {
  transition: stroke 0.4s ease;
}
.spine-glow {
  animation: dm-float 6s ease-in-out infinite;
}

.event-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
}
.event-node {
  position: relative;
  opacity: 0.35;
  transform: scale(0.97);
  transform-origin: left center;
  transition: opacity 0.6s ease, transform 0.6s ease;
}
.event-node.is-lit {
  opacity: 1;
  transform: scale(1);
}
.node-dot {
  position: absolute;
  left: calc(-1 * var(--space-8) + 21px);
  top: 22px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--dm-red);
  box-shadow: 0 0 14px var(--dm-glow-red);
}
.event-node.is-lit .node-dot {
  animation: dm-pulse 2s ease-in-out infinite;
}
.event-card {
  background: var(--dm-bg-glass);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border: 1px solid var(--dm-line);
  border-radius: var(--dm-radius);
  padding: var(--space-6);
  box-shadow: var(--dm-shadow);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.event-node.is-lit .event-card {
  border-color: var(--dm-red-dim);
}
.event-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}
.year-badge {
  font-family: var(--dm-font-display);
  font-size: var(--text-h2);
  font-weight: var(--fw-bold);
  color: var(--dm-red);
  text-shadow: 0 0 12px var(--dm-glow-red);
}
.source-badge {
  font-size: var(--text-caption);
  color: var(--dm-cyan);
  border: 1px solid var(--dm-line);
  border-radius: var(--radius-1);
  padding: var(--space-1) var(--space-2);
}
.event-title {
  margin: 0;
  font-family: var(--dm-font-display);
  font-size: var(--text-body);
  font-weight: var(--fw-semibold);
  color: var(--dm-ink);
  line-height: var(--line-height-h2);
}
.event-detail {
  margin: 0;
  font-size: var(--text-meta);
  line-height: var(--line-height-meta);
  color: var(--dm-ink-dim);
}

@media (max-width: 767px) {
  .timeline-body {
    padding-left: var(--space-6);
  }
  .timeline-spine {
    left: 18px;
  }
  .node-dot {
    left: calc(-1 * var(--space-6) + 13px);
  }
  .event-card {
    padding: var(--space-4);
  }
}
</style>
