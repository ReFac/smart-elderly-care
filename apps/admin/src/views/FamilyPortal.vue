<template>
  <div class="page-card">
    <h2 class="page-title">家属端视角（主管理员）</h2>
    <p class="hint">在此预览家属可见的账单透明与今日餐食；实际家属端 H5 仍可独立访问 :5174。</p>
    <el-row :gutter="16">
      <el-col :xs="24" :md="12">
        <h3>绑定老人账单</h3>
        <el-select v-model="elderId" filterable style="width: 100%; margin-bottom: 12px" @change="loadBills">
          <el-option v-for="e in elders" :key="e.id" :label="e.name" :value="e.id" />
        </el-select>
        <el-table :data="bills" size="small">
          <el-table-column prop="totalAmount" label="应付" />
          <el-table-column prop="paidAmount" label="已付" />
          <el-table-column prop="status" label="状态" />
          <el-table-column label="明细">
            <template #default="{ row }">
              {{ row.lines?.map((l: any) => l.feeName).join(' / ') }}
            </template>
          </el-table-column>
        </el-table>
      </el-col>
      <el-col :xs="24" :md="12">
        <h3>今日餐食（家属可见）</h3>
        <el-table :data="meals" size="small">
          <el-table-column prop="mealType" label="餐次" :formatter="(_, __, v) => ({ breakfast: '早餐', lunch: '午餐', dinner: '晚餐' } as any)[v] || v" />
          <el-table-column prop="dishes" label="菜品" />
          <el-table-column prop="dietTags" label="标签" />
        </el-table>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import http from '../api/http';

const elders = ref<any[]>([]);
const elderId = ref('');
const bills = ref<any[]>([]);
const meals = ref<any[]>([]);

async function loadBills() {
  const all: any[] = await http.get('/billing/bills', { params: { elderId: elderId.value } });
  bills.value = all;
}
onMounted(async () => {
  elders.value = await http.get('/elders');
  elderId.value = elders.value[0]?.id || '';
  meals.value = await http.get('/meals/today');
  if (elderId.value) await loadBills();
});
</script>

<style scoped>
.hint { color: #6a7b71; margin-top: -8px; }
</style>
