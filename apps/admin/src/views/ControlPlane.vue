<template>
  <div class="page-card">
    <h2 class="page-title">变量 / API / 服务总控</h2>
    <p class="hint">主管理员可改运行变量、启停 API 元数据、探测服务健康。模块化配置，符合敏捷热更新。</p>
    <div class="toolbar">
      <el-button @click="load">刷新快照</el-button>
      <el-tag v-if="snap">变量 {{ snap.counts?.variables }} · 服务 {{ snap.counts?.services }} · API {{ snap.counts?.apisEnabled }}/{{ snap.counts?.apis }}</el-tag>
    </div>

    <el-tabs v-model="tab">
      <el-tab-pane label="运行变量" name="vars">
        <div class="toolbar">
          <el-input v-model="varForm.key" placeholder="key" style="width:180px" />
          <el-input v-model="varForm.value" placeholder="value" style="width:200px" />
          <el-select v-model="varForm.groupName" style="width:120px">
            <el-option label="brand" value="brand" /><el-option label="agent" value="agent" />
            <el-option label="family" value="family" /><el-option label="mobile" value="mobile" />
            <el-option label="tour" value="tour" /><el-option label="learning" value="learning" />
            <el-option label="general" value="general" />
          </el-select>
          <el-button type="primary" @click="saveVar">保存变量</el-button>
        </div>
        <el-table :data="snap?.variables || []" size="small">
          <el-table-column prop="groupName" label="组" width="100" />
          <el-table-column prop="key" label="Key" />
          <el-table-column prop="value" label="Value" />
          <el-table-column prop="description" label="说明" />
          <el-table-column label="操作" width="160">
            <template #default="{ row }">
              <el-button size="small" @click="editVar(row)">编辑</el-button>
              <el-button size="small" type="danger" @click="delVar(row)">删</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="服务注册" name="svc">
        <el-table :data="snap?.services || []" size="small">
          <el-table-column prop="code" label="Code" width="100" />
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="baseUrl" label="Base URL" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column label="启用" width="80">
            <template #default="{ row }">
              <el-switch :model-value="row.enabled" @change="(v:boolean)=>toggleSvc(row,v)" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button size="small" @click="probe(row)">探测</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="API 元数据" name="apis">
        <div class="toolbar">
          <el-select v-model="audience" clearable placeholder="受众" style="width:140px" @change="load">
            <el-option label="admin" value="admin" />
            <el-option label="user" value="user" />
            <el-option label="employee" value="employee" />
          </el-select>
          <el-input v-model="apiForm.path" placeholder="/path" style="width:180px" />
          <el-select v-model="apiForm.method" style="width:100px">
            <el-option label="GET" value="GET" /><el-option label="POST" value="POST" />
            <el-option label="PUT" value="PUT" /><el-option label="PATCH" value="PATCH" />
          </el-select>
          <el-select v-model="apiForm.audience" style="width:120px">
            <el-option label="admin" value="admin" /><el-option label="user" value="user" /><el-option label="employee" value="employee" />
          </el-select>
          <el-button type="primary" @click="saveApi">登记/更新 API</el-button>
        </div>
        <el-table :data="filteredApis" size="small" max-height="480">
          <el-table-column prop="method" label="方法" width="80" />
          <el-table-column prop="path" label="路径" />
          <el-table-column prop="module" label="模块" width="120" />
          <el-table-column prop="audience" label="受众" width="100" />
          <el-table-column prop="description" label="说明" />
          <el-table-column label="启用" width="80">
            <template #default="{ row }">
              <el-switch :model-value="row.enabled" @change="(v:boolean)=>toggleApi(row,v)" />
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import http from '../api/http';

const tab = ref('vars');
const snap = ref<any>(null);
const audience = ref('');
const varForm = reactive({ key: '', value: '', groupName: 'general', description: '' });
const apiForm = reactive({ method: 'GET', path: '', audience: 'admin', module: 'custom', description: '' });

const filteredApis = computed(() => {
  const list = snap.value?.apis || [];
  return audience.value ? list.filter((a: any) => a.audience === audience.value) : list;
});

async function load() {
  snap.value = await http.get('/control/snapshot');
}
function editVar(row: any) {
  Object.assign(varForm, { key: row.key, value: row.value, groupName: row.groupName, description: row.description || '' });
}
async function saveVar() {
  await http.put('/control/variables', varForm);
  ElMessage.success('变量已保存');
  load();
}
async function delVar(row: any) {
  await http.delete(`/control/variables/${encodeURIComponent(row.key)}`);
  load();
}
async function toggleSvc(row: any, enabled: boolean) {
  await http.put('/control/services', { ...row, enabled });
  load();
}
async function probe(row: any) {
  await http.post(`/control/services/${row.code}/probe`);
  ElMessage.success('已探测');
  load();
}
async function saveApi() {
  await http.put('/control/apis', apiForm);
  ElMessage.success('API 元数据已更新');
  load();
}
async function toggleApi(row: any, enabled: boolean) {
  await http.put('/control/apis', { ...row, enabled });
  load();
}
onMounted(load);
</script>

<style scoped>
.hint { color: #6a7b71; margin-top: -8px; }
</style>
