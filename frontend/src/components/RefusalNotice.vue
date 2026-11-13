<script setup lang="ts">
// RefusalNotice —— 拒答区（红线 R3/B5/B6/I5）。**措辞不在此自造**：句子来源是
// docs/设计规范.md §5.1.4「两类拒答的措辞封闭集」（D4 登记，2026-11-13），按 refusal_reason 取句：
//   not_covered → 主句「当前知识库未收录这个问题」＋说明句「这些来源中暂无记载。」
//                 （既有句，不许改动——plan 全局约束 3 要求答复含「未收录」字样）
//   no_evidence → 主句「这个问题暂时找不到可用记载」＋说明句
//                 「已登记的来源中找不到可支持的记载，为避免编造，不作回答。」
// 两类句子**不许互换、不许自造第三种句式**；既有句「不在当前来源范围内」保留可用，归属对应
// 关系未经裁决前不主动使用。版式前句「本系统只依据已登记的 {N} 个来源单元回答…」为 §5.1.4
// 线框通用句；N 无契约来源时（sourceCount=null）自动改用无数字变体（宁可少说一句，不许说错）。
//
// 红的分界（visual-qa 定稿，§5.1.4/D4）：**错误红 --error-red 只属于「可重试的技术故障」**
// （⊗ + 文字 + 重试按钮，那是第三种状态、不是拒答）；本组件（两类拒答）底色一律 --paper-muted、
// 文字 --refusal-ink、图标只用 ℹ；不得带 ⊗、不得 role="alert"（用普通 role="status"）。
// 在线生成超时（15s/本地 30s）属能力降级说明条，既非拒答也非报错，不得套用这里的主句。
// 禁止措辞：见规范 §5.1.4 D4 白名单外的报错系词（禁词完整清单以规范条文为准，不在此复述）。
// props 只吃前端模型（lead 约束：后端字段名只进 src/api/adapter.ts）。
import type { RefusalReason, SourceCardModel } from '../api/model'
import SourceCard from './SourceCard.vue'

const props = defineProps<{
  reason: RefusalReason // N-6：单一来源类型（model.ts），契约加拒答值只改一处
  /** 已登记来源单元数；真实模式暂无契约来源时传 null——宁可少说一句，不许说错（J-2，§8 数字由后端注入禁写死） */
  sourceCount: number | null
  references: SourceCardModel[]
  /** 必须是 answer.suggestions 契约字段的内容（J-2）；提问区的静态示例入口不在此列 */
  suggestions: string[]
}>()

const emit = defineEmits<{ (e: 'suggest', question: string): void }>()

const head = () =>
  props.reason === 'no_evidence' ? '这个问题暂时找不到可用记载' : '当前知识库未收录这个问题'
const body = () => {
  // 说明句逐字取自 §5.1.4 封闭集，不许改写
  const prefix =
    props.sourceCount == null
      ? '本系统只依据公开出版的红色文化电子书与权威官方发布文章等已登记来源回答。'
      : `本系统只依据已登记的 ${props.sourceCount} 个来源单元回答，来源为公开出版的红色文化电子书与权威官方发布文章。`
  if (props.reason === 'no_evidence') {
    return `${prefix}已登记的来源中找不到可支持的记载，为避免编造，不作回答。`
  }
  return `${prefix}关于这个问题，这些来源中暂无记载。`
}
</script>

<template>
  <section class="refusal-notice" data-test="refusal" role="status" aria-live="polite">
    <p class="refusal-head">
      <svg
        data-icon="info"
        viewBox="0 0 24 24"
        width="18"
        height="18"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="10" />
        <path d="M12 16v-4" />
        <path d="M12 8h.01" />
      </svg>
      {{ head() }}
    </p>
    <p class="refusal-body">{{ body() }}</p>

    <div class="refusal-try">
      <p class="try-label">您可以试试</p>
      <button
        v-for="s in suggestions"
        :key="s"
        type="button"
        class="suggest-chip"
        data-test="suggest-chip"
        @click="emit('suggest', s)"
      >
        {{ s }}
      </button>
    </div>

    <template v-if="references.length > 0">
      <p class="refusal-disclaimer">已收录的相近条目（仅参考，不构成对该问题的回答）：</p>
      <div class="refusal-refs">
        <SourceCard v-for="ref in references.slice(0, 3)" :key="ref.sourceId" :src="ref" />
      </div>
    </template>
  </section>
</template>

<style scoped>
/* 中性纸面底 + 说明文体（R3）：禁止红色、报错边框、⊗ 图标 */
.refusal-notice {
  background: var(--refusal-bg);
  color: var(--refusal-ink);
  border-radius: var(--radius-1);
  padding: var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.refusal-head {
  margin: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-body);
  font-weight: var(--fw-medium);
}
.refusal-body {
  margin: 0;
  font-size: var(--text-body);
  line-height: var(--line-height-body);
}
.try-label {
  margin: 0 0 var(--space-2);
  font-size: var(--text-meta);
  color: var(--cite-grey);
}
.suggest-chip {
  min-height: 44px;
  padding: var(--space-2) var(--space-3);
  margin: 0 var(--space-2) var(--space-2) 0;
  background: var(--paper-card);
  color: var(--link-blue);
  border: 1px solid var(--line-border);
  border-radius: var(--radius-1);
  font-size: var(--text-meta);
  cursor: pointer;
}
/* 免责句按 §5.1.4 用 16px 正文，不用灰字弱化 */
.refusal-disclaimer {
  margin: 0;
  font-size: var(--text-body);
  color: var(--ink);
}
.refusal-refs {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
</style>
