<template>
  <div class="page-card">
    <h2 class="page-title">老人档案</h2>
    <div class="toolbar">
      <el-input v-model="q" placeholder="搜索姓名/证件/电话" style="width: 240px" clearable @clear="load" />
      <el-button @click="load">搜索</el-button>
      <el-button type="primary" @click="openCreate">新建入住</el-button>
      <el-button @click="ocrAssist">OCR 辅助建档</el-button>
    </div>
    <el-table :data="list" stripe @row-click="(row) => $router.push(`/elders/${row.id}`)">
      <el-table-column prop="name" label="姓名" width="100" />
      <el-table-column prop="gender" label="性别" width="70" />
      <el-table-column prop="careLevel" label="自理等级" :formatter="(_, __, v) => levelLabel(v)" />
      <el-table-column prop="paymentType" label="缴费类型" />
      <el-table-column label="床位">
        <template #default="{ row }">{{ row.bed?.code || '-' }}</template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="90" />
    </el-table>

    <el-dialog v-model="dialog" title="新建老人档案" width="640px">
      <el-form label-width="100px">
        <el-form-item label="姓名"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="性别">
          <el-select v-model="form.gender"><el-option label="男" value="男" /><el-option label="女" value="女" /></el-select>
        </el-form-item>
        <el-form-item label="证件号"><el-input v-model="form.idNumber" /></el-form-item>
        <el-form-item label="自理等级">
          <el-select v-model="form.careLevel">
            <el-option v-for="(label, key) in CARE_LEVEL_LABELS" :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="缴费类型">
          <el-select v-model="form.paymentType">
            <el-option label="自费" value="self" />
            <el-option label="医保" value="medical" />
            <el-option label="长护险" value="long_term_care" />
          </el-select>
        </el-form-item>
        <el-form-item label="床位">
          <el-select v-model="form.bedId" filterable clearable style="width: 100%">
            <el-option v-for="b in idleBeds" :key="b.id" :label="b.code" :value="b.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="押金"><el-input-number v-model="form.depositAmount" :min="0" /></el-form-item>
        <el-form-item label="过敏史"><el-input v-model="form.health.allergies" /></el-form-item>
        <el-form-item label="慢病"><el-input v-model="form.health.chronicDiseases" /></el-form-item>
        <el-form-item label="紧急联系人"><el-input v-model="contact.name" placeholder="姓名" /></el-form-item>
        <el-form-item label="联系电话"><el-input v-model="contact.phone" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="create">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import http from '../api/http';
import { CARE_LEVEL_LABELS } from '@nh/shared';

const router = useRouter();
const list = ref<any[]>([]);
const idleBeds = ref<any[]>([]);
const q = ref('');
const dialog = ref(false);
const form = reactive<any>({
  name: '',
  gender: '男',
  idNumber: '',
  careLevel: 'independent',
  paymentType: 'self',
  bedId: '',
  depositAmount: 5000,
  health: { allergies: '', chronicDiseases: '' },
});
const contact = reactive({ name: '', phone: '', relation: '子女', isEmergency: true, isPrimary: true });

function levelLabel(v: string) {
  return (CARE_LEVEL_LABELS as any)[v] || v;
}

async function load() {
  list.value = await http.get('/elders', { params: { q: q.value || undefined } });
}

async function openCreate() {
  idleBeds.value = await http.get('/org/beds', { params: { status: 'idle' } });
  dialog.value = true;
}

async function create() {
  await http.post('/elders', {
    ...form,
    health: form.health,
    contacts: contact.name ? [contact] : [],
  });
  ElMessage.success('建档成功');
  dialog.value = false;
  load();
}

async function ocrAssist() {
  const ocr: any = await http.post('/ai/ocr');
  const extracted: any = await http.post('/ai/extract-form', { text: ocr.text, formHint: 'elder_profile' });
  Object.assign(form, extracted.data);
  if (!form.health) form.health = {};
  form.health.allergies = extracted.data.allergies || '';
  form.health.chronicDiseases = extracted.data.chronicDiseases || '';
  await openCreate();
  ElMessage.success('已用 OCR/编排结果预填表单（演示为 mock）');
}

onMounted(load);
</script>
