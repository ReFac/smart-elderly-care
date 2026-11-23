<template>
  <div>
    <div class="topbar">
      <h1>账单透明</h1>
      <p>可查看所有账单与支出明细</p>
    </div>
    <div class="card" v-for="b in bills" :key="b.id">
      <h3>{{ b.elder?.name }} · ¥{{ b.totalAmount }}</h3>
      <div class="row"><span class="muted">状态</span><span>{{ b.status }}</span></div>
      <div class="row">
        <span class="muted">账期</span>
        <span>{{ fmt(b.periodStart) }} ~ {{ fmt(b.periodEnd) }}</span>
      </div>
      <div class="row" v-for="l in b.lines" :key="l.id">
        <span>{{ l.feeName }}</span>
        <span>¥{{ l.amount }}</span>
      </div>
      <div class="row"><span class="muted">已付</span><span>¥{{ b.paidAmount }}</span></div>
    </div>
    <div class="card" v-if="!bills.length"><p class="muted">暂无账单</p></div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import http from '../api';

const bills = ref<any[]>([]);
const me = ref<any>(null);

function fmt(v: string) {
  return new Date(v).toLocaleDateString();
}

onMounted(async () => {
  me.value = await http.get('/auth/me');
  const all: any[] = await http.get('/billing/bills');
  if (me.value.role === 'family') {
    const ids = new Set((me.value.elders || []).map((e: any) => e.id));
    bills.value = all.filter((b) => ids.has(b.elderId));
  } else {
    bills.value = all.slice(0, 10);
  }
});
</script>
