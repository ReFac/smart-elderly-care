<template>
  <el-container class="layout">
    <el-aside :width="collapsed ? '72px' : '240px'" class="aside">
      <div class="brand">
        <span v-if="!collapsed">智能养老 · 主控台</span>
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
        <el-menu-item-group v-for="g in menuGroups" :key="g.key">
          <template #title v-if="!collapsed">
            <span class="group-title">{{ g.label }}</span>
          </template>
          <el-menu-item v-for="item in g.items" :key="item.path" :index="item.path">
            <span>{{ item.title }}</span>
          </el-menu-item>
        </el-menu-item-group>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <div class="left">
          <el-button text @click="collapsed = !collapsed">菜单</el-button>
          <el-autocomplete
            v-model="searchQ"
            :fetch-suggestions="querySearch"
            placeholder="模糊搜索功能 / 设置 / API…"
            class="search"
            clearable
            @select="onSelect"
          >
            <template #default="{ item }">
              <div class="sug">
                <b>{{ item.title }}</b>
                <span class="sug-meta">{{ item.groupLabel }} · {{ item.apiPrefix }}</span>
                <div class="sug-desc">{{ item.description }}</div>
              </div>
            </template>
          </el-autocomplete>
        </div>
        <div class="right">
          <el-tag type="success" effect="plain">主管理员视角</el-tag>
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
import { computed, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { FEATURE_REGISTRY, MODULE_GROUP_LABELS, searchFeatures, type ModuleGroup } from '@nh/shared';
import { useAuthStore } from '../stores/auth';
import http from '../api/http';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const collapsed = ref(false);
const searchQ = ref('');

const order: ModuleGroup[] = ['ops', 'clinical', 'family', 'caregiver', 'agent', 'system'];

const menuGroups = computed(() =>
  order.map((key) => ({
    key,
    label: MODULE_GROUP_LABELS[key],
    items: FEATURE_REGISTRY.filter((f) => f.group === key),
  })),
);

async function querySearch(query: string, cb: (rows: any[]) => void) {
  const q = query.trim();
  if (!q) {
    cb(
      FEATURE_REGISTRY.slice(0, 8).map((f) => ({
        ...f,
        value: f.title,
        groupLabel: MODULE_GROUP_LABELS[f.group],
      })),
    );
    return;
  }
  try {
    const remote: any[] = await http.get('/extensions/search', { params: { q } });
    cb(
      (remote || []).map((f) => ({
        ...f,
        value: f.title,
        groupLabel: MODULE_GROUP_LABELS[f.group as ModuleGroup] || f.group,
      })),
    );
  } catch {
    const local = searchFeatures(q).map((f) => ({
      ...f,
      value: f.title,
      groupLabel: MODULE_GROUP_LABELS[f.group],
    }));
    cb(local);
  }
}

function onSelect(item: any) {
  if (item?.path) router.push(item.path);
  searchQ.value = '';
}

function onLogout() {
  auth.logout();
  router.push('/login');
}
</script>

<style scoped>
.layout { min-height: 100vh; }
.aside {
  background: var(--nh-sidebar);
  transition: width 0.2s;
  overflow: auto;
}
.brand {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 700;
  letter-spacing: 0.04em;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding: 0 8px;
  text-align: center;
  font-size: 14px;
}
.group-title {
  color: #8fb39a;
  font-size: 12px;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #fff;
  border-bottom: 1px solid #e5eee8;
  gap: 12px;
}
.left, .right {
  display: flex;
  gap: 12px;
  align-items: center;
}
.search { width: min(420px, 48vw); }
.sug b { display: block; }
.sug-meta { color: #6a7b71; font-size: 12px; }
.sug-desc { color: #405548; font-size: 12px; margin-top: 2px; }
.main { padding: 16px; }
@media (max-width: 768px) {
  .aside { position: fixed; z-index: 20; height: 100%; }
  .search { width: 160px; }
}
</style>
