<template>
  <el-dialog
    :model-value="modelValue"
    width="560px"
    class="priv-dialog"
    append-to-body
    destroy-on-close
    :close-on-click-modal="false"
    @close="emit('update:modelValue', false)"
  >
    <template #header>
      <div class="priv-head">
        <span class="badge">高权限</span>
        <h3>{{ action?.title || '确认变更' }}</h3>
      </div>
    </template>

    <p class="summary">{{ action?.summary }}</p>

    <label class="review-label">变更甄别（确认前请逐条核对）</label>
    <div class="review-box" tabindex="0">
      <div v-for="(c, i) in action?.changes || []" :key="i" class="diff-row">
        <div class="diff-path">{{ c.path }}</div>
        <div class="diff-line">
          <span class="before">− {{ c.before }}</span>
          <span class="after">+ {{ c.after }}</span>
        </div>
        <div class="diff-impact">影响：{{ c.impact }}</div>
      </div>
      <p v-if="!(action?.changes?.length)" class="empty">无结构化变更明细</p>
    </div>

    <el-form label-position="top" @submit.prevent="confirm">
      <el-form-item label="管理员密码（每次高权限必填）">
        <el-input
          v-model="password"
          type="password"
          show-password
          placeholder="输入当前管理员密码"
          autocomplete="current-password"
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="danger" :loading="loading" :disabled="!password" @click="confirm">
        密码确认并执行
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import http from '../api/http';

const props = defineProps<{
  modelValue: boolean;
  action: any | null;
}>();
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void;
  (e: 'done', result: any): void;
}>();

const password = ref('');
const loading = ref(false);

watch(
  () => props.modelValue,
  (v) => {
    if (v) password.value = '';
  },
);

async function confirm() {
  if (!props.action || !password.value) return;
  loading.value = true;
  try {
    const reauth: any = await http.post('/auth/reauth', { password: password.value });
    const result = await http.post('/agent/console/execute', {
      action: props.action,
      password: password.value,
      elevateToken: reauth.elevateToken,
    });
    ElMessage.success('高权限变更已执行');
    emit('done', result);
    emit('update:modelValue', false);
  } catch (e: any) {
    ElMessage.error(String(e || '执行失败'));
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.priv-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.priv-head h3 {
  margin: 0;
  font-family: var(--nh-display);
  font-size: 1.15rem;
}
.badge {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #fff;
  background: linear-gradient(120deg, #c0392b, #c45c26);
  padding: 4px 8px;
  border-radius: 999px;
}
.summary {
  margin: 0 0 14px;
  color: var(--nh-muted);
  font-size: 14px;
  line-height: 1.5;
}
.review-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--nh-ink-soft);
  margin-bottom: 8px;
}
.review-box {
  max-height: 240px;
  overflow: auto;
  border: 1px solid var(--nh-line-strong);
  border-radius: 12px;
  background: #0d1a19;
  color: #d7e8e4;
  padding: 12px 14px;
  font-family: ui-monospace, 'SF Mono', Menlo, monospace;
  font-size: 12px;
  line-height: 1.55;
  margin-bottom: 16px;
  outline: none;
}
.review-box:focus {
  box-shadow: 0 0 0 2px rgba(15, 143, 120, 0.35);
}
.diff-row + .diff-row {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}
.diff-path {
  color: #7eb8ad;
  margin-bottom: 4px;
}
.diff-line {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.before {
  color: #f0a8a0;
}
.after {
  color: #9ddebf;
}
.diff-impact {
  margin-top: 4px;
  color: #9aaeaa;
}
.empty {
  margin: 0;
  color: #9aaeaa;
}
</style>
