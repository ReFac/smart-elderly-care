<template>
  <div class="shell" :class="{ 'agent-open': agentOpen, 'nav-collapsed': collapsed }">
    <aside class="nav">
      <div class="brand-block">
        <div class="brand-mark">阳</div>
        <div v-if="!collapsed" class="brand-text">
          <div class="brand-name">阳光养老</div>
          <div class="brand-sub">主控台 · 2026</div>
        </div>
      </div>

      <nav class="nav-scroll">
        <section v-for="g in menuGroups" :key="g.key" class="nav-group">
          <p v-if="!collapsed" class="nav-label">{{ g.label }}</p>
          <router-link
            v-for="item in g.items"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            :class="{ active: route.path === item.path || route.path.startsWith(item.path + '/') }"
            :title="item.title"
          >
            <span class="nav-dot" />
            <span v-if="!collapsed">{{ item.title }}</span>
          </router-link>
        </section>
      </nav>

      <button class="collapse-btn" type="button" @click="collapsed = !collapsed">
        {{ collapsed ? '⟩' : '⟨ 收起' }}
      </button>
    </aside>

    <div class="workspace">
      <header class="topbar">
        <div class="top-left">
          <el-autocomplete
            v-model="searchQ"
            :fetch-suggestions="querySearch"
            placeholder="搜索功能、设置、API…"
            class="cmd-search"
            clearable
            popper-class="nh-search-popper"
            @select="onSelect"
          >
            <template #prefix>
              <span class="search-ico">⌘</span>
            </template>
            <template #default="{ item }">
              <div class="sug">
                <b>{{ item.title }}</b>
                <span class="sug-meta">{{ item.groupLabel }} · {{ item.apiPrefix }}</span>
                <div class="sug-desc">{{ item.description }}</div>
              </div>
            </template>
          </el-autocomplete>
        </div>
        <div class="top-right">
          <span class="role-pill">主管理员</span>
          <span class="user-name">{{ auth.user?.name }}</span>
          <button class="agent-toggle" type="button" @click="agentOpen = !agentOpen">
            {{ agentOpen ? '收起 Agent' : 'Agent' }}
          </button>
          <button class="ghost-btn" type="button" @click="onLogout">退出</button>
        </div>
      </header>

      <main class="main">
        <router-view />
      </main>
    </div>

    <AgentRail v-if="agentOpen" :open="agentOpen" @close="agentOpen = false" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { FEATURE_REGISTRY, MODULE_GROUP_LABELS, searchFeatures, type ModuleGroup } from '@nh/shared';
import { useAuthStore } from '../stores/auth';
import http from '../api/http';
import AgentRail from '../components/AgentRail.vue';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const collapsed = ref(false);
const agentOpen = ref(true);
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
    cb(
      searchFeatures(q).map((f) => ({
        ...f,
        value: f.title,
        groupLabel: MODULE_GROUP_LABELS[f.group],
      })),
    );
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
.shell {
  display: grid;
  grid-template-columns: 248px minmax(0, 1fr);
  min-height: 100vh;
  transition: grid-template-columns 0.28s ease;
}
.shell.nav-collapsed {
  grid-template-columns: 76px minmax(0, 1fr);
}
.shell.agent-open {
  grid-template-columns: 248px minmax(0, 1fr) var(--nh-agent-width);
}
.shell.agent-open.nav-collapsed {
  grid-template-columns: 76px minmax(0, 1fr) var(--nh-agent-width);
}

.nav {
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, #0c2422 0%, #081816 100%);
  color: #d7e8e4;
  border-right: 1px solid rgba(255, 255, 255, 0.05);
}
.brand-block {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.brand-mark {
  width: 40px;
  height: 40px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  font-family: var(--nh-display);
  font-weight: 800;
  background: linear-gradient(145deg, #1aa888, #0b6e5c);
  color: #fff;
  box-shadow: 0 8px 20px rgba(15, 143, 120, 0.35);
  flex-shrink: 0;
}
.brand-name {
  font-family: var(--nh-display);
  font-weight: 700;
  font-size: 1.05rem;
  letter-spacing: -0.02em;
  color: #fff;
}
.brand-sub {
  font-size: 11px;
  color: #7eb8ad;
  margin-top: 2px;
}
.nav-scroll {
  flex: 1;
  overflow: auto;
  padding: 12px 10px 20px;
}
.nav-group + .nav-group {
  margin-top: 14px;
}
.nav-label {
  margin: 0 8px 6px;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #6f918a;
  font-weight: 600;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border-radius: 12px;
  color: #c5d9d4;
  font-size: 13.5px;
  margin-bottom: 2px;
  transition: background 0.15s ease, color 0.15s ease;
}
.nav-item:hover {
  background: rgba(255, 255, 255, 0.05);
  color: #fff;
}
.nav-item.active {
  background: rgba(15, 143, 120, 0.22);
  color: #fff;
  box-shadow: inset 0 0 0 1px rgba(15, 143, 120, 0.35);
}
.nav-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #4d6f6a;
  flex-shrink: 0;
}
.nav-item.active .nav-dot {
  background: #3dd4b0;
  box-shadow: 0 0 0 3px rgba(61, 212, 176, 0.2);
}
.collapse-btn {
  margin: 8px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: transparent;
  color: #9bb5af;
  border-radius: 10px;
  padding: 8px;
  cursor: pointer;
  font-size: 12px;
}

.workspace {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 100vh;
}
.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  backdrop-filter: blur(16px);
  background: rgba(244, 247, 246, 0.78);
  border-bottom: 1px solid var(--nh-line);
}
.top-left,
.top-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.cmd-search {
  width: min(440px, 52vw);
}
.cmd-search :deep(.el-input__wrapper) {
  border-radius: 999px;
  box-shadow: 0 0 0 1px var(--nh-line) inset !important;
  background: rgba(255, 255, 255, 0.88);
  padding-left: 8px;
}
.search-ico {
  color: var(--nh-muted);
  font-size: 12px;
  font-weight: 700;
  margin-left: 4px;
}
.role-pill {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--nh-accent-strong);
  background: var(--nh-accent-soft);
  padding: 5px 10px;
  border-radius: 999px;
}
.user-name {
  font-size: 13px;
  color: var(--nh-ink-soft);
}
.agent-toggle {
  border: none;
  border-radius: 999px;
  padding: 8px 14px;
  font-weight: 600;
  font-size: 13px;
  color: #fff;
  background: linear-gradient(120deg, #0f8f78, #0b6e5c);
  cursor: pointer;
  box-shadow: 0 8px 18px rgba(15, 143, 120, 0.25);
}
.ghost-btn {
  border: 1px solid var(--nh-line-strong);
  background: transparent;
  border-radius: 999px;
  padding: 7px 12px;
  font-size: 13px;
  cursor: pointer;
  color: var(--nh-muted);
}
.main {
  padding: 20px 22px 40px;
  flex: 1;
}
.sug b {
  display: block;
}
.sug-meta {
  color: var(--nh-muted);
  font-size: 12px;
}
.sug-desc {
  color: var(--nh-ink-soft);
  font-size: 12px;
  margin-top: 2px;
}

@media (max-width: 1100px) {
  .shell,
  .shell.nav-collapsed,
  .shell.agent-open,
  .shell.agent-open.nav-collapsed {
    grid-template-columns: 76px minmax(0, 1fr);
  }
  .shell.agent-open {
    grid-template-columns: 76px minmax(0, 1fr);
  }
  .agent-rail-host {
    position: fixed;
  }
}
@media (max-width: 1100px) {
  :deep(.agent-rail) {
    position: fixed;
    right: 0;
    top: 0;
    bottom: 0;
    z-index: 40;
  }
}
</style>
