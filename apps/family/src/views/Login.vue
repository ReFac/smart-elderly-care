<template>
  <div class="app-shell" style="padding: 48px 20px">
    <h1 style="margin: 0 0 8px">阳光养老</h1>
    <p class="muted">家属端 / 护理端 H5（可扩展微信小程序）</p>
    <div class="card" style="margin: 24px 0">
      <input class="input" v-model="username" placeholder="账号 family 或 caregiver" />
      <input class="input" v-model="password" type="password" placeholder="密码 123456" />
      <button class="btn" @click="login">登录</button>
      <p class="muted" style="margin-top: 12px; font-size: 12px">
        家属账号 family 可看账单餐食；护理账号 caregiver 可打卡工单。
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import http from '../api';

const router = useRouter();
const username = ref('family');
const password = ref('123456');

async function login() {
  try {
    const res: any = await http.post('/auth/login', {
      username: username.value,
      password: password.value,
    });
    localStorage.setItem('nh_family_token', res.accessToken);
    localStorage.setItem('nh_family_user', JSON.stringify(res.user));
    router.push('/home');
  } catch (e: any) {
    alert(String(e));
  }
}
</script>
