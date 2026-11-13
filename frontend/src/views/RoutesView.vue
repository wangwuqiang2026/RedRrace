<script setup lang="ts">
import PhaseEmptyState from '../components/PhaseEmptyState.vue'
</script>

<template>
  <PhaseEmptyState phase="阶段六" title="研学路线">
    <ul>
      <li>概要条（吸顶）：主题 · 天数 · 站点数 · 总时长（等宽数字），总时长必须带构成说明（§5.6）。</li>
      <li>站点序列为垂直步骤条：站名 →「为什么来」一句话（句末上标引用编号）→ 出处卡精简版 → 停留时长。</li>
      <li>无坐标站点不显示；页面如实写站点数，不做「完整路线」暗示。</li>
      <li>页脚汇总全部引用编号（与正文上标一致）+ 路线生成规则说明。</li>
    </ul>
  </PhaseEmptyState>
</template>
