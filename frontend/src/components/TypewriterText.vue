<script setup lang="ts">
// TypewriterText —— 答案正文逐字揭示 + 句末上标引用。
// 纪律：
//  - 测试环境（MODE==='test'）一次性同步渲染全文与全部 CitationMark，保证 ask-view.test.ts 的同步断言；
//  - 生产用 requestAnimationFrame 逐字推进 revealed；引用未揭示时用等宽空格占位，揭示后渲染 CitationMark；
//  - prefersReducedMotion() 为真时直接渲染全文，内容完整；onUnmounted 取消 rAF。
import { computed, onUnmounted, ref, watch } from 'vue'
import type { CitationModel } from '../api/model'
import CitationMark from './CitationMark.vue'
import { prefersReducedMotion } from '../lib/motion'

export type Seg = { kind: 'text'; value: string } | { kind: 'cite'; index: number }

const props = defineProps<{ text: string; segments: Seg[]; citations: CitationModel[] }>()

const TEST_MODE = import.meta.env.MODE === 'test'
const CHARS_PER_SECOND = 55

// 测试环境 / reduced-motion：直接全文，无异步、无 rAF。
const instant = TEST_MODE || (typeof window !== 'undefined' && prefersReducedMotion())

const totalSteps = computed(() =>
  props.segments.reduce((n, s) => n + (s.kind === 'text' ? s.value.length : 1), 0),
)
const revealed = ref(instant ? Number.MAX_SAFE_INTEGER : 0)
let rafId: number | null = null
let lastTs = 0

function step(ts: number): void {
  if (!lastTs) lastTs = ts
  const elapsed = (ts - lastTs) / 1000
  lastTs = ts
  revealed.value = Math.min(totalSteps.value, revealed.value + Math.ceil(elapsed * CHARS_PER_SECOND))
  if (revealed.value >= totalSteps.value) {
    rafId = null
    return
  }
  rafId = window.requestAnimationFrame(step)
}

function start(): void {
  if (instant || rafId !== null) return
  lastTs = 0
  rafId = window.requestAnimationFrame(step)
}

watch(
  () => [props.text, props.segments, props.citations] as const,
  () => {
    if (instant) {
      revealed.value = Number.MAX_SAFE_INTEGER
      return
    }
    if (rafId !== null) {
      window.cancelAnimationFrame(rafId)
      rafId = null
    }
    revealed.value = 0
    start()
  },
  { deep: false },
)

if (!instant) start()

onUnmounted(() => {
  if (rafId !== null) {
    window.cancelAnimationFrame(rafId)
    rafId = null
  }
})

function citationFor(index: number): CitationModel | null {
  return props.citations.find((c) => c.index === index) ?? null
}

// 每段在揭示序列中的起始偏移；用于按 revealed 决定显示多少字符。
function visibleLength(segIndex: number): number {
  let offset = 0
  for (let i = 0; i < segIndex; i++) {
    const s = props.segments[i]
    offset += s.kind === 'text' ? s.value.length : 1
  }
  const s = props.segments[segIndex]
  const length = s.kind === 'text' ? s.value.length : 1
  return Math.max(0, Math.min(revealed.value - offset, length))
}
</script>

<template>
  <p class="answer-text" :aria-label="text">
    <template v-for="(s, i) in segments" :key="i">
      <!-- 文本段：按揭示进度截取 -->
      <template v-if="s.kind === 'text'">{{ s.value.slice(0, visibleLength(i)) }}</template>
      <!-- 引用段：未揭示时用等宽空格占位（保持布局）；揭示后渲染 CitationMark -->
      <template v-else>
        <span v-if="visibleLength(i) === 0" class="cite-placeholder" aria-hidden="true">{{ ' '.repeat(3) }}</span>
        <CitationMark
          v-else-if="citationFor(s.index)"
          :index="s.index"
          :source-id="citationFor(s.index)!.source.sourceId"
          :source-title="citationFor(s.index)!.source.title"
        />
      </template>
    </template>
  </p>
</template>

<style scoped>
.answer-text {
  margin: 0;
  font-size: var(--text-body);
  line-height: var(--line-height-body);
  color: var(--dm-ink);
}
.cite-placeholder {
  display: inline;
  white-space: pre;
  font-family: var(--font-mono);
  color: var(--dm-ink-dim);
}
</style>
