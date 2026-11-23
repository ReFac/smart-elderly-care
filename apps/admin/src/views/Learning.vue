<template>
  <div class="page-card">
    <h2 class="page-title">学习与噪声</h2>
    <p class="hint">人工修正误判后自动注入噪声样本；误报加负样本噪声，漏报/修正加正样本邻域噪声。</p>

    <el-row :gutter="16">
      <el-col :md="12" :xs="24">
        <h3>提交人工修正</h3>
        <el-form label-width="100px">
          <el-form-item label="类型">
            <el-select v-model="form.kind" style="width: 100%">
              <el-option label="误报 false_positive（加噪声↑阈值）" value="false_positive" />
              <el-option label="漏报 false_negative（加噪声↑召回）" value="false_negative" />
              <el-option label="属实 true_positive" value="true_positive" />
              <el-option label="一般修正 correction" value="correction" />
            </el-select>
          </el-form-item>
          <el-form-item label="来源">
            <el-input v-model="form.source" placeholder="security / agent / care" />
          </el-form-item>
          <el-form-item label="置信度">
            <el-slider v-model="form.confidence" :min="0" :max="1" :step="0.01" show-input />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="form.note" type="textarea" />
          </el-form-item>
          <el-button type="primary" @click="submit">学习并加噪声</el-button>
          <el-button @click="syncAgent">同步到 Agent 反馈</el-button>
        </el-form>
        <pre class="box" v-if="last">{{ pretty(last) }}</pre>
      </el-col>
      <el-col :md="12" :xs="24">
        <div class="toolbar">
          <el-button @click="loadStats">刷新统计</el-button>
        </div>
        <el-descriptions :column="1" border v-if="stats">
          <el-descriptions-item label="学习事件">{{ stats.totalEvents }}</el-descriptions-item>
          <el-descriptions-item label="噪声库">{{ stats.noiseBankSize }}</el-descriptions-item>
          <el-descriptions-item label="分布">{{ pretty(stats.byKind) }}</el-descriptions-item>
        </el-descriptions>
        <h3>最近事件</h3>
        <el-table :data="stats?.recent || []" size="small">
          <el-table-column prop="kind" label="类型" width="120" />
          <el-table-column prop="noiseInjected" label="噪声条数" width="90" />
          <el-table-column prop="source" label="来源" />
          <el-table-column prop="createdAt" label="时间" />
        </el-table>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import http from '../api/http';

const form = reactive({
  kind: 'false_positive' as string,
  source: 'agent',
  confidence: 0.62,
  note: '',
});
const last = ref<any>(null);
const stats = ref<any>(null);
const pretty = (v: any) => JSON.stringify(v, null, 2);

async function submit() {
  last.value = await http.post('/extensions/learning/correct', {
    kind: form.kind,
    source: form.source,
    payload: { confidence: form.confidence, note: form.note, event_type: 'manual_correction' },
  });
  ElMessage.success(last.value?.hint || '已学习');
  loadStats();
}

async function syncAgent() {
  const label = form.kind === 'false_positive' ? 'false_positive' : 'true_positive';
  try {
    await http.post('/agent/feedback', {
      alert_id: `manual_${Date.now()}`,
      label,
      note: form.note,
    });
    ElMessage.success('已同步 Agent 反馈通道');
  } catch {
    ElMessage.warning('Agent 未就绪，仅完成后端噪声学习');
  }
}

async function loadStats() {
  stats.value = await http.get('/extensions/learning/stats');
}

onMounted(loadStats);
</script>

<style scoped>
.hint { color: #6a7b71; margin-top: -8px; }
.box { background: #f4f7f5; padding: 12px; border-radius: 8px; font-size: 12px; margin-top: 12px; max-height: 240px; overflow: auto; }
</style>
