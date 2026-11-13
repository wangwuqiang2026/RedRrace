<script setup lang="ts">
import PhaseEmptyState from '../components/PhaseEmptyState.vue'
</script>

<template>
  <PhaseEmptyState phase="阶段七" title="审核台">
    <ul>
      <li>日志行字段固定：问题 → 答案摘要 → 逐句展开区 → 出处卡列表 → 元数据（耗时/提示词版本，引用灰）（§5.8）。</li>
      <li>逐句三状态=颜色+图标+文字三通道：✓ 通过（绿）｜✎ 需修改（橙褐）｜⊘ 拒答（深蓝灰中性系，不是错误红）。</li>
      <li>错误红在审核台不出现——它只留给技术故障且必须带重试按钮（lead 裁决 6，红线 I5）。</li>
      <li>状态筛选 chips ≥44px 高，选中态三重区分；通过率/耗时数字等宽对齐。</li>
    </ul>
  </PhaseEmptyState>
</template>
