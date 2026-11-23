<template>
  <div class="nh-page">
    <header class="nh-page-header">
      <div>
        <p class="nh-kicker">Clinical Intel</p>
        <h1 class="nh-title">声学异常与 AI 预诊</h1>
        <p class="nh-subtitle">
          床头麦克风可选接入；敏捷度可调。Stub + 接口预留，SOTA 见 docs/clinical-intel-sota.md。
        </p>
      </div>
    </header>
    <div class="page-card">

    <el-tabs v-model="tab">
      <el-tab-pane label="识别敏捷度" name="cfg">
        <el-form v-if="cfg" label-width="160px" style="max-width: 640px">
          <el-form-item label="启用流水线">
            <el-switch v-model="cfg.enabled" />
          </el-form-item>
          <el-form-item label="咳嗽灵敏度">
            <el-slider v-model="cfg.coughSensitivity" :min="0" :max="1" :step="0.01" show-input />
          </el-form-item>
          <el-form-item label="急促窗口(秒)">
            <el-input-number v-model="cfg.paroxysmalWindowSec" :min="1" :max="60" />
          </el-form-item>
          <el-form-item label="急促最少次数">
            <el-input-number v-model="cfg.paroxysmalMinCount" :min="1" :max="20" />
          </el-form-item>
          <el-form-item label="硬碰撞阈值">
            <el-slider v-model="cfg.hardImpactThreshold" :min="0" :max="1" :step="0.01" show-input />
          </el-form-item>
          <el-form-item label="忽略软碰撞">
            <el-switch v-model="cfg.softImpactIgnore" />
          </el-form-item>
          <el-form-item label="自动写档案">
            <el-switch v-model="cfg.autoUpdateProfile" />
          </el-form-item>
          <el-form-item label="自动院内推送">
            <el-switch v-model="cfg.autoFacilityPush" />
          </el-form-item>
          <el-form-item label="SOTA 推理 URL">
            <el-input v-model="cfg.inferenceBaseUrl" placeholder="https://sota.example/acoustic" />
          </el-form-item>
          <el-form-item label="模型 ID">
            <el-input v-model="cfg.modelId" />
          </el-form-item>
          <el-button type="primary" @click="saveCfg">保存敏捷度</el-button>
        </el-form>
      </el-tab-pane>

      <el-tab-pane label="事件模拟 / 列表" name="events">
        <div class="toolbar">
          <el-select v-model="sim.elderId" filterable placeholder="选择老人" style="width: 180px">
            <el-option v-for="e in elders" :key="e.id" :label="e.name" :value="e.id" />
          </el-select>
          <el-select v-model="sim.hint" style="width: 200px">
            <el-option label="急促型咳嗽" value="急促咳嗽 paroxysmal" />
            <el-option label="普通咳嗽" value="咳嗽" />
            <el-option label="明显硬碰撞" value="明显硬碰撞 impact" />
            <el-option label="普通软碰撞" value="软碰撞 impact" />
          </el-select>
          <el-slider v-model="sim.confidence" :min="0" :max="1" :step="0.01" style="width: 160px" />
          <el-button type="primary" @click="ingest">模拟摄入</el-button>
          <el-button @click="loadEvents">刷新</el-button>
        </div>
        <pre class="box" v-if="lastIngest">{{ pretty(lastIngest) }}</pre>
        <el-table :data="events" size="small" max-height="360">
          <el-table-column prop="eventType" label="类型" width="90" />
          <el-table-column prop="subtype" label="子类" width="140" />
          <el-table-column prop="confidence" label="置信度" width="90" />
          <el-table-column prop="pathological" label="病理" width="70">
            <template #default="{ row }">{{ row.pathological ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column prop="note" label="说明" />
          <el-table-column label="标注" width="200">
            <template #default="{ row }">
              <el-button size="small" @click="label(row, 'false_positive')">误报</el-button>
              <el-button size="small" @click="label(row, 'true_positive')">属实</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="AI 预诊框" name="pre">
        <div class="toolbar">
          <el-select v-model="preElderId" filterable placeholder="选择老人" style="width: 200px">
            <el-option v-for="e in elders" :key="e.id" :label="e.name" :value="e.id" />
          </el-select>
          <el-button type="primary" :disabled="!preElderId" @click="generate">一键生成 AI 建议</el-button>
        </div>
        <div v-if="preResult" class="pre-box">
          <el-alert type="warning" show-icon :closable="false" title="辅助信息，不构成医疗诊断或处方" />
          <h3>相关情况</h3>
          <pre>{{ preResult.draft?.situation }}</pre>
          <h3>医学性建议</h3>
          <pre>{{ preResult.draft?.medicalAdvice }}</pre>
          <h3>风险提示</h3>
          <pre>{{ preResult.draft?.riskHints }}</pre>
          <h3>可能性推断</h3>
          <el-table :data="preResult.draft?.inferences || []" size="small">
            <el-table-column prop="hypothesis" label="假设" />
            <el-table-column prop="confidence" label="置信度" width="90" />
            <el-table-column prop="rationale" label="依据" />
          </el-table>
          <p class="hint">家属推送需护工批准：{{ preResult.familyPush?.status }}</p>
        </div>
        <h3>历史报告</h3>
        <el-table :data="reports" size="small">
          <el-table-column prop="elderId" label="老人" width="120" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column prop="modelId" label="模型" width="160" />
          <el-table-column prop="createdAt" label="时间" />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="推送 / 提示词" name="push">
        <div class="toolbar">
          <el-button @click="loadPushes">刷新推送</el-button>
          <el-button @click="loadPrompts">刷新提示词</el-button>
        </div>
        <el-table :data="pushes" size="small" max-height="280">
          <el-table-column prop="audience" label="受众" width="90" />
          <el-table-column prop="title" label="标题" />
          <el-table-column prop="status" label="状态" width="100" />
          <el-table-column label="操作" width="220">
            <template #default="{ row }">
              <el-button size="small" type="primary" @click="approveFamily(row)">批准推家属</el-button>
              <el-button size="small" @click="rejectFamily(row)">拒绝</el-button>
            </template>
          </el-table-column>
        </el-table>
        <h3>系统提示词</h3>
        <el-table :data="prompts" size="small">
          <el-table-column prop="key" label="Key" width="220" />
          <el-table-column prop="title" label="标题" width="160" />
          <el-table-column prop="version" label="版本" width="80" />
          <el-table-column prop="content" label="内容" show-overflow-tooltip />
        </el-table>
      </el-tab-pane>
    </el-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import http from '../api/http';

const tab = ref('cfg');
const cfg = ref<any>(null);
const elders = ref<any[]>([]);
const events = ref<any[]>([]);
const lastIngest = ref<any>(null);
const sim = reactive({ elderId: '', hint: '急促咳嗽 paroxysmal', confidence: 0.8 });
const preElderId = ref('');
const preResult = ref<any>(null);
const reports = ref<any[]>([]);
const pushes = ref<any[]>([]);
const prompts = ref<any[]>([]);

function pretty(v: any) {
  return JSON.stringify(v, null, 2);
}

async function loadCfg() {
  cfg.value = (await http.get('/clinical/config')) || {};
}
async function saveCfg() {
  cfg.value = await http.put('/clinical/config', cfg.value);
  ElMessage.success('敏捷度已保存');
}
async function loadElders() {
  elders.value = await http.get('/elders');
  if (elders.value[0]) {
    sim.elderId = elders.value[0].id;
    preElderId.value = elders.value[0].id;
  }
}
async function loadEvents() {
  events.value = await http.get('/clinical/events');
}
async function ingest() {
  lastIngest.value = await http.post('/clinical/events/ingest', {
    elderId: sim.elderId,
    hint: sim.hint,
    confidence: sim.confidence,
    paroxysmal: sim.hint.includes('急促'),
    hard: sim.hint.includes('硬'),
  });
  ElMessage.success(lastIngest.value?.classification?.note || '已摄入');
  loadEvents();
}
async function label(row: any, kind: string) {
  await http.post(`/clinical/events/${row.id}/label`, { kind });
  loadEvents();
}
async function generate() {
  preResult.value = await http.post('/clinical/prediagnosis/generate', { elderId: preElderId.value });
  reports.value = await http.get('/clinical/prediagnosis');
  ElMessage.success('已生成预诊草稿');
}
async function loadPushes() {
  pushes.value = await http.get('/clinical/pushes');
}
async function loadPrompts() {
  prompts.value = await http.get('/clinical/prompts');
}
async function approveFamily(row: any) {
  await http.post(`/clinical/pushes/${row.id}/approve-family`, { reportId: row.reportId });
  ElMessage.success('已批准推送家属');
  loadPushes();
}
async function rejectFamily(row: any) {
  await http.post(`/clinical/pushes/${row.id}/reject-family`, { reason: 'staff rejected' });
  loadPushes();
}

onMounted(async () => {
  await Promise.all([loadCfg(), loadElders(), loadEvents(), loadPushes(), loadPrompts()]);
  reports.value = await http.get('/clinical/prediagnosis');
});
</script>

<style scoped>
.hint { color: #6a7b71; margin-top: -8px; }
.box, .pre-box pre {
  background: #f4f7f5;
  padding: 12px;
  border-radius: 10px;
  white-space: pre-wrap;
  font-size: 13px;
}
.pre-box h3 { margin: 14px 0 6px; font-size: 15px; }
</style>
