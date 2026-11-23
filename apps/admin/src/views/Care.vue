<template>
  <div class="page-card">
    <h2 class="page-title">照护服务</h2>
    <el-tabs v-model="tab">
      <el-tab-pane label="今日工单" name="tasks">
        <div class="toolbar">
          <el-button type="primary" @click="genTasks">生成今日任务</el-button>
          <el-button @click="loadTasks">刷新</el-button>
        </div>
        <el-table :data="tasks" stripe>
          <el-table-column label="老人">
            <template #default="{ row }">{{ row.elder?.name }}</template>
          </el-table-column>
          <el-table-column prop="title" label="项目" />
          <el-table-column label="计划时间">
            <template #default="{ row }">{{ new Date(row.scheduledAt).toLocaleTimeString() }}</template>
          </el-table-column>
          <el-table-column prop="status" label="状态" />
          <el-table-column label="操作" width="220">
            <template #default="{ row }">
              <el-button size="small" :disabled="row.status === 'done'" @click="checkin(row, '')">打卡</el-button>
              <el-button size="small" type="warning" @click="checkin(row, '拒食')">异常</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="临时服务" name="orders">
        <div class="toolbar">
          <el-select v-model="orderForm.elderId" placeholder="老人" filterable style="width: 160px">
            <el-option v-for="e in elders" :key="e.id" :label="e.name" :value="e.id" />
          </el-select>
          <el-input v-model="orderForm.title" placeholder="服务内容" style="width: 200px" />
          <el-button type="primary" @click="createOrder">发起工单</el-button>
        </div>
        <el-table :data="orders">
          <el-table-column label="老人"><template #default="{ row }">{{ row.elder?.name }}</template></el-table-column>
          <el-table-column prop="title" label="内容" />
          <el-table-column prop="status" label="状态" />
          <el-table-column label="操作">
            <template #default="{ row }">
              <el-button size="small" @click="doneOrder(row)" :disabled="row.status === 'done'">完成</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="探视登记" name="visits">
        <div class="toolbar">
          <el-select v-model="visitForm.elderId" placeholder="老人" filterable style="width: 160px">
            <el-option v-for="e in elders" :key="e.id" :label="e.name" :value="e.id" />
          </el-select>
          <el-input v-model="visitForm.visitorName" placeholder="访客姓名" style="width: 140px" />
          <el-input v-model="visitForm.relation" placeholder="关系" style="width: 100px" />
          <el-button type="primary" @click="createVisit">登记</el-button>
        </div>
        <el-table :data="visits">
          <el-table-column label="老人"><template #default="{ row }">{{ row.elder?.name }}</template></el-table-column>
          <el-table-column prop="visitorName" label="访客" />
          <el-table-column prop="relation" label="关系" />
          <el-table-column label="时间">
            <template #default="{ row }">{{ new Date(row.visitAt).toLocaleString() }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="照护计划" name="plans">
        <el-table :data="plans">
          <el-table-column label="老人"><template #default="{ row }">{{ row.elder?.name }}</template></el-table-column>
          <el-table-column prop="careLevel" label="等级" />
          <el-table-column label="项目">
            <template #default="{ row }">{{ JSON.parse(row.itemsJson || '[]').join('、') }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import http from '../api/http';

const tab = ref('tasks');
const tasks = ref<any[]>([]);
const orders = ref<any[]>([]);
const visits = ref<any[]>([]);
const plans = ref<any[]>([]);
const elders = ref<any[]>([]);
const orderForm = reactive({ elderId: '', title: '' });
const visitForm = reactive({ elderId: '', visitorName: '', relation: '' });

async function loadTasks() {
  tasks.value = await http.get('/care/tasks');
}
async function genTasks() {
  const res: any = await http.post('/care/tasks/generate-today');
  ElMessage.success(`生成 ${res.count} 条任务`);
  loadTasks();
}
async function checkin(row: any, anomaly: string) {
  await http.post(`/care/tasks/${row.id}/checkin`, { anomaly: anomaly || undefined, note: anomaly ? '异常上报' : '完成' });
  ElMessage.success(anomaly ? '已上报异常' : '打卡成功');
  loadTasks();
}
async function loadOrders() {
  orders.value = await http.get('/care/orders');
}
async function createOrder() {
  await http.post('/care/orders', orderForm);
  ElMessage.success('工单已创建');
  orderForm.title = '';
  loadOrders();
}
async function doneOrder(row: any) {
  await http.patch(`/care/orders/${row.id}`, { status: 'done' });
  loadOrders();
}
async function loadVisits() {
  visits.value = await http.get('/care/visits');
}
async function createVisit() {
  await http.post('/care/visits', visitForm);
  ElMessage.success('探视已登记');
  loadVisits();
}
async function loadPlans() {
  plans.value = await http.get('/care/plans');
}

onMounted(async () => {
  elders.value = await http.get('/elders');
  await Promise.all([loadTasks(), loadOrders(), loadVisits(), loadPlans()]);
});
</script>
