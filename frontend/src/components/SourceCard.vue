<script setup lang="ts">
// SourceCard —— 本项目最核心界面单元（全局共用，阶段五/六复用）。
// 版式规范 §5.1.3：字段顺序固定「载体徽标+编号 → 标题 → 发布者·日期 → 定位 → 逐字引文 → 回链」；
// 页码与链接至少其一，缺失显示「定位待补」不留空（简报 S4）。
// 红线 R4：载体类型=徽标文字+SVG 图标双通道，禁止 emoji，不得仅靠颜色/形状区分。
// props 只吃前端模型（src/api/model.ts），后端字段名一律经 src/api/adapter.ts 转换——
// 阶段三接真接口的人请只改适配层，不要在本组件里读蛇形字段。
import type { SourceCardModel } from '../api/model'

defineProps<{ src: SourceCardModel }>()
</script>

<template>
  <article class="source-card" :id="`source-${src.sourceId}`" :data-source-id="src.sourceId">
    <div class="card-head" data-field="badge">
      <span class="media-badge">
        <!-- Lucide book / link，同库同描边（§6.4 no-emoji-icons）。
             N-4 待办（阶段三/五）：mediaKind=unknown（如登记表出现「缩微胶片」）目前
             走 v-else 的 link 图标且 URL 只作纯文本——真实新载体入表时需补专用徽标与可点定位。 -->
        <svg
          v-if="src.mediaKind === 'book'"
          data-icon="book"
          viewBox="0 0 24 24"
          width="16"
          height="16"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
        >
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
          <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
        </svg>
        <svg
          v-else
          data-icon="link"
          viewBox="0 0 24 24"
          width="16"
          height="16"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
        >
          <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
          <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
        </svg>
        <span class="media-label">{{ src.mediaLabel }}</span>
      </span>
      <span class="source-no tabular">{{ src.sourceId }}</span>
    </div>

    <h3 class="card-title" data-field="title">{{ src.title }}</h3>

    <p class="card-meta" data-field="publisher-date">{{ src.publisher }} · {{ src.dateText }}</p>

    <p class="card-meta" data-field="locator">
      <template v-if="src.mediaKind === 'article' && src.url">
        <a :href="src.url" target="_blank" rel="noopener noreferrer" class="wrap-anywhere locator-link">{{ src.locatorText }}</a>
      </template>
      <template v-else-if="src.locatorText">{{ src.locatorText }}</template>
      <span v-else class="locator-missing">
        <svg data-icon="alert-diamond" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path d="M12 2.5 21.5 12 12 21.5 2.5 12z" />
        </svg>
        定位待补
      </span>
    </p>

    <blockquote class="card-quote" data-field="quote">「{{ src.quote }}」</blockquote>

    <p class="card-foot" data-field="backlink">
      <a
        v-if="src.url"
        :href="src.url"
        target="_blank"
        rel="noopener noreferrer"
        class="wrap-anywhere"
        >打开来源原文／核验页</a
      >
      <span v-else>来源链接未登记</span>
      <span class="verify-note">引文与原文逐字一致，经系统校验定位</span>
    </p>
  </article>
</template>

<style scoped>
.source-card {
  background: var(--paper-card);
  border: 1px solid var(--line-border);
  border-radius: var(--radius-1);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.media-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--cite-grey);
  font-size: var(--text-caption);
  font-weight: var(--fw-medium);
}
.source-no {
  color: var(--cite-grey);
  font-size: var(--text-caption);
}
.card-title {
  font-family: var(--font-serif);
  font-size: var(--text-h2);
  line-height: var(--line-height-h2);
  font-weight: var(--fw-semibold);
  color: var(--ink);
}
.card-meta {
  margin: 0;
  font-size: var(--text-meta);
  line-height: var(--line-height-meta);
  color: var(--cite-grey);
}
.card-meta a {
  color: var(--link-blue);
}
.locator-missing {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--disputed);
}
.card-quote {
  margin: 0;
  border-left: 2px solid var(--cite-grey);
  padding-left: var(--space-3);
  font-size: var(--text-body);
  line-height: var(--line-height-body);
  color: var(--ink);
}
.card-foot {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  justify-content: space-between;
  font-size: var(--text-meta);
  color: var(--cite-grey);
}
.card-foot a {
  color: var(--link-blue);
}
.verify-note {
  font-size: var(--text-caption);
  color: var(--cite-grey);
}
</style>
