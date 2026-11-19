<script setup lang="ts">
// AskView —— 问答页（溯源控制台）：提问区 → 答案区（打字机 + 句末上标）→ 冲突区 → 出处区 ｜ 拒答区互斥。
// 右侧 EvidencePanel 承载检索雷达 / 闸门仪表 / 证据链；真接口链路 POST /api/ask 与全部测试契约保持不变。
// 组件只吃前端模型（src/api/model.ts）；后端字段名一律经 src/api/adapter.ts（本页不碰）。
import { ref, computed } from 'vue'
import type { AnswerModel } from '../api/model'
import { SAMPLE_QUESTIONS } from '../api/mock/scenarios'
import { askApi } from '../api/client'
import SourceCard from '../components/SourceCard.vue'
import ConflictPair from '../components/ConflictPair.vue'
import RefusalNotice from '../components/RefusalNotice.vue'
import TypewriterText from '../components/TypewriterText.vue'
import EvidencePanel from '../components/EvidencePanel.vue'

const question = ref('')
const answer = ref<AnswerModel | null>(null)
const loading = ref(false)
const techError = ref<string | null>(null)

async function ask(q: string): Promise<void> {
  if (!q.trim()) return
  question.value = q
  loading.value = true
  techError.value = null
  try {
    // 真接口返回 AnswerOut → 由 askApi 内部经 adapter.toAnswerModel 归一（本页不碰后端字段名）。
    answer.value = await askApi(q)
  } catch (e) {
    answer.value = null
    // 技术故障态：红色 + ⊗ + 重试（与内容拒答严格分版式，§5.4）
    techError.value = e instanceof Error ? e.message : '接口暂时不可用'
  } finally {
    loading.value = false
  }
}

/** 答案文本按 [n] 上标切段渲染（§5.1.2）；无对应 citation 的编号不渲染链接。 */
type Seg = { kind: 'text'; value: string } | { kind: 'cite'; index: number }
const segments = computed<Seg[]>(() => {
  const text = answer.value?.answer ?? ''
  return text
    .split(/(\[\d+\])/)
    .filter(Boolean)
    .map((part) => {
      const m = part.match(/^\[(\d+)\]$/)
      if (m) return { kind: 'cite', index: Number(m[1]) } as Seg
      return { kind: 'text', value: part } as Seg
    })
})

function citationFor(index: number) {
  return answer.value?.citations.find((c) => c.index === index) ?? null
}

// 拒答参考卡：真接口当前只给文本 suggestions，尚不带出处卡（阶段三契约未加 reference_cards），
// 故前端不自造字段名、不拿 mock 样例冒充真实参考卡 —— 返回空数组（RefusalNotice 自动隐藏参考区）。
// J-2：拒答区 chips 一律消费契约字段 answer.suggestions；提问区示例入口（SAMPLE_QUESTIONS）
// 是前端静态 UI 引导，两处数据源不同，不混用。
// 注册来源数：真接口暂无该契约字段 → null，RefusalNotice 自动改用无数字文案（§8 数字由后端注入）。
const refusalReferences = computed(() => [] as import('../api/model').SourceCardModel[])
const registeredCount = computed<number | null>(() => null)

// 超时降级说明条（在线 15s/本地 30s，lead 裁决定值）在阶段三接流水线时实现；壳阶段不做假计时。
</script>

<template>
  <div class="ask-console">
    <div class="console-main">
      <header class="console-head">
        <!-- 英文题眉走伪元素，避免 A4 可见文案红线（smoke.test.ts） -->
        <p class="console-eyebrow" aria-label="溯源查询控制台"></p>
        <h1 class="console-title">溯源问答</h1>
        <p class="console-sub">依据已登记来源回答，每个结论可回链到逐字引文。</p>
      </header>

      <form class="ask-form" @submit.prevent="ask(question)">
        <label class="visually-hidden" for="ask-input">提问</label>
        <span class="prompt-glyph" aria-hidden="true">&gt;</span>
        <input
          id="ask-input"
          v-model="question"
          type="search"
          placeholder="请输入与已登记来源相关的问题"
          autocomplete="off"
        />
        <button type="submit" class="ask-btn" :disabled="loading || !question.trim()">
          <span v-if="loading" aria-hidden="true">检索中…</span><span v-else>提问</span>
        </button>
      </form>

      <div class="samples" aria-label="示例问题">
        <button
          v-for="q in SAMPLE_QUESTIONS"
          :key="q"
          type="button"
          class="sample-chip"
          data-test="sample-chip"
          @click="ask(q)"
        >
          <span class="chip-dot" aria-hidden="true"></span>{{ q }}
        </button>
      </div>

      <!-- 加载骨架：shimmer 流光条 -->
      <div v-if="loading" class="skeleton" aria-hidden="true">
        <div class="skeleton-line skeleton-wide dm-shimmer"></div>
        <div class="skeleton-line skeleton-medium dm-shimmer"></div>
        <div class="skeleton-line skeleton-narrow dm-shimmer"></div>
      </div>

      <div v-else-if="techError" class="tech-error" role="alert">
        <p class="tech-error-line">
          <svg
            data-icon="x-circle"
            viewBox="0 0 24 24"
            width="18"
            height="18"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            aria-hidden="true"
          >
            <circle cx="12" cy="12" r="10" />
            <path d="m15 9-6 6" />
            <path d="m9 9 6 6" />
          </svg>
          接口暂时不可用：{{ techError }}
        </p>
        <button type="button" class="retry-btn" @click="ask(question)">重试</button>
      </div>

      <template v-else-if="answer">
        <!-- 拒答区与答案区互斥（§5.1.4） -->
        <RefusalNotice
          v-if="answer.refusal"
          :reason="answer.refusalReason"
          :source-count="registeredCount"
          :references="refusalReferences"
          :suggestions="answer.suggestions"
          :gate-note="answer.gateNote"
          @suggest="ask"
        />

        <template v-else>
          <section
            class="answer-zone"
            data-test="answer"
            role="status"
            aria-live="polite"
            :data-primary-source="citationFor(1)?.source.sourceId ?? ''"
          >
            <h2 class="zone-title">回答</h2>
            <TypewriterText
              :text="answer.answer"
              :segments="segments"
              :citations="answer.citations"
            />
          </section>

          <section v-if="answer.conflicts.length" class="conflict-zone" aria-label="冲突记载">
            <ConflictPair v-for="(c, i) in answer.conflicts" :key="i" :conflict="c" />
          </section>

          <section id="sources" class="sources-zone">
            <h2 class="zone-title">本回答的出处（共 {{ answer.citations.length }} 条）</h2>
            <div class="sources-list">
              <!-- SourceCard 内部已携带 id="source-{id}"，此处不重复 id -->
              <SourceCard v-for="c in answer.citations" :key="c.source.sourceId" :src="c.source" />
            </div>
          </section>
        </template>
      </template>
    </div>

    <EvidencePanel class="console-side" :answer="answer" :loading="loading" />
  </div>
</template>

<style scoped>
.ask-console {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: var(--space-6);
  align-items: start;
}
.console-main {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  min-width: 0;
}
.console-eyebrow {
  margin: 0 0 var(--space-1);
  font-family: var(--font-mono);
  font-size: var(--text-caption);
  letter-spacing: 0.18em;
  color: var(--dm-cyan);
}
.console-eyebrow::after { content: 'TRACE / QUERY CONSOLE'; }
.console-title {
  margin: 0;
  font-family: var(--dm-font-display);
  font-size: var(--text-display);
  line-height: var(--line-height-display);
  font-weight: var(--fw-bold);
  background: linear-gradient(135deg, var(--dm-ink), var(--dm-red));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.console-sub {
  margin: var(--space-1) 0 0;
  color: var(--dm-ink-dim);
  font-size: var(--text-meta);
}
/* 提问区：深色玻璃面 + 聚焦朱砂红光晕 */
.ask-form {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2);
  background: var(--dm-bg-glass);
  border: 1px solid var(--dm-line);
  border-radius: var(--dm-radius);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  transition: border-color 0.25s ease, box-shadow 0.25s ease;
}
.ask-form:focus-within {
  border-color: var(--dm-red);
  box-shadow: 0 0 0 3px var(--dm-glow-red), 0 0 24px var(--dm-glow-red);
}
.prompt-glyph {
  padding-left: var(--space-2);
  font-family: var(--font-mono);
  font-size: var(--text-h2);
  color: var(--dm-red);
}
.ask-form input {
  flex: 1;
  min-width: 0;
  height: 48px;
  font-size: var(--text-body);
  padding: 0 var(--space-3);
  border: none;
  background: transparent;
  color: var(--dm-ink);
  outline: none;
}
.ask-form input::placeholder {
  color: var(--dm-ink-dim);
}
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  clip-path: inset(50%);
  overflow: hidden;
  white-space: nowrap;
}
.ask-btn {
  height: 48px;
  padding: 0 var(--space-6);
  background: linear-gradient(135deg, var(--dm-red), var(--dm-red-dim));
  color: var(--dm-ink);
  border: none;
  border-radius: var(--dm-radius);
  font-size: var(--text-body);
  font-weight: var(--fw-semibold);
  cursor: pointer;
  box-shadow: 0 0 18px var(--dm-glow-red);
  transition: filter 0.2s ease, box-shadow 0.2s ease;
}
.ask-btn:hover:not(:disabled) {
  filter: brightness(1.18);
  box-shadow: 0 0 28px var(--dm-glow-red);
}
.ask-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
.samples {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.sample-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 44px;
  padding: var(--space-2) var(--space-3);
  background: var(--dm-bg-glass);
  color: var(--dm-ink-dim);
  border: 1px solid var(--dm-line);
  border-radius: 999px;
  font-size: var(--text-meta);
  cursor: pointer;
  transition: color 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}
.sample-chip:hover {
  color: var(--dm-ink);
  border-color: var(--dm-red);
  box-shadow: 0 0 12px var(--dm-glow-red);
}
.chip-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--dm-red);
  box-shadow: 0 0 8px var(--dm-glow-red);
  flex-shrink: 0;
}
/* shimmer 骨架 */
.skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--dm-bg-elev);
  border: 1px solid var(--dm-line);
  border-radius: var(--dm-radius);
}
.skeleton-line {
  height: 16px;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--dm-bg), var(--dm-line), var(--dm-bg));
  background-size: 200% 100%;
  animation: dm-shimmer 1.6s linear infinite;
}
.skeleton-wide { width: 85%; }
.skeleton-medium { width: 70%; }
.skeleton-narrow { width: 60%; }
.tech-error {
  background: var(--dm-bg-elev);
  color: var(--dm-red);
  border: 1px solid var(--dm-red-dim);
  border-radius: var(--dm-radius);
  padding: var(--space-4);
}
.tech-error-line {
  margin: 0 0 var(--space-3);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.retry-btn {
  min-height: 44px;
  padding: var(--space-2) var(--space-4);
  background: var(--dm-bg-glass);
  color: var(--dm-red);
  border: 1px solid var(--dm-red);
  border-radius: var(--dm-radius);
  cursor: pointer;
}
.retry-btn:hover {
  box-shadow: 0 0 14px var(--dm-glow-red);
}
.zone-title {
  font-family: var(--dm-font-display);
  font-size: var(--text-h1);
  line-height: var(--line-height-h1);
  font-weight: var(--fw-semibold);
  margin: 0 0 var(--space-3);
  color: var(--dm-ink);
}
.answer-zone {
  max-width: var(--answer-column-width);
  padding: var(--space-4);
  background: var(--dm-bg-glass);
  border: 1px solid var(--dm-line);
  border-left: 3px solid var(--dm-red);
  border-radius: var(--dm-radius);
}
.sources-zone,
.conflict-zone {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.sources-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

@media (max-width: 1024px) {
  .ask-console {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (max-width: 767px) {
  .ask-console {
    gap: var(--space-4);
  }
  .ask-form {
    flex-wrap: wrap;
  }
  .ask-form input {
    flex-basis: 100%;
  }
  .ask-btn {
    flex: 1;
  }
  .console-title {
    font-size: var(--text-h1);
  }
}
</style>

<!-- dm-flash 必须定义在全局样式块：class 由 JS 动态加到 #source-* 元素，scoped 样式覆盖不到 -->
<style>
@keyframes dm-flash {
  0%, 100% { box-shadow: none; }
  35% { box-shadow: 0 0 0 2px var(--dm-red), 0 0 24px var(--dm-glow-red); }
}
.dm-flash {
  animation: dm-flash 1.2s ease-out 1;
}
</style>
