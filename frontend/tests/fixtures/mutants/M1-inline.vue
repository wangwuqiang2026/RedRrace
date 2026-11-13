<template>
  <div>
    <p style="color: #8E2430">破坏法 M1a：模板内联 style 属性写死品牌红</p>
    <svg width="16" height="16"><circle cx="8" cy="8" r="6" fill="#166534" /></svg>
    <span :style="{ color: '#A02020' }">破坏法 M1b：绑定样式对象里的错误红</span>
  </div>
</template>
<style scoped>
.m1 { color: var(--cite-grey); }
</style>
