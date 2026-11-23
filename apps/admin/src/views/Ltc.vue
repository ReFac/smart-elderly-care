<template>
  <div class="page-card">
    <h2 class="page-title">长护险</h2>
    <el-tabs v-model="tab">
      <el-tab-pane label="评估" name="assess">
        <div class="toolbar">
          <el-select v-model="assess.elderId" filterable style="width: 140px">
            <el-option v-for="e in elders" :key="e.id" :label="e.name" :value="e.id" />
          </el-select>
          <el-select v-model="assess.level" style="width: 120px">
            <el-option label="一级" value="L1" /><el-option label="二级" value="L2" /><el-option label="三级" value="L3" />
          </el-select>
          <el-input v-model="assess.resultSummary" placeholder="评估结论" style="width: 220px" />
          <el-button type="primary" @click="saveAssess">登记评估</el-button>
        </div>
        <el-table :data="assessments" size="small">
          <el-table-column label="老人"><template #default="{row}">{{row.elder?.name}}</template></el-table-column>
          <el-table-column prop="level" label="等级" />
          <el-table-column prop="resultSummary" label="结论" />
          <el-table-column prop="status" label="状态" />
          <el-table-column label="操作">
            <template #default="{row}">
              <el-button size="small" @click="submitAssess(row)">提交</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="服务项目/留痕" name="svc">
        <div class="toolbar">
          <el-select v-model="rec.elderId" filterable style="width: 140px">
            <el-option v-for="e in elders" :key="e.id" :label="e.name" :value="e.id" />
          </el-select>
          <el-select v-model="rec.itemCode" style="width: 180px">
            <el-option v-for="i in items" :key="i.code" :label="`${i.name} ¥${i.unitPrice}`" :value="i.code" />
          </el-select>
          <el-button type="primary" @click="saveRec">服务留痕</el-button>
          <el-button @click="addItem">新增项目</el-button>
        </div>
        <el-table :data="records" size="small">
          <el-table-column label="老人"><template #default="{row}">{{row.elder?.name}}</template></el-table-column>
          <el-table-column prop="itemName" label="项目" />
          <el-table-column prop="amount" label="金额" />
          <el-table-column label="时间"><template #default="{row}">{{new Date(row.serviceAt).toLocaleString()}}</template></el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="对账/导出" name="recon">
        <div class="toolbar">
          <el-select v-model="recon.elderId" filterable style="width: 140px">
            <el-option v-for="e in elders" :key="e.id" :label="e.name" :value="e.id" />
          </el-select>
          <el-input v-model="recon.period" placeholder="账期 YYYY-MM" style="width: 140px" />
          <el-input-number v-model="recon.claimAmount" :min="0" />
          <el-button type="primary" @click="saveRecon">生成对账</el-button>
          <el-button @click="doExport">导出申报包</el-button>
        </div>
        <el-table :data="recons" size="small">
          <el-table-column label="老人"><template #default="{row}">{{row.elder?.name}}</template></el-table-column>
          <el-table-column prop="period" label="账期" />
          <el-table-column prop="claimAmount" label="申报" />
          <el-table-column prop="approvedAmount" label="核定" />
          <el-table-column prop="status" label="状态" />
        </el-table>
        <pre v-if="exportData" class="export-box">{{ exportData }}</pre>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import http from '../api/http';

const tab = ref('assess');
const elders = ref<any[]>([]);
const assessments = ref<any[]>([]);
const items = ref<any[]>([]);
const records = ref<any[]>([]);
const recons = ref<any[]>([]);
const exportData = ref('');
const assess = reactive<any>({ elderId: '', level: 'L2', resultSummary: '' });
const rec = reactive<any>({ elderId: '', itemCode: '' });
const recon = reactive<any>({ elderId: '', period: new Date().toISOString().slice(0, 7), claimAmount: 0 });

async function load() {
  elders.value = await http.get('/elders');
  assessments.value = await http.get('/ltc/assessments');
  items.value = await http.get('/ltc/items');
  records.value = await http.get('/ltc/records');
  recons.value = await http.get('/ltc/reconciliations');
  if (elders.value[0]) assess.elderId = rec.elderId = recon.elderId = elders.value[0].id;
  if (items.value[0]) rec.itemCode = items.value[0].code;
}
async function saveAssess() {
  await http.post('/ltc/assessments', { ...assess, assessDate: new Date().toISOString() });
  assessments.value = await http.get('/ltc/assessments');
}
async function submitAssess(row: any) {
  await http.patch(`/ltc/assessments/${row.id}`, { status: 'submitted' });
  assessments.value = await http.get('/ltc/assessments');
}
async function addItem() {
  const { value: code } = await ElMessageBox.prompt('项目编码', '新增长护险项目');
  const { value: name } = await ElMessageBox.prompt('项目名称', '新增长护险项目');
  await http.post('/ltc/items', { code, name, unitPrice: 50 });
  items.value = await http.get('/ltc/items');
}
async function saveRec() {
  await http.post('/ltc/records', rec);
  records.value = await http.get('/ltc/records');
  ElMessage.success('已留痕');
}
async function saveRecon() {
  await http.post('/ltc/reconciliations', recon);
  recons.value = await http.get('/ltc/reconciliations');
}
async function doExport() {
  const data = await http.get('/ltc/export', { params: { elderId: recon.elderId, period: recon.period } });
  exportData.value = JSON.stringify(data, null, 2);
  ElMessage.success('已生成导出 JSON');
}
onMounted(load);
</script>

<style scoped>
.export-box {
  margin-top: 12px;
  max-height: 280px;
  overflow: auto;
  background: #f6f8f7;
  padding: 12px;
  border-radius: 8px;
  font-size: 12px;
}
</style>
