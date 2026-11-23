<template>
  <div class="page-card">
    <h2 class="page-title">安防告警</h2>
    <el-tabs v-model="tab">
      <el-tab-pane label="告警中心" name="alerts">
        <div class="toolbar">
          <el-button type="primary" @click="scan">风险扫描</el-button>
          <el-input v-model="alertForm.title" placeholder="告警标题" style="width: 180px" />
          <el-select v-model="alertForm.type" style="width: 140px">
            <el-option label="跌倒" value="fall" />
            <el-option label="SOS" value="sos" />
            <el-option label="走失" value="wander_risk" />
            <el-option label="压疮风险" value="pressure" />
            <el-option label="用药风险" value="medication" />
          </el-select>
          <el-button @click="createAlert">手动告警</el-button>
        </div>
        <el-table :data="alerts" stripe size="small">
          <el-table-column prop="title" label="标题" />
          <el-table-column prop="type" label="类型" />
          <el-table-column prop="severity" label="级别" />
          <el-table-column prop="source" label="来源" />
          <el-table-column prop="status" label="状态" />
          <el-table-column label="时间"><template #default="{row}">{{new Date(row.createdAt).toLocaleString()}}</template></el-table-column>
          <el-table-column label="操作">
            <template #default="{row}">
              <el-button size="small" :disabled="row.status!=='open'" @click="handle(row)">处理</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="门禁出入" name="access">
        <div class="toolbar">
          <el-input v-model="accessForm.person" placeholder="人员" style="width: 140px" />
          <el-select v-model="accessForm.direction" style="width: 100px">
            <el-option label="进入" value="in" /><el-option label="离开" value="out" />
          </el-select>
          <el-input v-model="accessForm.gate" placeholder="门禁点" style="width: 120px" />
          <el-button type="primary" @click="createAccess">登记</el-button>
        </div>
        <el-table :data="accessLogs" size="small">
          <el-table-column prop="person" label="人员" />
          <el-table-column prop="direction" label="方向" />
          <el-table-column prop="gate" label="门禁" />
          <el-table-column label="时间"><template #default="{row}">{{new Date(row.recordedAt).toLocaleString()}}</template></el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import http from '../api/http';

const tab = ref('alerts');
const alerts = ref<any[]>([]);
const accessLogs = ref<any[]>([]);
const alertForm = reactive({ title: '', type: 'sos', severity: 'high' });
const accessForm = reactive({ person: '', direction: 'in', gate: '正门' });

async function load() {
  alerts.value = await http.get('/security/alerts');
  accessLogs.value = await http.get('/security/access-logs');
}
async function scan() {
  const res: any = await http.post('/security/risks/scan');
  ElMessage.success(`新增 ${res.created} 条风险告警`);
  load();
}
async function createAlert() {
  await http.post('/security/alerts', alertForm);
  load();
}
async function handle(row: any) {
  await http.post(`/security/alerts/${row.id}/handle`, {});
  load();
}
async function createAccess() {
  await http.post('/security/access-logs', accessForm);
  accessLogs.value = await http.get('/security/access-logs');
}
onMounted(load);
</script>
