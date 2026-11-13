<script setup lang="ts">
// ConflictPair —— 红线 R1 的落点（简报 S5，测试即验收）：
//  1. 两条来源视觉等权：同一 SourceCard 组件、同一 props 模型，仅数据不同；
//     模板不绑定任何动态 inline style、不加 muted/dim 等主次类、无「推荐/更可信」文案。
//  2. 固定排序与可信度无关：恒按 source_id 升序（lead 裁决 5），组件层再排一次做双保险，
//     DOM 顺序=视觉顺序。
//  3. 窄屏（<768px）纵向堆叠，样式仍等权（§5.2 第 4 条）。
// props 只吃前端模型；后端字段名一律经 src/api/adapter.ts 转换（lead 约束，阶段三改适配层即可）。
import { computed } from 'vue'
import type { ConflictModel } from '../api/model'
import { compareSourceCodepoint } from '../api/adapter'
import SourceCard from './SourceCard.vue'

const props = defineProps<{ conflict: ConflictModel }>()

// N-3：码点序=后端 Python sorted() 同序（契约级排序，不用 localeCompare）。
const orderedSides = computed(() =>
  [...props.conflict.sides].sort((a, b) => compareSourceCodepoint(a.sourceId, b.sourceId)),
)

// J-1（约束 4「冲突不取舍」）：不截断——契约层（schema min/maxItems + 构造校验）已拦 ≠2，
// 若上游防线全部失守塞进三条，组件仍全量渲染（宁可暴露异常，不丢记载）；中文数序标签兜底。
const SIDE_LABELS = ['记载一', '记载二', '记载三', '记载四', '记载五'] as const
</script>

<template>
  <section class="conflict-band" data-test="conflict" aria-label="两处记载不一致的冲突并列">
    <h3 class="conflict-title" data-test="conflict-title">
      <svg
        data-icon="diamond"
        viewBox="0 0 24 24"
        width="18"
        height="18"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        aria-hidden="true"
      >
        <path d="M12 2.5 21.5 12 12 21.5 2.5 12z" />
      </svg>
      两处记载不一致：「{{ conflict.subject }}」的「{{ conflict.predicate }}」存在两种来源记载
    </h3>
    <ul role="list" class="conflict-grid">
      <li v-for="(side, i) in orderedSides" :key="side.sourceId" class="conflict-side">
        <p class="side-label">{{ SIDE_LABELS[i] }}</p>
        <SourceCard :src="side" />
      </li>
    </ul>
  </section>
</template>

<style scoped>
.conflict-band {
  background: var(--brand-red-tint);
  border-radius: var(--radius-1);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.conflict-title {
  margin: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-body);
  font-weight: var(--fw-medium);
  color: var(--brand-red);
}
.conflict-grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  /* I-7（review-F2）：J-1 后 >2 条也要渲染——auto-fit 让 N 条均分同宽一行，
   * 固定 1fr 1fr 会把第三条甩成孤行，观感上变成"补充说明"，违 R1 等权。 */
  grid-template-columns: repeat(auto-fit, minmax(0, 1fr));
  gap: var(--space-4);
}
.conflict-side {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  min-width: 0;
}
.side-label {
  margin: 0;
  font-size: var(--text-meta);
  font-weight: var(--fw-medium);
  color: var(--ink);
}
/* 窄屏纵向堆叠且仍等权（§5.2 第 4 条；红线自动化判据见 视觉验收-阶段零F C1） */
@media (max-width: 767px) {
  .conflict-grid {
    grid-template-columns: 1fr;
  }
}
</style>
