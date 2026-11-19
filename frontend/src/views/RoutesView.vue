<script setup lang="ts">
// 研学路线页：滚动驱动的 SVG 路径绘制 + 镜头跟随圆点。
// 左侧 sticky 示意图（复用 MapView 的程序化中国轮廓思路），右侧 6 段叙事，
// 每段对应 ROUTE_STOPS 中一条真实语料来源。滚动进度经 createPathDraw 的
// ScrollTrigger scrub 绑定到路径 strokeDashoffset；跟随圆点按
// path.getPointAtLength(progress * total) 逐帧定位，经过站点时高亮切换。
// 无外链图片、无第三方地图 API、全部颜色走 --dm-* token。
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { createPathDraw, createStagger, motionContext, prefersReducedMotion } from '../lib/motion'
import { ROUTE_STOPS, SAMPLE_SOURCES, SOURCE_ARCHIVE } from '../data/samples'

const pageRef = ref<HTMLElement | null>(null)
const mapRef = ref<HTMLElement | null>(null)
const storyRef = ref<HTMLElement | null>(null)
let routePathEl: SVGPathElement | null = null

const expanded = ref(false)
const activeIndex = ref(0)
const isStatic = ref(false)
// 跟随圆点位置（800×600 viewBox 坐标），初始落在第一站，避免挂载前闪现左上角
const follower = ref({ x: px(ROUTE_STOPS[0]?.x ?? 0), y: py(ROUTE_STOPS[0]?.y ?? 0) })

const sourceById = new Map(SAMPLE_SOURCES.map((s) => [s.sourceId, s]))
const archiveById = new Map(SOURCE_ARCHIVE.map((a) => [a.sourceId, a]))
const stops = ROUTE_STOPS.map((s, i) => ({ ...s, index: i, tier: archiveById.get(s.sourceId)?.corpusTier ?? '补充' }))

// viewBox 0-100 百分比 → 800×600 画布坐标
function px(x: number): number {
  return (x / 100) * 800
}
function py(y: number): number {
  return (y / 100) * 600
}

// 路线 path：依次穿过各站点，用二次贝塞尔平滑转角，避免生硬折线。
const routeD = computed(() => {
  const pts = stops.map((s) => [px(s.x), py(s.y)] as const)
  if (pts.length === 0) return ''
  let d = `M ${pts[0][0]} ${pts[0][1]}`
  for (let i = 1; i < pts.length; i++) {
    const [px0, py0] = pts[i - 1]
    const [px1, py1] = pts[i]
    const mx = (px0 + px1) / 2
    const my = (py0 + py1) / 2
    d += ` Q ${px0} ${py0} ${mx} ${my}`
    if (i === pts.length - 1) d += ` T ${px1} ${py1}`
  }
  return d
})

let ctx: ReturnType<typeof motionContext> = null
let drawTween: ReturnType<typeof createPathDraw> = null
let rafId = 0
let transitionRafId = 0
// 收起全图时跟随圆点从终点平滑回落到滚动进度；非 null 时优先于主循环
let followProgressOverride: number | null = null
// 各站点在路径上的长度比例（采样最近点求得），用于高亮与镜头跟随同步
let stopRatios: number[] = []

function setRoutePath(el: unknown) {
  // jsdom 无 SVGPathElement 全局构造器，用能力检测代替 instanceof
  routePathEl = el && typeof (el as SVGPathElement).getTotalLength === 'function'
    ? (el as SVGPathElement)
    : null
}

function updateFollower(progress: number) {
  const path = routePathEl
  if (!path || typeof path.getTotalLength !== 'function') return
  const total = path.getTotalLength()
  if (!total) return
  const p = Math.max(0, Math.min(1, progress))
  const point = path.getPointAtLength(p * total)
  follower.value = { x: point.x, y: point.y }
  // 高亮：找最近的站点长度比例
  let nearest = 0
  let best = Infinity
  for (let i = 0; i < stopRatios.length; i++) {
    const d = Math.abs(stopRatios[i] - p)
    if (d < best) {
      best = d
      nearest = i
    }
  }
  activeIndex.value = nearest
}

function computeStopRatios(path: SVGPathElement) {
  const total = path.getTotalLength()
  if (!total) return
  stopRatios = stops.map((s) => {
    const targetX = px(s.x)
    const targetY = py(s.y)
    let bestLen = 0
    let bestDist = Infinity
    // 2px 步长采样，取距站点示意坐标最近的路径点
    for (let len = 0; len <= total; len += 2) {
      const pt = path.getPointAtLength(len)
      const dx = pt.x - targetX
      const dy = pt.y - targetY
      const dist = dx * dx + dy * dy
      if (dist < bestDist) {
        bestDist = dist
        bestLen = len
      }
    }
    return bestLen / total
  })
}

function tick() {
  // 展开全图时滚动驱动暂时让位给「推进到终点」的确定状态
  if (!expanded.value) {
    if (followProgressOverride !== null) {
      updateFollower(followProgressOverride)
    } else {
      const st = drawTween?.scrollTrigger
      updateFollower(st ? st.progress : 0)
    }
  }
  rafId = requestAnimationFrame(tick)
}

/** 收起全图后让跟随圆点从终点平滑回落到滚动进度，避免瞬移。 */
function glideFollowerTo(target: number) {
  if (transitionRafId) cancelAnimationFrame(transitionRafId)
  const from = 1
  const duration = 450
  const startedAt = performance.now()
  const step = (now: number) => {
    const t = Math.min(1, (now - startedAt) / duration)
    const eased = 1 - Math.pow(1 - t, 3)
    followProgressOverride = from + (target - from) * eased
    updateFollower(followProgressOverride)
    if (t < 1) {
      transitionRafId = requestAnimationFrame(step)
    } else {
      transitionRafId = 0
      followProgressOverride = null
    }
  }
  followProgressOverride = from
  transitionRafId = requestAnimationFrame(step)
}

/** 「展开全图」：真正放大地图，并把路径绘制推进到 1；再点恢复滚动驱动。 */
function toggleExpand() {
  expanded.value = !expanded.value
  if (expanded.value) {
    drawTween?.scrollTrigger?.disable(false)
    drawTween?.progress(1)
    updateFollower(1)
  } else {
    drawTween?.scrollTrigger?.enable()
    const st = drawTween?.scrollTrigger
    glideFollowerTo(st ? st.progress : 0)
  }
}

onMounted(() => {
  const path = routePathEl
  if (!path || !storyRef.value || !mapRef.value) return

  // reduced-motion / 测试环境：路径直接完整显示，叙事与站点卡片保持完整可读
  if (prefersReducedMotion()) {
    isStatic.value = true
    updateFollower(1)
    return
  }

  ctx = motionContext(pageRef.value ?? mapRef.value)
  if (!ctx) {
    isStatic.value = true
    updateFollower(1)
    return
  }

  ctx.add(() => {
    const cards = Array.from(storyRef.value?.querySelectorAll('.stop-card') ?? [])
    createStagger(cards, { y: 24, stagger: 0.12 })
    // 叙事区很长，用工厂的 end 参数让路径绘制贯穿 6 段故事
    drawTween = createPathDraw(path, { trigger: storyRef.value!, end: 'bottom bottom' })
    if (typeof path.getTotalLength === 'function') {
      computeStopRatios(path)
      updateFollower(0)
      rafId = requestAnimationFrame(tick)
    }
  })
})

onUnmounted(() => {
  if (rafId) cancelAnimationFrame(rafId)
  if (transitionRafId) cancelAnimationFrame(transitionRafId)
  drawTween?.scrollTrigger?.kill()
  drawTween?.kill()
  drawTween = null
  ctx?.revert()
  ctx = null
})
</script>

<template>
  <section ref="pageRef" class="routes-page" aria-labelledby="routes-title">
    <header class="page-head">
      <p class="eyebrow">溯源叙事 · 滚动长卷</p>
      <h1 id="routes-title" class="page-title">重走长征路 / Interactive Route</h1>
      <p class="page-sub">
        沿登记语料中真实出现的地名，逐站展开一段可滚动阅读的长征叙事。
        地图为程序化 SVG 示意图（非精确测绘），坐标为示意落点；每条记录均附来源档案编号。
      </p>
      <div class="head-actions">
        <button
          type="button"
          class="expand-btn"
          :aria-pressed="expanded"
          @click="toggleExpand"
        >
          {{ expanded ? '收起全图' : '展开全图' }}
        </button>
        <span class="progress-figures tabular">{{ activeIndex + 1 }} / {{ stops.length }} 站</span>
      </div>
    </header>

    <div class="route-layout" :class="{ 'is-expanded': expanded }">
      <!-- 左侧 sticky 地图 -->
      <div ref="mapRef" class="map-frame">
        <div class="map-caption">
          <span class="caption-kicker">路线轨迹</span>
          <strong>{{ stops[activeIndex]?.name }}</strong>
          <span class="caption-id tabular">{{ stops[activeIndex]?.sourceId }}</span>
        </div>
        <svg viewBox="0 0 800 600" class="map-svg" role="img" aria-label="长征叙事路线示意图：路线随右侧滚动逐段绘制">
          <!-- 中国示意轮廓：与 MapView 同一思路的抽象闭环，非精确测绘 -->
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

          <!-- 路线底图（虚线预告全程走向） -->
          <path class="route-ghost" :d="routeD" fill="none" />
          <!-- 滚动绘制的主路线 -->
          <path
            :ref="setRoutePath"
            class="route-line"
            :class="{ 'is-static': isStatic }"
            :d="routeD"
            fill="none"
          />

          <!-- 途经点：当前站点高亮 -->
          <g
            v-for="stop in stops"
            :key="stop.sourceId + stop.name"
            class="stop-dot"
            :class="{ active: stop.index === activeIndex, reached: stop.index <= activeIndex, supplementary: stop.tier === '补充' }"
            :transform="`translate(${px(stop.x)} ${py(stop.y)})`"
          >
            <circle class="stop-halo" r="16" />
            <circle class="stop-core" r="5" />
            <text class="stop-label" x="11" y="-9">{{ stop.name }}</text>
          </g>

          <!-- 镜头跟随圆点 -->
          <g class="follower" :transform="`translate(${follower.x} ${follower.y})`">
            <circle class="follower-glow" r="20" />
            <circle class="follower-core" r="7" />
          </g>
        </svg>
        <p class="map-foot">路线按语料原文出现的地名顺序绘制；绘制进度与右侧阅读进度同步。</p>
      </div>

      <!-- 右侧滚动叙事 -->
      <div ref="storyRef" class="story">
        <article
          v-for="stop in stops"
          :key="stop.sourceId + stop.name"
          class="stop-card"
          :class="{ current: stop.index === activeIndex }"
          :aria-current="stop.index === activeIndex ? 'step' : undefined"
        >
          <div class="stop-index tabular">{{ String(stop.index + 1).padStart(2, '0') }}</div>
          <div class="stop-body">
            <span class="source-badge tabular">{{ stop.sourceId }} · {{ stop.tier }}语料</span>
            <h2 class="stop-title">{{ stop.name }}</h2>
            <p class="stop-detail">{{ stop.detail }}</p>
            <a
              v-if="sourceById.get(stop.sourceId)?.url"
              :href="sourceById.get(stop.sourceId)?.url ?? ''"
              target="_blank"
              rel="noopener noreferrer"
              class="source-link"
            >核验来源原文 →</a>
          </div>
        </article>
        <p class="story-end">— 路线终 — 数据来源：登记语料 S001–S005；郴州为当代档案归集地，非当年行军途经点。</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.routes-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
}
.page-head {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.eyebrow {
  margin: 0;
  font-size: var(--text-caption);
  letter-spacing: 0.24em;
  color: var(--dm-cyan);
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
  max-width: 68ch;
  font-size: var(--text-meta);
  line-height: var(--line-height-meta);
  color: var(--dm-ink-dim);
}
.head-actions {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
}
.expand-btn {
  font: inherit;
  font-size: var(--text-meta);
  font-weight: var(--fw-semibold);
  color: var(--dm-ink);
  background: var(--dm-red-dim);
  border: 1px solid var(--dm-red);
  border-radius: var(--radius-1);
  padding: var(--space-2) var(--space-4);
  cursor: pointer;
  transition: background 180ms ease, box-shadow 180ms ease;
}
.expand-btn:hover {
  background: var(--dm-red);
  box-shadow: 0 0 14px var(--dm-glow-red);
}
.progress-figures {
  font-size: var(--text-caption);
  color: var(--dm-cyan);
}

.route-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 420px);
  gap: var(--space-8);
  align-items: start;
}

/* 左侧地图：sticky 跟随 */
.map-frame {
  position: sticky;
  top: calc(var(--header-height) + var(--space-6));
  background: var(--dm-bg-glass);
  border: 1px solid var(--dm-line);
  border-radius: var(--dm-radius);
  box-shadow: var(--dm-shadow);
  padding: var(--space-4);
  overflow: hidden;
  z-index: var(--z-base);
}
.route-layout.is-expanded .map-frame {
  position: fixed;
  inset: var(--header-height) var(--space-6) var(--space-6);
  z-index: var(--z-overlay);
  display: flex;
  flex-direction: column;
  justify-content: center;
  background: var(--dm-bg-elev);
  box-shadow: 0 0 0 100vmax var(--dm-bg);
  animation: map-zoom 360ms ease-out;
}
@keyframes map-zoom {
  from { opacity: 0.4; transform: scale(0.92); }
  to { opacity: 1; transform: scale(1); }
}
.map-caption {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
  font-family: var(--dm-font-display);
}
.caption-kicker {
  font-size: var(--text-caption);
  letter-spacing: 0.18em;
  color: var(--dm-ink-dim);
}
.map-caption strong {
  font-size: var(--text-h2);
  color: var(--dm-ink);
}
.caption-id {
  font-size: var(--text-caption);
  color: var(--dm-cyan);
}
.map-svg {
  width: 100%;
  height: auto;
  display: block;
}
.map-foot {
  margin: var(--space-2) 0 0;
  font-size: var(--text-caption);
  color: var(--dm-ink-dim);
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
.route-ghost {
  stroke: var(--dm-line);
  stroke-width: 2;
  stroke-dasharray: 6 8;
  fill: none;
}
.route-line {
  stroke: var(--dm-red);
  stroke-width: 4;
  stroke-linecap: round;
  stroke-linejoin: round;
  filter: drop-shadow(0 0 8px var(--dm-glow-red));
}
.route-line.is-static {
  stroke-dasharray: none;
  stroke-dashoffset: 0;
}
.stop-halo {
  fill: var(--dm-glow-red);
  opacity: 0.35;
}
.stop-core {
  fill: var(--dm-red);
  stroke: var(--dm-ink);
  stroke-width: 1.5;
}
.stop-dot.supplementary .stop-core {
  fill: var(--dm-cyan);
}
.stop-dot.reached .stop-halo {
  fill: var(--dm-glow-amber);
  opacity: 0.55;
}
.stop-dot.active .stop-core {
  stroke-width: 3;
  filter: drop-shadow(0 0 8px var(--dm-glow-red));
}
.stop-label {
  fill: var(--dm-ink);
  font-size: 14px;
  font-family: var(--dm-font-display);
  pointer-events: none;
}
.stop-dot.active .stop-label {
  fill: var(--dm-red);
}
.follower-glow {
  fill: var(--dm-glow-red);
  opacity: 0.55;
  animation: dm-pulse 1.6s ease-in-out infinite;
  transform-box: fill-box;
  transform-origin: center;
}
.follower-core {
  fill: var(--dm-amber);
  stroke: var(--dm-ink);
  stroke-width: 2;
  filter: drop-shadow(0 0 10px var(--dm-glow-amber));
}

/* 右侧叙事 */
.story {
  display: flex;
  flex-direction: column;
  gap: var(--space-12);
  padding-bottom: var(--space-16);
}
.stop-card {
  display: grid;
  grid-template-columns: 44px 1fr;
  gap: var(--space-4);
  min-height: 56vh;
  padding: var(--space-6);
  background: var(--dm-bg-glass);
  border: 1px solid var(--dm-line);
  border-radius: var(--dm-radius);
  opacity: 0.62;
  transition: opacity 300ms ease, border-color 300ms ease, box-shadow 300ms ease, background 300ms ease;
}
.stop-card.current {
  opacity: 1;
  border-color: var(--dm-red);
  background: var(--dm-bg-elev);
  box-shadow: 0 0 24px var(--dm-glow-red);
}
.stop-index {
  font-family: var(--dm-font-display);
  font-size: var(--text-h1);
  color: var(--dm-red);
  line-height: 1;
}
.stop-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.source-badge {
  align-self: flex-start;
  font-size: var(--text-caption);
  color: var(--dm-cyan);
  border: 1px solid var(--dm-line);
  border-radius: var(--radius-1);
  padding: var(--space-1) var(--space-2);
}
.stop-title {
  margin: 0;
  font-family: var(--dm-font-display);
  font-size: var(--text-h2);
  line-height: var(--line-height-h2);
  color: var(--dm-ink);
}
.stop-detail {
  margin: 0;
  font-size: var(--text-meta);
  line-height: var(--line-height-meta);
  color: var(--dm-ink-dim);
}
.source-link {
  align-self: flex-start;
  font-size: var(--text-meta);
  color: var(--dm-red);
  text-decoration: none;
}
.source-link:hover {
  color: var(--dm-ink);
}
.story-end {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--dm-ink-dim);
  border-top: 1px solid var(--dm-line);
  padding-top: var(--space-4);
}

@media (max-width: 1024px) {
  .route-layout {
    grid-template-columns: 1fr;
  }
  .map-frame {
    position: relative;
    top: auto;
    height: 46vh;
    min-height: 320px;
    display: flex;
    flex-direction: column;
    justify-content: center;
  }
  .map-svg {
    max-height: 100%;
  }
  .stop-card {
    min-height: 40vh;
  }
  .route-layout.is-expanded .map-frame {
    inset: var(--header-height) var(--space-4) var(--space-4);
  }
}
@media (max-width: 767px) {
  .routes-page {
    gap: var(--space-6);
  }
  .route-layout {
    gap: var(--space-6);
  }
  .map-frame {
    height: 34vh;
    min-height: 240px;
    padding: var(--space-2);
  }
  .map-foot {
    display: none;
  }
  .stop-card {
    grid-template-columns: 1fr;
    min-height: 0;
    padding: var(--space-4);
    gap: var(--space-2);
  }
  .story {
    gap: var(--space-4);
  }
  .stop-label {
    font-size: 18px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .follower-glow {
    animation: none;
  }
  .route-layout.is-expanded .map-frame {
    animation: none;
  }
}
</style>
