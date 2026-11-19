<script setup lang="ts">
// AskView —— 问答页（阶段三步骤 8：去 mock，接真接口）：提问区 → 答案区（句末上标）→ 冲突区 → 出处区 ｜ 拒答区互斥。
// 本页只走 `POST /api/ask` 真接口（src/api/client.ts）；mock 夹具只留在 tests 与 src/api/mock
// 供组件版式测试使用，生产入口不再有 VITE_USE_MOCK 分支。
// 组件只吃前端模型（src/api/model.ts）；后端字段名一律经 src/api/adapter.ts（lead 约束）。
import { ref, computed } from 'vue'
import type { AnswerModel } from '../api/model'
import { SAMPLE_QUESTIONS } from '../api/mock/scenarios'
import { askApi } from '../api/client'
import SourceCard from '../components/SourceCard.vue'
import ConflictPair from '../components/ConflictPair.vue'
import CitationMark from '../components/CitationMark.vue'
import RefusalNotice from '../components/RefusalNotice.vue'

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
  <div class="ask-page">
    <form class="ask-form" @submit.prevent="ask(question)">
      <label class="visually-hidden" for="ask-input">提问</label>
      <input
        id="ask-input"
        v-model="question"
        type="search"
        placeholder="请输入与已登记来源相关的问题"
        autocomplete="off"
      />
      <button type="submit" class="ask-btn" :disabled="loading || !question.trim()">
        <span v-if="loading" aria-hidden="true">（提交中）</span>提问
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
        {{ q }}
      </button>
    </div>

    <!-- >1s 显示骨架屏（§5.1.1）；壳阶段以静态骨架呈现 -->
    <div v-if="loading" class="skeleton" aria-hidden="true">
      <div class="skeleton-line" style="width: 85%"></div>
      <div class="skeleton-line" style="width: 70%"></div>
      <div class="skeleton-line" style="width: 60%"></div>
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
        <section class="answer-zone" data-test="answer" role="status" aria-live="polite">
          <h2 class="zone-title">回答</h2>
          <p class="answer-text">
            <template v-for="(seg, i) in segments" :key="i">
              <CitationMark
                v-if="seg.kind === 'cite' && citationFor(seg.index)"
                :index="seg.index"
                :source-id="citationFor(seg.index)!.source.sourceId"
                :source-title="citationFor(seg.index)!.source.title"
              />
              <span v-else>{{ seg.kind === 'text' ? seg.value : '' }}</span>
            </template>
          </p>
        </section>

        <section v-if="answer.conflicts.length" class="conflict-zone" aria-label="冲突记载">
          <ConflictPair v-for="(c, i) in answer.conflicts" :key="i" :conflict="c" />
        </section>

        <section id="sources" class="sources-zone">
          <h2 class="zone-title">本回答的出处（共 {{ answer.citations.length }} 条）</h2>
          <SourceCard v-for="c in answer.citations" :key="c.source.sourceId" :src="c.source" />
        </section>
      </template>
    </template>
  </div>
</template>

<style scoped>
.ask-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}
.ask-form {
  display: flex;
  gap: var(--space-3);
}
.ask-form input {
  flex: 1;
  min-width: 0;
  height: 48px;
  font-size: var(--text-body);
  padding: 0 var(--space-3);
  border: 1px solid var(--line-border);
  border-radius: var(--radius-1);
  background: var(--paper-card);
  color: var(--ink);
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
  background: var(--brand-red);
  color: var(--ink-inverse);
  border: none;
  border-radius: var(--radius-1);
  font-size: var(--text-body);
  font-weight: var(--fw-medium);
  cursor: pointer;
}
.ask-btn:hover:not(:disabled) {
  background: var(--brand-red-deep);
}
.ask-btn:disabled {
  opacity: 0.6;
  cursor: default;
}
.samples {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.sample-chip {
  min-height: 44px;
  padding: var(--space-2) var(--space-3);
  background: var(--paper-muted);
  color: var(--link-blue);
  border: 1px solid var(--line-border);
  border-radius: var(--radius-1);
  font-size: var(--text-meta);
  cursor: pointer;
}
.skeleton-line {
  height: 16px;
  background: var(--paper-muted);
  border-radius: var(--radius-1);
  margin-bottom: var(--space-2);
}
.tech-error {
  background: var(--error-red-bg);
  color: var(--error-red);
  border-radius: var(--radius-1);
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
  background: var(--paper-card);
  color: var(--error-red);
  border: 1px solid var(--error-red);
  border-radius: var(--radius-1);
  cursor: pointer;
}
.zone-title {
  font-family: var(--font-serif);
  font-size: var(--text-h1);
  line-height: var(--line-height-h1);
  font-weight: var(--fw-semibold);
  margin-bottom: var(--space-3);
}
.answer-zone {
  max-width: var(--answer-column-width);
}
.answer-text {
  margin: 0;
  font-size: var(--text-body);
  line-height: var(--line-height-body);
}
.sources-zone {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.conflict-zone {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
</style>
