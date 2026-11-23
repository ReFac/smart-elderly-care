<template>
  <div class="page-card">
    <h2 class="page-title">报表报送</h2>
    <div class="toolbar">
      <el-button type="primary" @click="generate">生成民政月度报送表</el-button>
      <el-button @click="load">刷新</el-button>
    </div>
    <el-table :data="list" stripe>
      <el-table-column prop="reportType" label="类型" />
      <el-table-column prop="period" label="周期" />
      <el-table-column prop="status" label="状态" />
      <el-table-column label="创建时间">
        <template #default="{ row }">{{ new Date(row.createdAt).toLocaleString() }}</template>
      </el-table-column>
      <el-table-column label="操作" width="260">
        <template #default="{ row }">
          <el-button size="small" @click="preview(row)">预览导出</el-button>
          <el-button size="small" type="success" :disabled="row.status==='submitted'" @click="submit(row)">标记已报送</el-button>
          <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <pre v-if="previewData" class="export-box">{{ previewData }}</pre>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import http from '../api/http';

const list = ref<any[]>([]);
const previewData = ref('');

async function load() {
  list.value = await http.get('/reports');
}
async function generate() {
  await http.post('/reports/generate/monthly', {});
  ElMessage.success('已生成草稿');
  load();
}
async function preview(row: any) {
  const data = await http.get(`/reports/${row.id}/export`);
  previewData.value = JSON.stringify(data, null, 2);
}
async function submit(row: any) {
  await http.patch(`/reports/${row.id}`, { status: 'submitted' });
  load();
}
async function remove(row: any) {
  await http.delete(`/reports/${row.id}`);
  load();
}
onMounted(load);
</script>

<style scoped>
.export-box {
  margin-top: 12px;
  max-height: 360px;
  overflow: auto;
  background: #f6f8f7;
  padding: 12px;
  border-radius: 8px;
  font-size: 12px;
}
</style>
