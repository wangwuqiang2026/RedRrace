<script setup lang="ts">
// AskView —— 问答页骨架（简报 S6）：提问区 → 答案区（句末上标）→ 冲突区 → 出处区 ｜ 拒答区互斥。
// 双模式：VITE_USE_MOCK=1 走本地契约样例；=0 走真接口（src/api/client.ts）。
// 纪律：本阶段无任何检索/生成逻辑；mock 文案全部标注「契约样例」，禁止假回答观感（简报 S9 演示话术）。
// 组件只吃前端模型（src/api/model.ts）；后端字段名一律经 src/api/adapter.ts（lead 约束）。
import { ref, computed } from 'vue'
import type { AnswerModel } from '../api/model'
import { toAnswerModel, toSourceCardModel } from '../api/adapter'
import { mockAsk, SAMPLE_QUESTIONS } from '../api/mock/scenarios'
import { SAMPLE_SOURCES } from '../api/mock/sources'
import { askApi } from '../api/client'
import SourceCard from '../components/SourceCard.vue'
import ConflictPair from '../components/ConflictPair.vue'
import CitationMark from '../components/CitationMark.vue'
import RefusalNotice from '../components/RefusalNotice.vue'

const USE_MOCK = import.meta.env.VITE_USE_MOCK === '1'

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
    // mock 与真接口都产出 AnswerOut 形状 → 同一适配路径（真实联调等阶段三，/api/ask 现为 501 占位）
    answer.value = USE_MOCK ? toAnswerModel(mockAsk(q)) : await askApi(q)
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

// 拒答参考卡：mock 模式取登记表样例前 3 条；
// 真接口的「最近邻参考」清单来源未定（AnswerOut.suggestions 现仅文本数组，撑不住带出处的参考项）。
// lead 2026-11-13 口径：阶段三契约定稿会加 reference_cards: list[Citation] 或把 suggestions
// 升级为对象数组——**字段没定下来之前，前端不得自造字段名去猜**（不可变契约第 3 条要求
// 参考项同样带出处）。本文件与 mock/scenarios.ts 均不加任何未登记的契约字段。
const refusalReferences = computed(() =>
  USE_MOCK ? SAMPLE_SOURCES.slice(0, 3).map((s) => toSourceCardModel(s)) : [],
)
// J-2：拒答区 chips 一律消费契约字段 answer.suggestions（mock 模式由 scenarios 以同字段供数）；
// 提问区示例入口（SAMPLE_QUESTIONS）是前端静态 UI 引导，两处数据源不同，不混用。
// 注册来源数：mock=样例数；真实模式暂无契约来源 → null，RefusalNotice 自动改用无数字文案
//（§8 数字由后端注入、前端禁写死；宁可少说一句，不许说错）。
const registeredCount = computed<number | null>(() => (USE_MOCK ? SAMPLE_SOURCES.length : null))

// 超时降级说明条（在线 15s/本地 30s，lead 裁决定值）在阶段三接流水线时实现；壳阶段不做假计时。
</script>

<template>
  <div class="ask-page">
    <p v-if="USE_MOCK" class="mock-banner" role="note">
      数据为契约样例，真实回答在阶段三接入——本页演示的是版式与信息层级，不是问答能力。
    </p>

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
.mock-banner {
  margin: 0;
  background: var(--paper-muted);
  color: var(--cite-grey);
  font-size: var(--text-meta);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-1);
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
