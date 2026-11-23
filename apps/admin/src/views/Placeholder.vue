<template>
  <div class="page-card">
    <h2 class="page-title">{{ title }}</h2>
    <div class="placeholder-box">
      <p>{{ info?.message || '模块接口已预留，后续版本实现。' }}</p>
      <p style="font-size: 13px">扩展点：Feature Flag + 独立 Nest Module，可按机构定制启用。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import http from '../api/http';

const props = defineProps<{ title: string; module: string }>();
const info = ref<any>(null);

onMounted(async () => {
  try {
    info.value = await http.get(`/${props.module}/stub`);
  } catch {
    info.value = { message: `${props.title} 模块已在侧栏预留，后端 stub 可扩展` };
  }
});
</script>
