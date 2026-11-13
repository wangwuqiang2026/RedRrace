<script setup lang="ts">
import PhaseEmptyState from '../components/PhaseEmptyState.vue'
</script>

<template>
  <PhaseEmptyState phase="阶段五" title="地图">
    <ul>
      <li>主视图：省级/中国 GeoJSON + 散点，点位旁直接标注地名（§5.4）。</li>
      <li>存疑点位与时间轴同一套标记语言：菱形 +「[存疑]」前缀文字。</li>
      <li>点击点位弹出内嵌出处卡的回链卡片；popup 可键盘聚焦。</li>
      <li>右侧（窄屏改下方）「尚未定位的地点」面板：未定位不画点，列表仍带出处。</li>
      <li>降级两级：地理数据加载失败→自动切可排序地点列表 + 错误红「重试」条；用户主动选列表→中性说明条。</li>
      <li>图表库在阶段五按需引入，壳阶段不加载任何图表依赖。</li>
    </ul>
  </PhaseEmptyState>
</template>
