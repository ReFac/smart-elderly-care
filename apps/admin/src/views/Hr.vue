<template>
  <div class="page-card">
    <h2 class="page-title">人事排班</h2>
    <el-tabs v-model="tab">
      <el-tab-pane label="员工档案" name="emp">
        <div class="toolbar">
          <el-input v-model="empForm.username" placeholder="账号" style="width: 120px" />
          <el-input v-model="empForm.name" placeholder="姓名" style="width: 120px" />
          <el-select v-model="empForm.role" style="width: 120px">
            <el-option label="护理员" value="caregiver" />
            <el-option label="护士" value="nurse" />
            <el-option label="医生" value="doctor" />
            <el-option label="后勤" value="logistics" />
            <el-option label="行政" value="admin" />
            <el-option label="财务" value="finance" />
          </el-select>
          <el-button type="primary" @click="createEmp">新增员工</el-button>
        </div>
        <el-table :data="employees" size="small">
          <el-table-column prop="name" label="姓名" />
          <el-table-column prop="username" label="账号" />
          <el-table-column prop="role" label="岗位" />
          <el-table-column prop="phone" label="电话" />
          <el-table-column label="状态"><template #default="{row}">{{row.active?'在职':'停用'}}</template></el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="排班" name="shift">
        <div class="toolbar">
          <el-select v-model="shiftForm.employeeId" filterable style="width: 140px">
            <el-option v-for="e in employees" :key="e.id" :label="e.name" :value="e.id" />
          </el-select>
          <el-date-picker v-model="shiftForm.shiftDate" type="date" />
          <el-select v-model="shiftForm.shiftType" style="width: 120px">
            <el-option label="早班" value="morning" />
            <el-option label="中班" value="day" />
            <el-option label="晚班" value="night" />
          </el-select>
          <el-button type="primary" @click="createShift">排班</el-button>
        </div>
        <el-table :data="shifts" size="small">
          <el-table-column label="员工"><template #default="{row}">{{row.employee?.name}}</template></el-table-column>
          <el-table-column label="日期"><template #default="{row}">{{new Date(row.shiftDate).toLocaleDateString()}}</template></el-table-column>
          <el-table-column prop="shiftType" label="班次" />
          <el-table-column label="操作">
            <template #default="{row}"><el-button size="small" type="danger" @click="delShift(row)">删除</el-button></template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="考勤" name="att">
        <div class="toolbar">
          <el-button type="primary" @click="checkIn">我要打卡</el-button>
          <el-button @click="loadAtt">刷新</el-button>
        </div>
        <el-table :data="attendance" size="small">
          <el-table-column label="员工"><template #default="{row}">{{row.employee?.name}}</template></el-table-column>
          <el-table-column label="上班"><template #default="{row}">{{fmt(row.checkInAt)}}</template></el-table-column>
          <el-table-column label="下班"><template #default="{row}">{{fmt(row.checkOutAt)}}</template></el-table-column>
          <el-table-column label="操作">
            <template #default="{row}">
              <el-button size="small" :disabled="!!row.checkOutAt" @click="checkOut(row)">下班</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="绩效" name="perf">
        <div class="toolbar">
          <el-button type="primary" @click="compute">按工单统计本月绩效</el-button>
        </div>
        <el-table :data="performance" size="small">
          <el-table-column label="员工"><template #default="{row}">{{row.employee?.name}}</template></el-table-column>
          <el-table-column prop="period" label="周期" />
          <el-table-column prop="taskCount" label="工作量" />
          <el-table-column prop="score" label="得分" />
          <el-table-column prop="bonusAmount" label="绩效金额" />
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import http from '../api/http';

const tab = ref('emp');
const employees = ref<any[]>([]);
const shifts = ref<any[]>([]);
const attendance = ref<any[]>([]);
const performance = ref<any[]>([]);
const empForm = reactive({ username: '', name: '', role: 'caregiver' });
const shiftForm = reactive<any>({ employeeId: '', shiftDate: new Date(), shiftType: 'day' });
const fmt = (v?: string) => (v ? new Date(v).toLocaleString() : '-');

async function load() {
  employees.value = await http.get('/hr/employees');
  shifts.value = await http.get('/hr/shifts');
  attendance.value = await http.get('/hr/attendance');
  performance.value = await http.get('/hr/performance');
  if (employees.value[0]) shiftForm.employeeId = employees.value[0].id;
}
async function createEmp() {
  await http.post('/hr/employees', empForm);
  ElMessage.success('已创建，默认密码 123456');
  load();
}
async function createShift() {
  await http.post('/hr/shifts', { ...shiftForm, shiftDate: shiftForm.shiftDate.toISOString() });
  shifts.value = await http.get('/hr/shifts');
}
async function delShift(row: any) {
  await http.delete(`/hr/shifts/${row.id}`);
  shifts.value = await http.get('/hr/shifts');
}
async function checkIn() {
  await http.post('/hr/attendance/check-in', {});
  loadAtt();
}
async function loadAtt() {
  attendance.value = await http.get('/hr/attendance');
}
async function checkOut(row: any) {
  await http.post(`/hr/attendance/${row.id}/check-out`);
  loadAtt();
}
async function compute() {
  const res: any = await http.post('/hr/performance/compute', {});
  ElMessage.success(`生成 ${res.count} 条绩效`);
  performance.value = await http.get('/hr/performance');
}
onMounted(load);
</script>
