<template>
  <el-container class="layout">
    <el-aside :width="collapsed ? '72px' : '220px'" class="aside">
      <div class="brand">
        <span v-if="!collapsed">阳光养老</span>
        <span v-else>阳</span>
      </div>
      <el-menu
        :default-active="route.path"
        router
        background-color="#1f3b2c"
        text-color="#d7e8dc"
        active-text-color="#ffffff"
        :collapse="collapsed"
      >
        <el-menu-item v-for="item in menus" :key="item.path" :index="item.path">
          <span>{{ item.title }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <div class="left">
          <el-button text @click="collapsed = !collapsed">菜单</el-button>
          <span class="sub">管理后台 · 兼容桌面 / 手机浏览器</span>
        </div>
        <div class="right">
          <span>{{ auth.user?.name }}（{{ auth.user?.role }}）</span>
          <el-button type="danger" link @click="onLogout">退出</el-button>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '../stores/auth';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const collapsed = ref(false);

const menus = [
  { path: '/dashboard', title: '运营看板' },
  { path: '/beds', title: '楼层床位' },
  { path: '/elders', title: '老人档案' },
  { path: '/care', title: '照护服务' },
  { path: '/billing', title: '收费财务' },
  { path: '/meals', title: '食堂餐食' },
  { path: '/medical', title: '医护健康' },
  { path: '/ltc', title: '长护险' },
  { path: '/inventory', title: '后勤物资' },
  { path: '/hr', title: '人事排班' },
  { path: '/security', title: '安防告警' },
  { path: '/reports', title: '报表报送' },
  { path: '/settings', title: '系统设置' },
];

function onLogout() {
  auth.logout();
  router.push('/login');
}
</script>

<style scoped>
.layout {
  min-height: 100vh;
}
.aside {
  background: var(--nh-sidebar);
  transition: width 0.2s;
}
.brand {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 700;
  letter-spacing: 0.08em;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #fff;
  border-bottom: 1px solid #e5eee8;
}
.left,
.right {
  display: flex;
  gap: 12px;
  align-items: center;
}
.sub {
  color: #6a7b71;
  font-size: 13px;
}
.main {
  padding: 16px;
}
@media (max-width: 768px) {
  .aside {
    position: fixed;
    z-index: 20;
    height: 100%;
  }
  .sub {
    display: none;
  }
}
</style>
