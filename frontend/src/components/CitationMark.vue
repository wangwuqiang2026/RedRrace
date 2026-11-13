<script setup lang="ts">
// CitationMark —— 句末上标引用编号（规范 §5.1.2，红线 R2 的载体）。
// 三通道：可见文字 [n] + 上标形态 + aria-label「出处 n：{标题}」；a[href] 天然 Tab 可聚焦。
// 点击滚动定位到对应 SourceCard（#source-{id}）并 ≤1.2s 浅红底闪烁（§5.1 / 清单 B4）。
const props = defineProps<{ index: number; sourceId: string; sourceTitle: string }>()

function jump(): void {
  const el = document.getElementById(`source-${props.sourceId}`)
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  el.classList.add('cite-flash')
  window.setTimeout(() => el.classList.remove('cite-flash'), 1200)
}
</script>

<template>
  <sup class="citation-mark">
    <a
      data-test="cite-ref"
      :href="`#source-${props.sourceId}`"
      :aria-label="`出处 ${props.index}：${props.sourceTitle}`"
      @click.prevent="jump"
    >[{{ props.index }}]</a>
  </sup>
</template>

<style scoped>
.citation-mark a {
  color: var(--link-blue);
  font-size: var(--text-sup);
  font-weight: var(--fw-medium);
  text-decoration: none;
}
.citation-mark a:hover {
  text-decoration: underline;
}
</style>
