<template>
  <aside class="agent-rail" :class="{ open }">
    <header class="rail-head">
      <div>
        <p class="rail-kicker">Console Agent</p>
        <h2>协作者</h2>
      </div>
      <button class="icon-btn" type="button" aria-label="关闭" @click="emit('close')">✕</button>
    </header>

    <div class="rail-hints">
      <button type="button" v-for="h in hints" :key="h" class="chip" @click="send(h)">{{ h }}</button>
    </div>

    <div ref="scroller" class="rail-messages">
      <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
        <div class="bubble">
          <pre>{{ m.content }}</pre>
          <div v-if="m.quickLinks?.length" class="links">
            <button
              v-for="l in m.quickLinks"
              :key="l.path"
              type="button"
              class="link-btn"
              @click="go(l.path)"
            >
              → {{ l.label }}
            </button>
          </div>
          <div v-if="m.actions?.length" class="actions">
            <button
              v-for="a in m.actions"
              :key="a.id"
              type="button"
              class="action-btn"
              @click="openPrivilege(a)"
            >
              甄别并确认：{{ a.title }}
            </button>
          </div>
        </div>
      </div>
      <div v-if="thinking" class="msg assistant">
        <div class="bubble thinking">正在理解意图…</div>
      </div>
    </div>

    <form class="rail-input" @submit.prevent="send()">
      <textarea
        v-model="draft"
        rows="2"
        placeholder="像 Codex 一样下达指令…（高权限会要求密码）"
        @keydown.enter.exact.prevent="send()"
      />
      <button type="submit" class="send" :disabled="!draft.trim() || thinking">发送</button>
    </form>

    <PrivilegeConfirm v-model="privOpen" :action="pendingAction" @done="onPrivilegedDone" />
  </aside>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import http from '../api/http';
import PrivilegeConfirm from './PrivilegeConfirm.vue';

defineProps<{ open: boolean }>();
const emit = defineEmits<{ (e: 'close'): void }>();

const route = useRoute();
const router = useRouter();
const draft = ref('');
const thinking = ref(false);
const messages = ref<any[]>([
  {
    role: 'assistant',
    content:
      '你好。我是嵌在主控台右侧的 Agent（类 Codex）。\n可搜索功能、起草配置变更。\n高权限操作会弹出变更甄别框，并每次校验管理员密码。',
    quickLinks: [],
    actions: [],
  },
]);
const scroller = ref<HTMLElement | null>(null);
const hints = ['打开临床智能', '调整咳嗽灵敏度', '停用 agent 服务', '搜索床位'];
const privOpen = ref(false);
const pendingAction = ref<any>(null);

watch(
  () => messages.value.length,
  async () => {
    await nextTick();
    if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight;
  },
);

function go(path: string) {
  router.push(path);
}

function openPrivilege(action: any) {
  pendingAction.value = action;
  privOpen.value = true;
}

function onPrivilegedDone(result: any) {
  messages.value.push({
    role: 'assistant',
    content: `已执行高权限变更。\n${JSON.stringify(result?.applied || result, null, 2).slice(0, 600)}`,
    actions: [],
    quickLinks: [],
  });
}

async function send(text?: string) {
  const message = (text ?? draft.value).trim();
  if (!message || thinking.value) return;
  draft.value = '';
  messages.value.push({ role: 'user', content: message, actions: [], quickLinks: [] });
  thinking.value = true;
  try {
    const res: any = await http.post('/agent/console/chat', {
      message,
      contextPath: route.path,
    });
    messages.value.push({
      role: 'assistant',
      content: res.content || '（无回复）',
      actions: res.actions || [],
      quickLinks: res.quickLinks || [],
    });
    if (res.actions?.[0]?.privilege === 'high') {
      ElMessage.info('检测到高权限草案，请在甄别框中核对');
    }
  } catch (e: any) {
    messages.value.push({
      role: 'assistant',
      content: `请求失败：${String(e)}`,
      actions: [],
      quickLinks: [],
    });
  } finally {
    thinking.value = false;
  }
}
</script>

<style scoped>
.agent-rail {
  display: flex;
  flex-direction: column;
  width: var(--nh-agent-width);
  max-width: 100%;
  height: 100%;
  background:
    linear-gradient(180deg, rgba(18, 40, 38, 0.98), rgba(10, 22, 21, 0.99)),
    var(--nh-agent);
  color: #e8f2ef;
  border-left: 1px solid rgba(255, 255, 255, 0.06);
  box-shadow: -16px 0 40px rgba(8, 20, 18, 0.18);
  animation: nh-fade 0.25s ease both;
}
.rail-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 18px 16px 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.rail-kicker {
  margin: 0;
  font-size: 11px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #7eb8ad;
}
.rail-head h2 {
  margin: 4px 0 0;
  font-family: var(--nh-display);
  font-size: 1.25rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}
.icon-btn {
  border: none;
  background: rgba(255, 255, 255, 0.06);
  color: #fff;
  width: 32px;
  height: 32px;
  border-radius: 10px;
  cursor: pointer;
}
.rail-hints {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 10px 12px;
}
.chip {
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  color: #cfe4df;
  border-radius: 999px;
  padding: 5px 10px;
  font-size: 12px;
  cursor: pointer;
}
.chip:hover {
  background: rgba(15, 143, 120, 0.25);
}
.rail-messages {
  flex: 1;
  overflow: auto;
  padding: 8px 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.msg {
  display: flex;
  animation: nh-rise 0.28s ease both;
}
.msg.user {
  justify-content: flex-end;
}
.bubble {
  max-width: 92%;
  border-radius: 14px;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.06);
}
.msg.user .bubble {
  background: rgba(15, 143, 120, 0.28);
  border-color: rgba(15, 143, 120, 0.35);
}
.bubble pre {
  margin: 0;
  white-space: pre-wrap;
  font-family: var(--nh-font);
  font-size: 13px;
  line-height: 1.5;
}
.thinking {
  color: #9aaeaa;
  font-size: 13px;
}
.links,
.actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 10px;
}
.link-btn,
.action-btn {
  text-align: left;
  border: none;
  border-radius: 10px;
  padding: 8px 10px;
  cursor: pointer;
  font-size: 12px;
}
.link-btn {
  background: rgba(255, 255, 255, 0.08);
  color: #d7ebe6;
}
.action-btn {
  background: linear-gradient(120deg, rgba(192, 57, 43, 0.85), rgba(196, 92, 38, 0.85));
  color: #fff;
  font-weight: 600;
}
.rail-input {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(0, 0, 0, 0.2);
}
.rail-input textarea {
  resize: none;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.05);
  color: #fff;
  padding: 10px 12px;
  font: inherit;
  font-size: 13px;
}
.rail-input textarea:focus {
  outline: none;
  border-color: rgba(15, 143, 120, 0.6);
}
.send {
  border: none;
  border-radius: 12px;
  background: var(--nh-accent);
  color: #fff;
  font-weight: 600;
  padding: 0 14px;
  cursor: pointer;
}
.send:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
