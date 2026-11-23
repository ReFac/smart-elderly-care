<template>
  <div class="page-card" v-if="elder">
    <div class="toolbar">
      <h2 class="page-title" style="margin: 0">{{ elder.name }}</h2>
      <el-tag>{{ levelLabel(elder.careLevel) }}</el-tag>
      <el-tag type="warning" v-if="elder.wanderRisk">走失风险</el-tag>
      <el-button @click="$router.back()">返回</el-button>
      <el-button type="primary" @click="changeBedDialog = true">调房换床</el-button>
      <el-button type="success" :loading="preLoading" @click="genPrediagnosis">一键 AI 预诊</el-button>
    </div>
    <el-descriptions :column="2" border>
      <el-descriptions-item label="性别">{{ elder.gender }}</el-descriptions-item>
      <el-descriptions-item label="证件号">{{ elder.idNumber }}</el-descriptions-item>
      <el-descriptions-item label="缴费类型">{{ elder.paymentType }}</el-descriptions-item>
      <el-descriptions-item label="床位">{{ elder.bed?.code || '-' }}</el-descriptions-item>
      <el-descriptions-item label="押金">{{ elder.depositAmount }}</el-descriptions-item>
      <el-descriptions-item label="入住日期">{{ formatDate(elder.checkInDate) }}</el-descriptions-item>
      <el-descriptions-item label="过敏">{{ elder.health?.allergies || '-' }}</el-descriptions-item>
      <el-descriptions-item label="慢病">{{ elder.health?.chronicDiseases || '-' }}</el-descriptions-item>
      <el-descriptions-item label="饮食禁忌">{{ elder.health?.dietTaboos || '-' }}</el-descriptions-item>
    </el-descriptions>

    <h3>紧急联系人</h3>
    <el-table :data="elder.contacts" size="small">
      <el-table-column prop="name" label="姓名" />
      <el-table-column prop="relation" label="关系" />
      <el-table-column prop="phone" label="电话" />
    </el-table>

    <h3>合同档案</h3>
    <el-table :data="elder.contracts" size="small">
      <el-table-column prop="title" label="标题" />
      <el-table-column prop="type" label="类型" />
      <el-table-column label="到期">
        <template #default="{ row }">{{ formatDate(row.endDate) }}</template>
      </el-table-column>
    </el-table>

    <h3>换床记录</h3>
    <el-table :data="elder.bedChangeLogs" size="small">
      <el-table-column prop="fromBedId" label="原床" />
      <el-table-column prop="toBedId" label="新床" />
      <el-table-column prop="reason" label="原因" />
      <el-table-column label="时间">
        <template #default="{ row }">{{ formatDate(row.createdAt) }}</template>
      </el-table-column>
    </el-table>

    <div v-if="preResult" class="page-card" style="margin: 16px 0; box-shadow: none; border: 1px solid #e5eee8">
      <h3>AI 预诊草稿</h3>
      <el-alert type="warning" :closable="false" show-icon title="辅助信息，不构成医疗诊断或处方" />
      <p><b>情况</b></p>
      <pre style="white-space: pre-wrap; font-size: 13px">{{ preResult.draft?.situation }}</pre>
      <p><b>医学建议</b></p>
      <pre style="white-space: pre-wrap; font-size: 13px">{{ preResult.draft?.medicalAdvice }}</pre>
      <p><b>风险提示</b></p>
      <pre style="white-space: pre-wrap; font-size: 13px">{{ preResult.draft?.riskHints }}</pre>
    </div>

    <h3>临床摘要（声学/预诊自动维护）</h3>
    <pre style="white-space: pre-wrap; font-size: 13px; background: #f4f7f5; padding: 10px; border-radius: 8px">{{ elder.health?.clinicalNotes || '暂无' }}</pre>
    <p class="muted" v-if="elder.health?.acousticRiskTags">风险标签：{{ elder.health.acousticRiskTags }}</p>

    <h3>情绪行为（失智专项）</h3>
    <div class="toolbar">
      <el-input v-model="emotion.mood" placeholder="情绪" style="width: 140px" />
      <el-input v-model="emotion.behavior" placeholder="行为" style="width: 180px" />
      <el-button @click="addEmotion">登记</el-button>
    </div>
    <el-table :data="elder.emotionRecords" size="small">
      <el-table-column prop="mood" label="情绪" />
      <el-table-column prop="behavior" label="行为" />
      <el-table-column prop="note" label="备注" />
    </el-table>

    <el-dialog v-model="changeBedDialog" title="调房换床" width="420px">
      <el-select v-model="toBedId" filterable style="width: 100%">
        <el-option v-for="b in idleBeds" :key="b.id" :label="b.code" :value="b.id" />
      </el-select>
      <template #footer>
        <el-button type="primary" @click="doChangeBed">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { useRoute } from 'vue-router';
import { ElMessage } from 'element-plus';
import http from '../api/http';
import { CARE_LEVEL_LABELS } from '@nh/shared';

const route = useRoute();
const elder = ref<any>(null);
const changeBedDialog = ref(false);
const idleBeds = ref<any[]>([]);
const toBedId = ref('');
const emotion = reactive({ mood: '', behavior: '', note: '' });
const preLoading = ref(false);
const preResult = ref<any>(null);

function levelLabel(v: string) {
  return (CARE_LEVEL_LABELS as any)[v] || v;
}
function formatDate(v?: string) {
  return v ? new Date(v).toLocaleString() : '-';
}

async function load() {
  elder.value = await http.get(`/elders/${route.params.id}`);
  idleBeds.value = await http.get('/org/beds', { params: { status: 'idle' } });
}

async function genPrediagnosis() {
  preLoading.value = true;
  try {
    preResult.value = await http.post('/clinical/prediagnosis/generate', { elderId: route.params.id });
    ElMessage.success('已生成 AI 预诊草稿');
    await load();
  } finally {
    preLoading.value = false;
  }
}

async function doChangeBed() {
  await http.post(`/elders/${route.params.id}/change-bed`, { toBedId: toBedId.value, reason: '调房' });
  ElMessage.success('已调床');
  changeBedDialog.value = false;
  load();
}

async function addEmotion() {
  await http.post(`/elders/${route.params.id}/emotions`, emotion);
  ElMessage.success('已登记');
  emotion.mood = '';
  emotion.behavior = '';
  load();
}

onMounted(load);
</script>
