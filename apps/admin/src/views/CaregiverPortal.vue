<template>
  <div class="page-card">
    <h2 class="page-title">护理端视角（主管理员）</h2>
    <p class="hint">预览护理员今日工单与异常；对应移动端入口 :5174 护理账号。</p>
    <div class="toolbar">
      <el-button type="primary" @click="gen">生成今日任务</el-button>
      <el-button @click="load">刷新</el-button>
    </div>
    <el-table :data="tasks" stripe>
      <el-table-column label="老人"><template #default="{ row }">{{ row.elder?.name }}</template></el-table-column>
      <el-table-column prop="title" label="项目" />
      <el-table-column prop="status" label="状态" />
      <el-table-column label="异常">
        <template #default="{ row }">
          {{ row.checkins?.[0]?.anomaly || '-' }}
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import http from '../api/http';

const tasks = ref<any[]>([]);
async function load() {
  tasks.value = await http.get('/care/tasks');
}
async function gen() {
  const res: any = await http.post('/care/tasks/generate-today');
  ElMessage.success(`生成 ${res.count} 条`);
  load();
}
onMounted(load);
</script>

<style scoped>
.hint { color: #6a7b71; margin-top: -8px; }
</style>
