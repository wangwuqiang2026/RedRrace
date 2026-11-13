<script setup lang="ts">
import PhaseEmptyState from '../components/PhaseEmptyState.vue'
</script>

<template>
  <PhaseEmptyState phase="阶段五" title="时间轴">
    <ul>
      <li>顶部主题筛选 + 年份范围；主体横向（≥1024px）/纵向（<1024px）时间轴（§5.3）。</li>
      <li>主轴线为品牌红细线；年份刻度用等宽数字，间距随屏宽自动抽稀。</li>
      <li>事件节点=实心圆 + 事件名直接标注；存疑事件=空心菱形 + 标签前缀「[存疑]」文字。</li>
      <li>下方独立「年代待考」区：粒度未知条目不混入主轴，按卡片编号排序。</li>
      <li>图表容器带概述文本与「表格视图」开关（等价时间序数据表，可排序）；键盘可逐节点移动。</li>
      <li>图表库在阶段五按需引入，壳阶段不加载任何图表依赖。</li>
    </ul>
  </PhaseEmptyState>
</template>
