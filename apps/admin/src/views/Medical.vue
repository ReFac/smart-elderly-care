<template>
  <div class="page-card">
    <h2 class="page-title">医护健康</h2>
    <el-tabs v-model="tab">
      <el-tab-pane label="生命体征" name="vitals">
        <div class="toolbar">
          <el-select v-model="vitalForm.elderId" placeholder="老人" filterable style="width: 140px">
            <el-option v-for="e in elders" :key="e.id" :label="e.name" :value="e.id" />
          </el-select>
          <el-input-number v-model="vitalForm.systolic" placeholder="收缩压" :controls="false" style="width: 100px" />
          <el-input-number v-model="vitalForm.diastolic" placeholder="舒张压" :controls="false" style="width: 100px" />
          <el-input-number v-model="vitalForm.glucose" placeholder="血糖" :controls="false" style="width: 90px" />
          <el-input-number v-model="vitalForm.temperature" placeholder="体温" :controls="false" style="width: 90px" />
          <el-input-number v-model="vitalForm.spo2" placeholder="血氧" :controls="false" style="width: 90px" />
          <el-button type="primary" @click="saveVital">录入</el-button>
        </div>
        <el-table :data="vitals" size="small" stripe>
          <el-table-column label="老人"><template #default="{ row }">{{ row.elder?.name }}</template></el-table-column>
          <el-table-column label="血压"><template #default="{ row }">{{ row.systolic }}/{{ row.diastolic }}</template></el-table-column>
          <el-table-column prop="glucose" label="血糖" />
          <el-table-column prop="temperature" label="体温" />
          <el-table-column prop="spo2" label="血氧" />
          <el-table-column label="时间"><template #default="{ row }">{{ fmt(row.recordedAt) }}</template></el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="药品台账" name="drugs">
        <div class="toolbar">
          <el-input v-model="drugForm.name" placeholder="药品名" style="width: 140px" />
          <el-input v-model="drugForm.spec" placeholder="规格" style="width: 120px" />
          <el-input-number v-model="drugForm.quantity" :min="0" />
          <el-checkbox v-model="drugForm.isHighRisk">高危</el-checkbox>
          <el-button type="primary" @click="saveDrug">新增</el-button>
        </div>
        <el-table :data="drugs" size="small">
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="spec" label="规格" />
          <el-table-column prop="quantity" label="库存" />
          <el-table-column label="高危"><template #default="{ row }">{{ row.isHighRisk ? '是' : '否' }}</template></el-table-column>
          <el-table-column label="操作" width="200">
            <template #default="{ row }">
              <el-button size="small" @click="stockDrug(row, 'in')">入库</el-button>
              <el-button size="small" @click="stockDrug(row, 'out')">出库</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="发药计划" name="doses">
        <div class="toolbar">
          <el-select v-model="planForm.elderId" placeholder="老人" filterable style="width: 140px">
            <el-option v-for="e in elders" :key="e.id" :label="e.name" :value="e.id" />
          </el-select>
          <el-select v-model="planForm.drugId" placeholder="药品" filterable style="width: 160px">
            <el-option v-for="d in drugs" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
          <el-input v-model="planForm.dosage" placeholder="剂量" style="width: 100px" />
          <el-button type="primary" @click="savePlan">建计划</el-button>
          <el-button @click="loadDoses">刷新待发</el-button>
        </div>
        <el-table :data="doses" size="small">
          <el-table-column label="老人"><template #default="{ row }">{{ row.plan?.elder?.name }}</template></el-table-column>
          <el-table-column label="药品"><template #default="{ row }">{{ row.plan?.drug?.name }}</template></el-table-column>
          <el-table-column prop="status" label="状态" />
          <el-table-column label="操作">
            <template #default="{ row }">
              <el-button size="small" type="primary" :disabled="row.status!=='pending'" @click="give(row,'given')">给药</el-button>
              <el-button size="small" type="warning" :disabled="row.status!=='pending'" @click="give(row,'missed')">漏药</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="体检/随访" name="exam">
        <div class="toolbar">
          <el-select v-model="examForm.elderId" filterable placeholder="老人" style="width: 140px">
            <el-option v-for="e in elders" :key="e.id" :label="e.name" :value="e.id" />
          </el-select>
          <el-input v-model="examForm.summary" placeholder="体检摘要" style="width: 220px" />
          <el-button type="primary" @click="saveExam">登记体检</el-button>
          <el-input v-model="followForm.disease" placeholder="慢病" style="width: 120px" />
          <el-input v-model="followForm.result" placeholder="随访结果" style="width: 160px" />
          <el-button @click="saveFollow">慢病随访</el-button>
        </div>
        <el-row :gutter="12">
          <el-col :span="12"><el-table :data="exams" size="small"><el-table-column label="老人"><template #default="{row}">{{row.elder?.name}}</template></el-table-column><el-table-column prop="summary" label="摘要" /></el-table></el-col>
          <el-col :span="12"><el-table :data="follows" size="small"><el-table-column label="老人"><template #default="{row}">{{row.elder?.name}}</template></el-table-column><el-table-column prop="disease" label="疾病" /><el-table-column prop="result" label="结果" /></el-table></el-col>
        </el-row>
      </el-tab-pane>

      <el-tab-pane label="医嘱/转诊" name="orders">
        <div class="toolbar">
          <el-select v-model="orderForm.elderId" filterable style="width: 140px" placeholder="老人">
            <el-option v-for="e in elders" :key="e.id" :label="e.name" :value="e.id" />
          </el-select>
          <el-input v-model="orderForm.content" placeholder="医嘱内容" style="width: 240px" />
          <el-button type="primary" @click="saveOrder">录入医嘱</el-button>
          <el-input v-model="refForm.hospital" placeholder="医院" style="width: 140px" />
          <el-input v-model="refForm.reason" placeholder="转诊原因" style="width: 160px" />
          <el-button @click="saveReferral">外出就医</el-button>
        </div>
        <el-table :data="orders" size="small" style="margin-bottom:12px">
          <el-table-column label="老人"><template #default="{row}">{{row.elder?.name}}</template></el-table-column>
          <el-table-column prop="content" label="医嘱" />
          <el-table-column prop="status" label="状态" />
        </el-table>
        <el-table :data="referrals" size="small">
          <el-table-column label="老人"><template #default="{row}">{{row.elder?.name}}</template></el-table-column>
          <el-table-column prop="hospital" label="医院" />
          <el-table-column prop="reason" label="原因" />
          <el-table-column label="120"><template #default="{row}">{{row.ambulance120?'是':'否'}}</template></el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import http from '../api/http';

const tab = ref('vitals');
const elders = ref<any[]>([]);
const vitals = ref<any[]>([]);
const drugs = ref<any[]>([]);
const doses = ref<any[]>([]);
const exams = ref<any[]>([]);
const follows = ref<any[]>([]);
const orders = ref<any[]>([]);
const referrals = ref<any[]>([]);

const vitalForm = reactive<any>({ elderId: '', systolic: 120, diastolic: 80, glucose: 5.5, temperature: 36.5, spo2: 98 });
const drugForm = reactive<any>({ name: '', spec: '', quantity: 10, isHighRisk: false });
const planForm = reactive<any>({ elderId: '', drugId: '', dosage: '1片' });
const examForm = reactive<any>({ elderId: '', summary: '' });
const followForm = reactive<any>({ elderId: '', disease: '', result: '' });
const orderForm = reactive<any>({ elderId: '', content: '' });
const refForm = reactive<any>({ elderId: '', hospital: '', reason: '' });

const fmt = (v: string) => (v ? new Date(v).toLocaleString() : '-');

async function load() {
  elders.value = await http.get('/elders');
  vitals.value = await http.get('/medical/vitals');
  drugs.value = await http.get('/medical/drugs');
  doses.value = await http.get('/medical/doses');
  exams.value = await http.get('/medical/exams');
  follows.value = await http.get('/medical/follow-ups');
  orders.value = await http.get('/medical/orders');
  referrals.value = await http.get('/medical/referrals');
  if (elders.value[0]) {
    vitalForm.elderId = examForm.elderId = followForm.elderId = orderForm.elderId = refForm.elderId = planForm.elderId = elders.value[0].id;
  }
}
async function saveVital() {
  await http.post('/medical/vitals', vitalForm);
  ElMessage.success('已录入');
  vitals.value = await http.get('/medical/vitals');
}
async function saveDrug() {
  await http.post('/medical/drugs', drugForm);
  ElMessage.success('已新增药品');
  drugs.value = await http.get('/medical/drugs');
}
async function stockDrug(row: any, type: string) {
  const { value } = await ElMessageBox.prompt('数量', type === 'in' ? '入库' : '出库', { inputValue: '1' });
  await http.post(`/medical/drugs/${row.id}/stock`, { type, quantity: Number(value) });
  drugs.value = await http.get('/medical/drugs');
}
async function savePlan() {
  await http.post('/medical/plans', planForm);
  ElMessage.success('计划已创建');
  loadDoses();
}
async function loadDoses() {
  doses.value = await http.get('/medical/doses');
}
async function give(row: any, status: string) {
  await http.post(`/medical/doses/${row.id}/give`, { status, missedReason: status === 'missed' ? '拒服' : undefined });
  loadDoses();
}
async function saveExam() {
  await http.post('/medical/exams', { ...examForm, examDate: new Date().toISOString() });
  exams.value = await http.get('/medical/exams');
}
async function saveFollow() {
  followForm.elderId = followForm.elderId || examForm.elderId;
  await http.post('/medical/follow-ups', { ...followForm, followDate: new Date().toISOString() });
  follows.value = await http.get('/medical/follow-ups');
}
async function saveOrder() {
  await http.post('/medical/orders', orderForm);
  orders.value = await http.get('/medical/orders');
}
async function saveReferral() {
  refForm.elderId = refForm.elderId || orderForm.elderId;
  await http.post('/medical/referrals', refForm);
  referrals.value = await http.get('/medical/referrals');
}

onMounted(load);
</script>
