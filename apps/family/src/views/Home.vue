<template>
  <div>
    <div class="topbar">
      <h1>你好，{{ user?.name }}</h1>
      <p>{{ roleText }} · 信息透明可查</p>
    </div>
    <div class="card" v-if="user?.role === 'family'">
      <h3>绑定老人</h3>
      <div v-for="e in me?.elders || []" :key="e.id" class="row">
        <span>{{ e.name }}</span>
        <span class="chip">{{ e.relation || '家属' }}</span>
      </div>
      <p v-if="!(me?.elders?.length)" class="muted">暂无绑定老人</p>
    </div>
    <div class="card" v-if="portal">
      <h3>今日概览</h3>
      <div class="row"><span>待缴账单</span><span>{{ portal.stats?.openBills ?? 0 }}</span></div>
      <div class="row"><span>未完成照护</span><span>{{ portal.stats?.openCare ?? 0 }}</span></div>
      <p class="muted" style="margin-top:8px">{{ portal.mobileHint || '已适配手机 Chrome / Safari / 微信公众号' }}</p>
    </div>
    <div class="card">
      <h3>快捷入口</h3>
      <p class="muted">账单、餐食、照护与 3D 房态导览。支付通道已预留。</p>
      <button class="btn" style="margin-top: 8px" type="button" @click="router.push('/tour')">进入房态导览</button>
      <button class="btn secondary" style="margin-top: 8px" type="button" @click="logout">退出登录</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import http from '../api';

const router = useRouter();
const user = ref(JSON.parse(localStorage.getItem('nh_family_user') || 'null'));
const me = ref<any>(null);
const portal = ref<any>(null);
const roleText = computed(() =>
  user.value?.role === 'family' ? '家属端' : user.value?.role === 'caregiver' ? '护理端' : '移动端',
);

onMounted(async () => {
  me.value = await http.get('/auth/me');
  try {
    portal.value =
      user.value?.role === 'caregiver' || user.value?.role === 'nurse'
        ? await http.get('/portal/employee/home')
        : await http.get('/portal/user/home');
  } catch {
    portal.value = null;
  }
});

function logout() {
  localStorage.removeItem('nh_family_token');
  localStorage.removeItem('nh_family_user');
  router.push('/login');
}
</script>
