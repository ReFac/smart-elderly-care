<template>
  <div class="page-card">
    <h2 class="page-title">Agent 智能体控制台</h2>
    <p class="muted">Harness / MCP / Hook / Skill · DeepSeek · Typeless 语音入口</p>

    <el-tabs v-model="tab">
      <el-tab-pane label="能力清单" name="manifest">
        <el-button @click="loadManifest">刷新 Manifest</el-button>
        <pre class="box">{{ pretty(manifest) }}</pre>
      </el-tab-pane>

      <el-tab-pane label="感知融合" name="fusion">
        <div class="toolbar">
          <el-input v-model="fusion.bed_id" placeholder="床位ID" style="width:140px" />
          <el-input v-model="fusion.elder_id" placeholder="老人ID" style="width:180px" />
          <el-button type="primary" @click="runFusion">模拟多源融合告警</el-button>
        </div>
        <pre class="box">{{ pretty(fusionResult) }}</pre>
      </el-tab-pane>

      <el-tab-pane label="语音照护" name="care">
        <el-input v-model="care.transcript" type="textarea" :rows="3" placeholder="护工口述，例如：给张建国翻身拍背，食欲一般" />
        <div class="toolbar" style="margin-top:8px">
          <el-input v-model="care.bed_id" placeholder="床位" style="width:140px" />
          <el-input v-model="care.elder_id" placeholder="老人ID" style="width:180px" />
          <el-button type="primary" @click="runCare">增量生成草稿</el-button>
        </div>
        <pre class="box">{{ pretty(careResult) }}</pre>
      </el-tab-pane>

      <el-tab-pane label="Typeless" name="typeless">
        <el-input v-model="typeless.utterance" type="textarea" :rows="2" placeholder="全语音/自然语言，无需表单" />
        <div class="toolbar" style="margin-top:8px">
          <el-input v-model="typeless.bed_id" placeholder="床位" style="width:140px" />
          <el-input v-model="typeless.elder_id" placeholder="老人ID" style="width:180px" />
          <el-button type="primary" @click="runTypeless">执行</el-button>
        </div>
        <pre class="box">{{ pretty(typelessResult) }}</pre>
      </el-tab-pane>

      <el-tab-pane label="会议纪要" name="meeting">
        <el-input v-model="meetingText" type="textarea" :rows="4" placeholder="粘贴交接班口述片段，多段用空行分隔" />
        <el-button type="primary" style="margin-top:8px" @click="runMeeting">生成纪要</el-button>
        <pre class="box">{{ pretty(meetingResult) }}</pre>
      </el-tab-pane>

      <el-tab-pane label="健康自动" name="health">
        <div class="toolbar">
          <el-input v-model="health.elder_id" placeholder="老人ID" style="width:200px" />
          <el-button type="primary" @click="runHealth">自动评估健康状态</el-button>
        </div>
        <pre class="box">{{ pretty(healthResult) }}</pre>
      </el-tab-pane>

      <el-tab-pane label="审计/复核" name="audit">
        <el-button @click="loadAudit">刷新审计</el-button>
        <el-button @click="loadReviews">刷新人工复核队列</el-button>
        <h4>审计链路</h4>
        <pre class="box">{{ pretty(audit) }}</pre>
        <h4>人工复核</h4>
        <el-table :data="reviews" size="small">
          <el-table-column prop="id" label="ID" width="160" />
          <el-table-column prop="action" label="动作" />
          <el-table-column prop="status" label="状态" />
          <el-table-column label="操作">
            <template #default="{ row }">
              <el-button size="small" @click="resolve(row,'approved')">通过</el-button>
              <el-button size="small" type="danger" @click="resolve(row,'rejected')">驳回</el-button>
            </template>
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

const tab = ref('manifest');
const manifest = ref<any>(null);
const fusionResult = ref<any>(null);
const careResult = ref<any>(null);
const typelessResult = ref<any>(null);
const meetingResult = ref<any>(null);
const healthResult = ref<any>(null);
const audit = ref<any[]>([]);
const reviews = ref<any[]>([]);
const meetingText = ref('今晚失智区要加强巡视。\n\n张建国血压偏高需要复查。\n\n待办：护士长确认夜间排班。');

const fusion = reactive({ bed_id: 'A101-1', elder_id: '' });
const care = reactive({ bed_id: 'A101-1', elder_id: '', transcript: '给老人翻身拍背，口腔护理已完成，无压疮。' });
const typeless = reactive({ utterance: '帮我记一下刚做的翻身护理', bed_id: 'A101-1', elder_id: '' });
const health = reactive({ elder_id: '' });

const pretty = (v: any) => (v ? JSON.stringify(v, null, 2) : '');

async function ensureElderIds() {
  const elders: any[] = await http.get('/elders');
  if (elders[0]) {
    fusion.elder_id = care.elder_id = typeless.elder_id = health.elder_id = elders[0].id;
    care.bed_id = fusion.bed_id = typeless.bed_id = elders[0].bed?.code || 'A101-1';
  }
}

async function loadManifest() {
  const res: any = await http.get('/agent/manifest');
  manifest.value = res.data || res;
}
async function runFusion() {
  const now = new Date().toISOString();
  const body = {
    bed_id: fusion.bed_id,
    elder_id: fusion.elder_id,
    events: [
      { source: 'cv_pose', bed_id: fusion.bed_id, elder_id: fusion.elder_id, event_type: 'fall_like', confidence: 0.62, ts: now },
      { source: 'mmwave_60g', bed_id: fusion.bed_id, elder_id: fusion.elder_id, event_type: 'impact', confidence: 0.71, ts: now },
      { source: 'acoustic_aed', bed_id: fusion.bed_id, elder_id: fusion.elder_id, event_type: 'impact', confidence: 0.55, ts: now },
      { source: 'call_terminal', bed_id: fusion.bed_id, elder_id: fusion.elder_id, event_type: 'sos', confidence: 0.9, ts: now },
    ],
  };
  const res: any = await http.post('/agent/fusion', body);
  fusionResult.value = res.data || res;
  ElMessage.success('融合完成');
}
async function runCare() {
  const res: any = await http.post('/agent/care/voice', care);
  careResult.value = res.data || res;
}
async function runTypeless() {
  const res: any = await http.post('/agent/typeless', typeless);
  typelessResult.value = res.data || res;
}
async function runMeeting() {
  const segments = meetingText.value.split(/\n\s*\n/).map((s) => s.trim()).filter(Boolean);
  const res: any = await http.post('/agent/meeting', { meeting_type: 'handover', transcript_segments: segments, attendees: ['护士长', '值班护理'] });
  meetingResult.value = res.data || res;
}
async function runHealth() {
  const res: any = await http.post('/agent/health/auto', {
    elder_id: health.elder_id,
    vitals: [{ systolic: 168, diastolic: 96, glucose: 7.1, temperature: 36.7, spo2: 96 }],
  });
  healthResult.value = res.data || res;
}
async function loadAudit() {
  const res: any = await http.get('/agent/audit');
  audit.value = res.data || res;
}
async function loadReviews() {
  const res: any = await http.get('/agent/reviews');
  reviews.value = res.data || res;
}
async function resolve(row: any, decision: string) {
  await http.post(`/agent/reviews/${row.id}/resolve`, { decision });
  loadReviews();
}

onMounted(async () => {
  await ensureElderIds();
  try {
    await loadManifest();
  } catch (e: any) {
    ElMessage.warning('Agent 服务未就绪：请先启动 apps/agent (8100)');
  }
});
</script>

<style scoped>
.muted { color: #6a7b71; margin-top: -8px; margin-bottom: 12px; }
.box {
  margin-top: 12px;
  background: #f4f7f5;
  border-radius: 8px;
  padding: 12px;
  max-height: 360px;
  overflow: auto;
  font-size: 12px;
}
</style>
