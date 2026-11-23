<template>
  <div class="page-card">
    <h2 class="page-title">运营看板</h2>
    <div class="stat-grid">
      <div class="stat-item" v-for="s in stats" :key="s.label">
        <div class="label">{{ s.label }}</div>
        <div class="value">{{ s.value }}</div>
      </div>
    </div>
    <el-row :gutter="16">
      <el-col :xs="24" :md="12">
        <h3>老人自理结构</h3>
        <el-table :data="overview?.careLevelGroups || []" size="small">
          <el-table-column prop="careLevel" label="等级" :formatter="(_, __, v) => levelLabel(v)" />
          <el-table-column prop="_count" label="人数" />
        </el-table>
      </el-col>
      <el-col :xs="24" :md="12">
        <h3>今日待办</h3>
        <ul class="todo">
          <li>待执行照护任务：{{ overview?.pendingTasks ?? '-' }}</li>
          <li>欠费/未结清账单：{{ overview?.unpaidBills ?? '-' }}</li>
          <li>30 日内合同到期：{{ overview?.expiringContracts ?? '-' }}</li>
          <li>本月已收：¥{{ overview?.monthRevenue ?? 0 }}</li>
        </ul>
      </el-col>
    </el-row>
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
.todo {
  line-height: 2;
  color: #405548;
}
</style>
