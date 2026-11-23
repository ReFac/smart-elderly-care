<template>
  <div class="nh-page">
    <header class="nh-page-header">
      <div>
        <p class="nh-kicker">Operations</p>
        <h1 class="nh-title">运营看板</h1>
        <p class="nh-subtitle">入住、照护与营收一屏总览。右侧 Agent 可直接帮你跳转或起草高权限变更。</p>
      </div>
    </header>

    <section class="stat-grid">
      <div class="stat-item" v-for="s in stats" :key="s.label">
        <div class="label">{{ s.label }}</div>
        <div class="value">{{ s.value }}</div>
      </div>
    </section>

    <div class="dash-grid">
      <section class="page-card">
        <h3 class="sec-title">老人自理结构</h3>
        <el-table :data="overview?.careLevelGroups || []" size="small">
          <el-table-column prop="careLevel" label="等级" :formatter="(_, __, v) => levelLabel(v)" />
          <el-table-column prop="_count" label="人数" />
        </el-table>
      </section>
      <section class="page-card">
        <h3 class="sec-title">今日待办</h3>
        <ul class="todo">
          <li><span>待执行照护任务</span><b>{{ overview?.pendingTasks ?? '-' }}</b></li>
          <li><span>欠费 / 未结清</span><b>{{ overview?.unpaidBills ?? '-' }}</b></li>
          <li><span>30 日内合同到期</span><b>{{ overview?.expiringContracts ?? '-' }}</b></li>
          <li><span>本月已收</span><b>¥{{ overview?.monthRevenue ?? 0 }}</b></li>
        </ul>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import http from '../api/http';
import { CARE_LEVEL_LABELS } from '@nh/shared';

const overview = ref<any>(null);

const stats = computed(() => [
  { label: '总床位', value: overview.value?.totalBeds ?? '-' },
  { label: '入住床位', value: overview.value?.occupiedBeds ?? '-' },
  { label: '空闲床位', value: overview.value?.idleBeds ?? '-' },
  { label: '入住率%', value: overview.value?.occupancyRate ?? '-' },
  { label: '在院老人', value: overview.value?.activeElders ?? '-' },
  { label: '欠费账单', value: overview.value?.unpaidBills ?? '-' },
]);

function levelLabel(v: string) {
  return (CARE_LEVEL_LABELS as any)[v] || v;
}

onMounted(async () => {
  overview.value = await http.get('/dashboard/overview');
});
</script>

<style scoped>
.dash-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.sec-title {
  margin: 0 0 12px;
  font-family: var(--nh-display);
  font-size: 1rem;
  font-weight: 700;
}
.todo {
  list-style: none;
  margin: 0;
  padding: 0;
}
.todo li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid var(--nh-line);
  color: var(--nh-ink-soft);
  font-size: 14px;
}
.todo li:last-child {
  border-bottom: none;
}
.todo b {
  font-family: var(--nh-display);
  color: var(--nh-ink);
}
@media (max-width: 900px) {
  .dash-grid {
    grid-template-columns: 1fr;
  }
}
</style>
