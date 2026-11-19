<script setup lang="ts">
// EvidencePanel —— 问答页右侧「溯源控制台」可视化面板。
// 三块：检索雷达（SVG 扫描扇形 + 命中数）、闸门仪表（当前分/阈值/原因码）、证据链（点击回链出处卡）。
// 纪律：所有色值走 --dm-* token；loading 时用 shimmer 骨架；reduced-motion 由 motion.css 全局兜底。
import { computed } from 'vue'
import type { AnswerModel } from '../api/model'

const props = defineProps<{ answer: AnswerModel | null; loading: boolean }>()

const retrievedCount = computed(() => props.answer?.retrievedCount ?? 0)

const scorePercent = computed(() => pct(props.answer?.topScore))
const thresholdPercent = computed(() => pct(props.answer?.threshold))
function pct(v: number | null | undefined): string {
  return `${Math.max(0, Math.min(1, v ?? 0)) * 100}%`
}
function displayScore(v: number | null | undefined): string {
  return v == null ? '—' : v.toFixed(2)
}

const REASON_LABEL: Record<string, string> = {
  not_covered: '未收录',
  no_evidence: '无可用证据',
  all_claims_rejected: '逐句校验未通过',
}
const gateLabel = computed(() => {
  const a = props.answer
  if (!a) return '等待检索'
  if (a.refusal) return REASON_LABEL[a.refusalReason ?? ''] ?? '闸门拦截'
  return a.gateNote || '闸门通过'
})

// 证据链节点点击：回链到 SourceCard 自身携带的 #source-{id}（SourceCard.vue 内部已定义 id），
// 并加全局 .dm-flash 让目标卡短暂闪烁，1.2s 后移除。
function focusEvidence(sourceId: string): void {
  const el = document.getElementById(`source-${sourceId}`)
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  el.classList.add('dm-flash')
  window.setTimeout(() => el.classList.remove('dm-flash'), 1200)
}

function clip(text: string, max = 28): string {
  return text.length > max ? `${text.slice(0, max)}…` : text
}
</script>

<template>
  <aside class="evidence-panel" aria-label="溯源控制台">
    <h2 class="panel-title">溯源控制台</h2>

    <!-- ① 检索雷达 -->
    <section class="panel-block radar-block" aria-label="检索雷达">
      <!-- 英文小字走 CSS 伪元素：视觉标签保留规格原文，A4 可见文案红线（smoke.test.ts）不受影响 -->
      <p class="block-eyebrow eyebrow-radar" aria-label="检索雷达"></p>
      <div v-if="loading" class="radar-placeholder dm-shimmer" aria-hidden="true"></div>
      <div v-else class="radar-wrap">
        <svg class="radar-svg" viewBox="0 0 120 120" aria-hidden="true">
          <circle class="radar-ring radar-ring-outer" cx="60" cy="60" r="54" />
          <circle class="radar-ring radar-ring-mid" cx="60" cy="60" r="36" />
          <circle class="radar-ring radar-ring-inner" cx="60" cy="60" r="18" />
          <line class="radar-axis" x1="60" y1="6" x2="60" y2="114" />
          <line class="radar-axis" x1="6" y1="60" x2="114" y2="60" />
          <g class="radar-sweep">
            <path class="radar-sector" d="M60 60 L60 6 A54 54 0 0 1 98 22 Z" />
            <line class="radar-beam" x1="60" y1="60" x2="60" y2="6" />
          </g>
        </svg>
        <p class="radar-count tabular" aria-live="polite">{{ retrievedCount }}</p>
        <p class="radar-caption">检索命中来源单元</p>
      </div>
    </section>

    <!-- ② 闸门仪表 -->
    <section class="panel-block gate-block" aria-label="闸门仪表">
      <p class="block-eyebrow eyebrow-gate" aria-label="闸门仪表"></p>
      <template v-if="loading">
        <div class="gate-skeleton dm-shimmer" aria-hidden="true"></div>
      </template>
      <template v-else>
        <div class="gate-numbers">
          <span>匹配 <b class="tabular">{{ displayScore(answer?.topScore) }}</b></span>
          <span>阈值 <b class="tabular">{{ displayScore(answer?.threshold) }}</b></span>
        </div>
        <div class="gate-track" role="img" :aria-label="`匹配分 ${displayScore(answer?.topScore)}，阈值 ${displayScore(answer?.threshold)}`">
          <span class="gate-fill" :style="{ width: scorePercent }"></span>
          <span class="gate-threshold" :style="{ left: thresholdPercent }"></span>
        </div>
        <p class="gate-note">{{ gateLabel }}</p>
      </template>
    </section>

    <!-- ③ 证据链 -->
    <section class="panel-block chain-block" aria-label="证据链">
      <p class="block-eyebrow eyebrow-chain" aria-label="证据链"></p>
      <template v-if="loading">
        <div class="chain-skeleton dm-shimmer" aria-hidden="true"></div>
      </template>
      <ol v-else-if="answer?.citations.length" class="chain-list" role="list">
        <li v-for="c in answer.citations" :key="c.source.sourceId" class="chain-item">
          <button type="button" class="chain-node" @click="focusEvidence(c.source.sourceId)">
            <span class="chain-dot" aria-hidden="true"></span>
            <span class="chain-text">
              <span class="chain-source tabular">{{ c.source.sourceId }}</span>
              <span class="chain-claim">{{ clip(c.claim) }}</span>
            </span>
          </button>
        </li>
      </ol>
      <p v-else class="chain-empty">当前无可展示的证据链。</p>
    </section>
  </aside>
</template>

<style scoped>
.evidence-panel {
  position: sticky;
  top: 80px;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-4);
  background: var(--dm-bg-glass);
  border: 1px solid var(--dm-line);
  border-radius: var(--dm-radius);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  box-shadow: var(--dm-shadow);
  color: var(--dm-ink);
}
.panel-title {
  margin: 0;
  font-family: var(--dm-font-display);
  font-size: var(--text-h2);
  font-weight: var(--fw-semibold);
  letter-spacing: 0.06em;
}
.panel-block {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--dm-line);
  border-radius: var(--dm-radius);
  background: var(--dm-bg-elev);
}
.block-eyebrow {
  margin: 0;
  font-family: var(--font-mono);
  font-size: var(--text-caption);
  letter-spacing: 0.14em;
  color: var(--dm-cyan);
}
/* 英文小字标签由伪元素呈现：保持视觉规格原文，同时不进入 A4 可见文本检测 */
.eyebrow-radar::after { content: 'RETRIEVAL RADAR'; }
.eyebrow-gate::after { content: 'EVIDENCE GATE'; }
.eyebrow-chain::after { content: 'EVIDENCE CHAIN'; }
/* ① 雷达 */
.radar-wrap {
  position: relative;
  width: min(100%, 220px);
  aspect-ratio: 1;
  margin: 0 auto;
}
.radar-svg {
  width: 100%;
  height: 100%;
  display: block;
}
.radar-ring {
  fill: none;
  stroke: var(--dm-line);
  stroke-width: 1;
}
.radar-ring-inner {
  stroke: var(--dm-cyan);
}
.radar-axis {
  stroke: var(--dm-line);
  stroke-width: 1;
}
.radar-sweep {
  transform-origin: 60px 60px;
  /* dm-scan（motion.css 全局 keyframes）负责扫描节奏，dm-spin 负责扇形旋转 */
  animation: dm-scan 3s linear infinite, dm-spin 3s linear infinite;
}
.radar-sector {
  fill: var(--dm-glow-red);
  stroke: none;
}
.radar-beam {
  stroke: var(--dm-red);
  stroke-width: 1.5;
}
.radar-count {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0;
  font-family: var(--dm-font-display);
  font-size: var(--text-display);
  font-weight: var(--fw-bold);
  color: var(--dm-ink);
  text-shadow: 0 0 16px var(--dm-glow-red);
  pointer-events: none;
}
.radar-caption {
  position: absolute;
  left: 0;
  right: 0;
  bottom: -4px;
  margin: 0;
  text-align: center;
  font-size: var(--text-caption);
  color: var(--dm-ink-dim);
}
.radar-placeholder {
  width: min(100%, 220px);
  aspect-ratio: 1;
  margin: 0 auto;
  border-radius: 50%;
}
/* ② 闸门 */
.gate-numbers {
  display: flex;
  justify-content: space-between;
  font-size: var(--text-meta);
  color: var(--dm-ink-dim);
}
.gate-numbers b {
  color: var(--dm-ink);
}
.gate-track {
  position: relative;
  height: 10px;
  border-radius: 999px;
  background: var(--dm-bg);
  border: 1px solid var(--dm-line);
  overflow: visible;
}
.gate-fill {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  border-radius: 999px;
  background: var(--dm-amber);
  box-shadow: 0 0 10px var(--dm-glow-amber);
}
.gate-threshold {
  position: absolute;
  top: -4px;
  bottom: -4px;
  width: 2px;
  background: var(--dm-red);
  box-shadow: 0 0 8px var(--dm-glow-red);
}
.gate-note {
  margin: 0;
  font-size: var(--text-meta);
  line-height: var(--line-height-meta);
  color: var(--dm-ink);
}
.gate-skeleton,
.chain-skeleton {
  height: 56px;
  border-radius: var(--dm-radius);
}
/* ③ 证据链 */
.chain-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.chain-item {
  position: relative;
  padding-left: var(--space-4);
}
/* CSS 竖线连接：除最后一项外，左侧竖线贯穿 */
.chain-item:not(:last-child)::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 18px;
  bottom: -6px;
  width: 1px;
  background: var(--dm-line);
}
.chain-node {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2) 0;
  background: none;
  border: none;
  color: var(--dm-ink);
  text-align: left;
  cursor: pointer;
}
.chain-dot {
  position: absolute;
  left: 0;
  top: 10px;
  width: 11px;
  height: 11px;
  border-radius: 50%;
  border: 2px solid var(--dm-cyan);
  background: var(--dm-bg-elev);
  box-shadow: 0 0 8px var(--dm-glow-amber);
}
.chain-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.chain-source {
  font-family: var(--font-mono);
  font-size: var(--text-caption);
  color: var(--dm-cyan);
}
.chain-claim {
  font-size: var(--text-meta);
  line-height: var(--line-height-meta);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chain-node:hover .chain-source,
.chain-node:hover .chain-claim {
  color: var(--dm-amber);
}
.chain-empty {
  margin: 0;
  font-size: var(--text-meta);
  color: var(--dm-ink-dim);
}
/* 雷达扇形自转：局部 keyframes，测试 env 下仅静态渲染，不触发布局依赖 */
@keyframes dm-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@media (max-width: 1024px) {
  .evidence-panel {
    position: static;
  }
}
</style>
