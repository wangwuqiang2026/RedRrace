<script setup lang="ts">
import PhaseEmptyState from '../components/PhaseEmptyState.vue'
</script>

<template>
  <PhaseEmptyState phase="阶段五" title="卡片库">
    <ul>
      <li>按主题检索事件与人物卡片，卡片与出处一一对应。</li>
      <li>卡片版式与问答页出处卡同构（设计规范 §5.1.3：徽标+编号→标题→发布者·日期→定位→逐字引文→回链）。</li>
      <li>超过 50 条启用虚拟滚动（§7 virtualize-lists）。</li>
    </ul>
  </PhaseEmptyState>
</template>
