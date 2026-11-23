<template>
  <div class="page-card">
    <h2 class="page-title">食堂餐食</h2>
    <div class="toolbar">
      <el-date-picker v-model="form.date" type="date" />
      <el-select v-model="form.mealType" style="width: 120px">
        <el-option label="早餐" value="breakfast" />
        <el-option label="午餐" value="lunch" />
        <el-option label="晚餐" value="dinner" />
      </el-select>
      <el-input v-model="form.dishes" placeholder="菜品，逗号分隔" style="width: 280px" />
      <el-button type="primary" @click="save">保存食谱</el-button>
    </div>
    <el-table :data="menus" stripe>
      <el-table-column label="日期">
        <template #default="{ row }">{{ new Date(row.date).toLocaleDateString() }}</template>
      </el-table-column>
      <el-table-column prop="mealType" label="餐次" :formatter="(_, __, v) => mealLabel(v)" />
      <el-table-column prop="dishes" label="菜品" />
      <el-table-column prop="dietTags" label="标签" />
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import http from '../api/http';

const menus = ref<any[]>([]);
const form = reactive({
  date: new Date(),
  mealType: 'lunch',
  dishes: '',
  dietTags: '普食',
});

function mealLabel(v: string) {
  return ({ breakfast: '早餐', lunch: '午餐', dinner: '晚餐' } as any)[v] || v;
}

async function load() {
  menus.value = await http.get('/meals');
}

async function save() {
  await http.post('/meals', {
    ...form,
    date: form.date.toISOString(),
  });
  ElMessage.success('已保存');
  load();
}

onMounted(load);
</script>
