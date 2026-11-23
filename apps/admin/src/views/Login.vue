<template>
  <div class="login-page">
    <div class="panel">
      <h1>智能养老主控台</h1>
      <p>管理端 · 家属/护理视角 · Agent 合一</p>
      <el-form @submit.prevent="onSubmit">
        <el-form-item label="账号">
          <el-input v-model="username" placeholder="admin" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="password" type="password" show-password placeholder="123456" />
        </el-form-item>
        <el-button type="primary" style="width: 100%" :loading="loading" @click="onSubmit">
          登录
        </el-button>
      </el-form>
      <div class="hint">演示账号：admin / nurse / caregiver / finance / family，密码均为 123456</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { useAuthStore } from '../stores/auth';

const auth = useAuthStore();
const router = useRouter();
const username = ref('admin');
const password = ref('123456');
const loading = ref(false);

async function onSubmit() {
  loading.value = true;
  try {
    await auth.login(username.value, password.value);
    ElMessage.success('登录成功');
    router.push('/dashboard');
  } catch (e: any) {
    ElMessage.error(String(e));
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  background:
    radial-gradient(circle at 20% 20%, #cfe8d8, transparent 40%),
    radial-gradient(circle at 80% 0%, #d9e8f5, transparent 35%),
    linear-gradient(160deg, #eef5f0, #f7faf8 60%, #e7efe9);
  padding: 24px;
}
.panel {
  width: min(420px, 100%);
  background: rgba(255, 255, 255, 0.92);
  border-radius: 16px;
  padding: 32px 28px;
  box-shadow: 0 12px 40px rgba(31, 59, 44, 0.12);
}
h1 {
  margin: 0;
  font-size: 32px;
  letter-spacing: 0.12em;
}
p {
  margin: 8px 0 24px;
  color: #61766a;
}
.hint {
  margin-top: 16px;
  font-size: 12px;
  color: #7a8c81;
  line-height: 1.5;
}
</style>
