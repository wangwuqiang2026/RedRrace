<script setup lang="ts">
// 阶段占位空状态（简报 S7）：显示「本视图将在阶段X接入」+ 取自设计规范的最终形态线框说明。
// 纪律：壳阶段不写假图表、不引图表库、不放假数据（视觉验收清单 D/E/F/G/H 组属阶段五~七）。
defineProps<{
  phase: string // 如「阶段五」
  title: string // 页面名（中文）
}>()
</script>

<template>
  <section class="empty-state">
    <h1 class="page-title">{{ title }}</h1>
    <p class="phase-note">
      <span class="phase-badge" aria-hidden="true">◇</span>
      本视图将在{{ phase }}接入。当前为阶段零F 前端壳，页面不展示任何假数据。
    </p>
    <div class="wireframe">
      <h2 class="wireframe-title">最终形态线框说明（取自设计规范）</h2>
      <slot />
    </div>
  </section>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}
.page-title {
  font-family: var(--font-serif);
  font-size: var(--text-display);
  line-height: var(--line-height-display);
  font-weight: var(--fw-bold);
}
.phase-note {
  margin: 0;
  background: var(--paper-muted);
  color: var(--cite-grey);
  font-size: var(--text-body);
  padding: var(--space-4);
  border-radius: var(--radius-1);
}
.phase-badge {
  color: var(--disputed);
  margin-right: var(--space-2);
}
.wireframe {
  background: var(--paper-card);
  border: 1px solid var(--line-border);
  border-radius: var(--radius-1);
  padding: var(--space-6);
}
.wireframe-title {
  font-family: var(--font-serif);
  font-size: var(--text-h1);
  line-height: var(--line-height-h1);
  font-weight: var(--fw-semibold);
  margin-bottom: var(--space-4);
}
.wireframe :deep(ul) {
  margin: 0;
  padding-left: var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.wireframe :deep(p) {
  margin: 0 0 var(--space-3);
}
</style>
