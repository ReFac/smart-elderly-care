<template>
  <div>
    <div class="topbar">
      <h1>今日餐食</h1>
      <p>每天吃什么，家属一目了然</p>
    </div>
    <div class="card" v-for="m in menus" :key="m.id">
      <h3>{{ label(m.mealType) }}</h3>
      <p>{{ m.dishes }}</p>
      <p class="muted" style="font-size: 12px">{{ m.dietTags }}</p>
    </div>
    <div class="card" v-if="!menus.length"><p class="muted">今日菜单暂未发布</p></div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import http from '../api';

const menus = ref<any[]>([]);
function label(v: string) {
  return ({ breakfast: '早餐', lunch: '午餐', dinner: '晚餐' } as any)[v] || v;
}
onMounted(async () => {
  menus.value = await http.get('/meals/today');
});
</script>
