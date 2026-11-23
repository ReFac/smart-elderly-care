<template>
  <div class="login-page">
    <div class="login-stage">
      <div class="login-brand">
        <div class="mark">阳</div>
        <h1>阳光养老</h1>
        <p>统一主控台 · 运营 / 医护 / Agent</p>
      </div>
      <form class="login-panel" @submit.prevent="onSubmit">
        <p class="kicker">Sign in</p>
        <h2>进入主控台</h2>
        <label>
          <span>账号</span>
          <input v-model="username" autocomplete="username" placeholder="admin" />
        </label>
        <label>
          <span>密码</span>
          <input v-model="password" type="password" autocomplete="current-password" placeholder="••••••" />
        </label>
        <button type="submit" :disabled="loading">{{ loading ? '登录中…' : '继续' }}</button>
        <p class="hint">演示：admin / nurse / caregiver / finance / family · 密码 123456</p>
      </form>
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
  padding: 24px;
  background:
    radial-gradient(700px 420px at 15% 10%, rgba(15, 143, 120, 0.22), transparent 55%),
    radial-gradient(560px 360px at 90% 0%, rgba(40, 90, 130, 0.12), transparent 50%),
    linear-gradient(165deg, #e9f1ef, #f5f8f7 55%, #e4ecea);
}
.login-stage {
  width: min(920px, 100%);
  display: grid;
  grid-template-columns: 1.05fr 0.95fr;
  gap: 28px;
  align-items: stretch;
  animation: nh-rise 0.45s ease both;
}
.login-brand {
  padding: 48px 28px;
  color: #0c2422;
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.mark {
  width: 56px;
  height: 56px;
  border-radius: 18px;
  display: grid;
  place-items: center;
  font-family: var(--nh-display);
  font-weight: 800;
  font-size: 1.4rem;
  color: #fff;
  background: linear-gradient(145deg, #1aa888, #0b6e5c);
  box-shadow: 0 16px 36px rgba(15, 143, 120, 0.3);
  margin-bottom: 22px;
}
.login-brand h1 {
  margin: 0;
  font-family: var(--nh-display);
  font-size: clamp(2.4rem, 2rem + 2vw, 3.4rem);
  font-weight: 800;
  letter-spacing: -0.04em;
  line-height: 1.05;
}
.login-brand p {
  margin: 12px 0 0;
  color: var(--nh-muted);
  font-size: 1.05rem;
  max-width: 28ch;
}
.login-panel {
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(18px);
  border: 1px solid rgba(12, 36, 34, 0.08);
  border-radius: 24px;
  padding: 32px 28px;
  box-shadow: var(--nh-shadow-lg);
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.kicker {
  margin: 0;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--nh-accent-strong);
}
.login-panel h2 {
  margin: 0 0 8px;
  font-family: var(--nh-display);
  font-size: 1.55rem;
  letter-spacing: -0.02em;
}
label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: var(--nh-muted);
  font-weight: 500;
}
input {
  border: 1px solid var(--nh-line-strong);
  border-radius: 12px;
  padding: 12px 14px;
  font: inherit;
  font-size: 15px;
  color: var(--nh-ink);
  background: #fff;
}
input:focus {
  outline: none;
  border-color: var(--nh-accent);
  box-shadow: 0 0 0 3px var(--nh-accent-soft);
}
button[type='submit'] {
  margin-top: 6px;
  border: none;
  border-radius: 12px;
  padding: 13px 16px;
  font: inherit;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(120deg, #0f8f78, #0b6e5c);
  cursor: pointer;
  box-shadow: 0 12px 24px rgba(15, 143, 120, 0.28);
}
button[type='submit']:disabled {
  opacity: 0.6;
  cursor: wait;
}
.hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--nh-muted);
  line-height: 1.5;
}
@media (max-width: 800px) {
  .login-stage {
    grid-template-columns: 1fr;
  }
  .login-brand {
    padding: 12px 8px 0;
  }
}
</style>
