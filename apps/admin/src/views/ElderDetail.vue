<template>
  <div class="page-card" v-if="elder">
    <div class="toolbar">
      <h2 class="page-title" style="margin: 0">{{ elder.name }}</h2>
      <el-tag>{{ levelLabel(elder.careLevel) }}</el-tag>
      <el-tag type="warning" v-if="elder.wanderRisk">走失风险</el-tag>
      <el-button @click="$router.back()">返回</el-button>
      <el-button type="primary" @click="changeBedDialog = true">调房换床</el-button>
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
