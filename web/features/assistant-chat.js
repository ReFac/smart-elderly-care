import { replyReader } from './assistant-reader.js';
import { streamReply } from './assistant-stream.js';
import { networkControl, searchSources } from './assistant-network.js';
import { el, icon } from '../lib/ui.js';
import { node } from './shared.js';
import { holdToSpeak, voiceServiceReason } from './agent-voice.js';
import { openPriorReports } from './assistants.js';
import { assistantCommand, assistantPageLinks, openAssistantAction } from './assistant-actions.js';
import { openVisitEditor } from './medical-visit-intake.js';

const path = '/api/assistant/chat';
const dayLabel = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: 'long',
  day: 'numeric',
  timeZone: 'Asia/Shanghai',
});

function control(label, glyph, className, onClick, iconOnly = false) {
  const button = el('button', className);
  button.type = 'button';
  button.append(icon(glyph, iconOnly ? 17 : 16));
  if (iconOnly) {
    button.title = label;
    button.setAttribute('aria-label', label);
  } else button.append(document.createTextNode(label));
  button.addEventListener('click', onClick);
  return button;
}

function mark(size = 18) {
  return node('span', 'assistant-mark', [icon('spark', size)]);
}

function messageBody(text) {
  const block = el('div', 'assistant-message-text');
  // Allow light typographical emphasis. The model's output always enters the DOM as text.
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue;
    const heading = /^#{1,4}\s+/.test(line);
    const bullet = /^[-*]\s+/.test(line);
    const part = el(heading ? 'h3' : 'p', bullet ? 'assistant-bullet' : '');
    for (const piece of line.replace(/^(?:#{1,4}|[-*])\s+/, '').split(/(\*\*[^*]+\*\*)/))
      part.append(
        piece.startsWith('**') && piece.endsWith('**')
          ? el('strong', '', piece.slice(2, -2))
          : document.createTextNode(piece),
      );
    block.append(part);
  }
  return block;
}

function actorSignature(ctx, scoped) {
  const membership =
    scoped || ctx.state.user.facilityScope
      ? (ctx.state.residents || []).map((r) => [r.id, r.bedId, r.status])
      : null;
  return JSON.stringify([ctx.state.user, ctx.state.uiSettings.hiddenRoutes, membership]);
}

export function chatLauncher(open) {
  const launch = control('健康助理', 'spark', 'assistant-launch', open);
  launch.id = 'assistant-launch';
  launch.setAttribute('aria-haspopup', 'dialog');
  launch.setAttribute('aria-controls', 'assistant-chat');
  launch.setAttribute('aria-expanded', String(Boolean(current && !current.panel.hidden)));
  return launch;
}

let current;
export function clearChat() {
  current?.destroy();
  current = null;
}
export function checkChatUser(ctx) {
  if (current && current.actor !== actorSignature(ctx, current.area)) clearChat();
}

// The panel lives outside the page renderer so changing business tabs does not erase a draft.
export function toggleChat(getContext) {
  if (current && !current.panel.hidden) current.hide();
  else openChat(getContext);
}

export function openChat(getContext, place = null) {
  const ctx = getContext();
  const region = Object.fromEntries(
    ['campusId', 'buildingId', 'floorId', 'roomId']
      .filter((key) => place?.[key])
      .map((key) => [key, place[key]]),
  );
  const area = new URLSearchParams(region).toString();
  const actor = actorSignature(ctx, area);
  if (current && (current.actor !== actor || current.area !== area)) clearChat();
  if (!current) current = buildChat(getContext, actor, area, region, place?.label || '');
  current.show();
}

function buildChat(getContext, actor, area, region, label) {
  const ctx = getContext();
  const panel = el('aside', 'assistant-drawer');
  panel.id = 'assistant-chat';
  panel.hidden = true;
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-labelledby', 'assistant-name');
  const name = el('h2', '', '健康助理');
  name.id = 'assistant-name';
  const scope = el('span', 'assistant-scope', label || ctx.state.uiSettings.institutionName);
  const titles = node('div', 'assistant-titles', [name, scope]);
  if (label) {
    scope.title = label;
    const resetScope = control('返回机构对话', 'undo', 'assistant-exit-scope', () =>
      openChat(getContext),
    );
    titles.append(resetScope);
  }
  const recents = control(
    '历史业务简报',
    'history',
    'assistant-icon-control',
    () => openPriorReports(getContext()),
    true,
  );
  recents.hidden = !(ctx.state.agentRuns?.length || ctx.state.suggestions?.length);
  const close = control('收起助理', 'close', 'assistant-icon-control', hide, true);
  const header = node('header', 'assistant-header', [mark(), titles, recents, close]);
  const log = el('section', 'assistant-log');
  log.setAttribute('role', 'log');
  log.setAttribute('aria-label', '对话记录');
  log.setAttribute('aria-live', 'polite');
  log.setAttribute('aria-relevant', 'additions');
  const composer = el('form', 'assistant-composer');
  composer.setAttribute('aria-label', '给助理发消息');
  const input = el('textarea', 'assistant-input');
  input.rows = 2;
  input.maxLength = 12000;
  input.placeholder = '问点什么，或按住下方说话…';
  input.setAttribute('aria-label', '消息内容');
  const send = control('发送', 'send', 'assistant-send', () => {}, true);
  send.type = 'submit';
  const note = el('p', 'assistant-status');
  note.setAttribute('role', 'status');
  const error = el('div', 'assistant-error');
  error.setAttribute('role', 'alert');
  const reader = replyReader((message) => { note.textContent = message; });
  const auto = el('input');
  auto.type = 'checkbox';
  const pref = 'assistant:auto-send:' + ctx.state.user.id;
  try {
    auto.checked = localStorage.getItem(pref) === 'yes';
  } catch {}
  auto.addEventListener('change', () => {
    try {
      localStorage.setItem(pref, auto.checked ? 'yes' : 'no');
    } catch {}
  });
  const autoLabel = node('label', 'assistant-auto', [auto, '语音转写后自动发送']);
  const keys = el('span', 'assistant-enter-hint', 'Enter 发送');
  let messages = [],
    scopeKey = '',
    generation = '',
    loaded = false,
    waiting = false,
    sending = false;
  let voicePhase = 'idle',
    request,
    retry,
    lastFocused,
    destroyed = false;
  let partial = '', partialRow, partialFrame, speechTurn;
  const requestURL = path + (area ? '?' + area : '');
  let voice;
  const network = networkControl({
    probe: (signal) =>
      json('/api/assistant/network/probe', {
        method: 'POST',
        signal,
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      }),
    changed: () => draw(),
  });
  async function json(url, options) {
    const response = await fetch(url, { cache: 'no-store', ...options });
    const data = await response.json();
    if (response.status === 401) {
      await getContext().refreshWorkspace();
      throw new Error('登录已过期，请重新登录。');
    }
    if (!response.ok)
      throw Object.assign(new Error(data.error || '暂时无法连接助理，请重试。'), {
        status: response.status,
      });
    return data;
  }
  function voiceService() {
    const state = getContext().state;
    return state.assistantVoice ?? state.agentCapabilities?.voiceInput;
  }
  voice = holdToSpeak({
    available: () => voiceServiceReason(voiceService()),
    onState(phase, text = '') {
      voicePhase = phase;
      note.textContent = text;
      sync();
    },
    upload: (blob, signal) =>
      json(voiceService().path + (area ? '?' + area : ''), {
        method: 'POST',
        signal,
        headers: { 'Content-Type': 'application/octet-stream', 'X-DeepSeek-Consent': 'yes' },
        body: blob,
      }),
    onText(result) {
      if (destroyed || panel.hidden || !result.text) return;
      input.value = [input.value.trim(), result.text.trim()].filter(Boolean).join('\n');
      adjustInput();
      if (input.value.length > input.maxLength) {
        note.textContent = '转写内容较长，请拆分后发送。';
      } else if (auto.checked) composer.requestSubmit();
      else {
        note.textContent = '已转写，可以编辑后发送。';
        input.focus();
      }
    },
  });
  const sendActions = node('div', 'assistant-send-actions', [keys, send]);
  const visit = !area && ctx.state.allowedActions?.includes('dossier.confirmVisit')
    ? control('传就诊资料', 'folder', 'assistant-visit', () => openVisitEditor(getContext()))
    : null;
  if (visit) visit.title = '上传一位长者的一组就诊图片或 PDF';
  const tools = node('div', 'assistant-compose-tools', [
    node('div', 'assistant-compose-inputs', [voice.control, visit]), sendActions,
  ]);
  const composeBox = node('div', 'assistant-compose-box', [input, tools]);
  composer.append(
    error,
    note,
    network.status,
    reader.player,
    composeBox,
    node('div', 'assistant-composer-foot', [autoLabel, reader.label, network.button]),
  );
  panel.append(header, log, composer);
  document.body.append(panel);

  function sync() {
    const blocked = !loaded || waiting || sending || network.probing;
    network.button.disabled =
      !network.enabled && !network.probing && (blocked || voicePhase !== 'idle');
    input.placeholder = network.enabled
      ? '搜索公开资料，例如河南长护险政策…'
      : '问点什么，或按住下方说话…';
    input.disabled = !loaded || waiting;
    input.readOnly = sending;
    send.disabled =
      blocked ||
      !input.value.trim() ||
      input.value.length > input.maxLength ||
      voicePhase !== 'idle';
    if (voice) voice.control.disabled = blocked;
    if (visit) visit.disabled = sending || network.probing || voicePhase !== 'idle';
  }
  function adjustInput() {
    input.style.height = 'auto';
    input.style.height = Math.min(128, Math.max(52, input.scrollHeight)) + 'px';
    sync();
  }
  function emptyState() {
    const personal = getContext().state.user.kind === 'family';
    const welcome = node('div', 'assistant-welcome', [
      mark(28),
      el('h3', '', '有什么想了解的？'),
      el(
        'p',
        '',
        label
          ? '可以从' + label + '的近况问起。'
          : personal
            ? '可以问我怎样查看照护消息和院内服务。'
            : '可以从院里的近况问起，也可以让我帮您找到办理入口。',
      ),
    ]);
    const examples = network.enabled
      ? [['globe', '查一下河南长期护理保险的公开政策']]
      : personal
        ? [
            ['heart', '在哪里查看照护消息？'],
            ['building', '在哪里查看院内环境？'],
          ]
        : label
          ? [
              ['pulse', '这里过去24小时有哪些变化？'],
              ['care', '有什么照护事项需要跟进？'],
            ]
          : [['pulse', '今天养老院情况怎么样？']];
    if (!personal && !label && getContext().available('inventory'))
      examples.push(['box', '今天的护理用具状况如何？']);
    if (!personal && !label && getContext().available('intake'))
      examples.push(['intake', '在哪里办理老人入住？']);
    const suggestions = el('div', 'assistant-starters');
    for (const [glyph, text] of examples) {
      const b = control(text, glyph, 'assistant-starter', () => transmit(text));
      b.disabled = network.probing;
      b.append(icon('chevron', 14));
      suggestions.append(b);
    }
    welcome.append(suggestions);
    return welcome;
  }
  function row(item) {
    const mine = item.role === 'user';
    const body = node('div', 'assistant-turn-body', [messageBody(item.content)]);
    const sources = searchSources(item);
    if (sources) body.append(sources);
    const links = assistantPageLinks(getContext(), item);
    if (links.length) {
      const group = el('div', 'assistant-page-links');
      group.setAttribute('role', 'group');
      group.setAttribute('aria-label', '相关页面');
      for (const link of links) {
        const button = control(
          '前往' + link.title,
          link.icon,
          'assistant-action assistant-page-link',
          () => perform({ ...link, kind: 'navigate' }, button),
        );
        button.append(icon('chevron', 14));
        group.append(button);
      }
      body.append(group);
    }
    if (!mine && !item.webSearched && ['notice', 'workOrder', 'medicationRound', 'scheduledMeal'].includes(item.action?.kind)) {
      const action = item.action;
      const trigger = control(
        action.kind === 'scheduledMeal' ? '核对伙食工单' : action.kind === 'medicationRound' ? '逐人核对服药' : action.kind === 'notice' ? '核对通知' : '核对工单',
        'file',
        'assistant-action',
        () => perform(action),
      );
      body.append(trigger);
    }
    return node(
      'article',
      'assistant-turn ' + (mine ? 'from-user' : 'from-assistant'),
      mine ? [body] : [mark(14), body],
    );
  }
  function draw(scroll = 'preserve') {
    const wasAt = log.scrollTop;
    const following = log.scrollHeight - log.clientHeight - wasAt < 32;
    const turns = document.createDocumentFragment();
    let previousDay = '';
    for (const message of messages) {
      const date = new Date(message.at);
      const day = Number.isFinite(date.getTime()) ? dayLabel.format(date) : '';
      if (day && day !== previousDay) turns.append(el('p', 'assistant-log-day', day));
      previousDay = day;
      turns.append(row(message));
    }
    log.replaceChildren(turns);
    if (!messages.length && loaded && !waiting && !sending) log.append(emptyState());
    if (sending) {
      log.append(row({ role: 'user', content: retry.text }));
      partialRow = el('div', 'assistant-current');
      partialRow.append(pendingReply());
      log.append(partialRow);
    }
    if (waiting && !messages.length) log.append(el('p', 'assistant-loading', '正在读取对话…'));
    if (scroll === 'start') log.scrollTop = 0;
    else if (following && scroll !== 'preserve') {
      const last = log.lastElementChild;
      const padding = parseFloat(getComputedStyle(log).paddingTop) || 0;
      if (
        scroll === 'answer' &&
        last?.classList.contains('from-assistant') &&
        last.offsetHeight > log.clientHeight - 2 * padding
      ) {
        const question = last.previousElementSibling;
        const first =
          question?.classList.contains('from-user') &&
          question.offsetHeight < Math.min(70, log.clientHeight / 5)
            ? question
            : last;
        log.scrollTop +=
          first.getBoundingClientRect().top - log.getBoundingClientRect().top - padding;
      } else log.scrollTop = log.scrollHeight;
    } else log.scrollTop = wasAt;
    sync();
  }
  function pendingReply() {
    return partial ? row({ role: 'assistant', content: partial }) : node('div', 'assistant-waiting', [
      mark(14), retry.webSearch ? '正在查阅公开资料…' : '正在整理回答…',
    ]);
  }
  function appendText(text) {
    partial += text;
    if (partialFrame) return;
    partialFrame = requestAnimationFrame(() => {
      partialFrame = 0;
      if (!sending || !partialRow?.isConnected) return;
      const follows = log.scrollHeight - log.clientHeight - log.scrollTop < 32;
      partialRow.replaceChildren(pendingReply());
      if (follows) log.scrollTop = log.scrollHeight;
    });
  }
  function update(result, sent = false) {
    const next = result.generation || '';
    if (loaded && (scopeKey !== result.scopeKey || (generation !== next && !(sent && !generation))))
      network.reset();
    messages = result.messages;
    scopeKey = result.scopeKey;
    generation = next;
    loaded = true;
  }
  function problem(message, callback, label = '重试') {
    error.replaceChildren(el('span', '', message));
    if (callback) error.append(control(label, 'undo', 'assistant-retry', callback));
  }
  async function load() {
    waiting = true;
    const before = messages.at(-1);
    error.replaceChildren();
    draw();
    request = new AbortController();
    try {
      const result = await json(requestURL, { signal: request.signal });
      if (!destroyed) update(result);
    } catch (e) {
      if (!destroyed) {
        loaded = false;
        messages = [];
        problem(e.message, load);
      }
    } finally {
      if (!destroyed) {
        waiting = false;
        const latest = messages.at(-1);
        const changed = !before || before.at !== latest?.at || before.content !== latest?.content;
        draw(changed ? 'answer' : 'preserve');
        if (loaded && !panel.hidden && document.activeElement === close)
          input.focus({ preventScroll: true });
      }
    }
  }
  async function reloadConflict(message) {
    network.reset();
    loaded = false;
    messages = [];
    scopeKey = '';
    retry = null;
    await load();
    if (!destroyed && loaded) problem(message);
  }
  function hide(keepPlayback = false) {
    if (keepPlayback !== true) {
      reader.stop();
      speechTurn = null;
    }
    if (network.probing) network.reset();
    panel.hidden = true;
    voice.cancel();
    const launch = document.getElementById('assistant-launch');
    launch?.setAttribute('aria-expanded', 'false');
    (lastFocused?.isConnected ? lastFocused : launch)?.focus({ preventScroll: true });
  }
  let openingAction = false;
  async function perform(action, button) {
    if (openingAction) return;
    openingAction = true;
    if (button) {
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
    }
    try {
      if (!(await getContext().refreshWorkspace()) || destroyed || panel.hidden) return;
      hide(true);
      await openAssistantAction(getContext(), action);
    } catch (e) {
      if (!destroyed) getContext().toast(e.message);
    } finally {
      openingAction = false;
      if (button) {
        button.disabled = false;
        button.removeAttribute('aria-busy');
      }
    }
  }
  async function transmit(raw) {
    const text = raw.trim();
    if (
      !loaded ||
      waiting ||
      sending ||
      network.probing ||
      voicePhase !== 'idle' ||
      !text ||
      text.length > input.maxLength
    )
      return;
    const startPage = location.hash;
    const page = startPage.slice(1).split('?')[0] || 'overview';
    if (!retry || retry.text !== text || retry.page !== page || retry.webSearch !== network.enabled)
      retry = { text, page, id: crypto.randomUUID(), webSearch: network.enabled };
    sending = true;
    reader.stop();
    partial = '';
    speechTurn = null;
    network.status.textContent = '';
    input.value = '';
    note.textContent = '';
    error.replaceChildren();
    adjustInput();
    draw('pending');
    request = new AbortController();
    let action,
      received = false,
      speechFrames = false;
    try {
      const speechRequested = reader.enabled;
      const result = await streamReply(path + '/stream', {
        text,
        requestId: retry.id,
        ...(retry.webSearch ? { webSearch: true } : {}),
        page: retry.page,
        region,
        scopeKey,
        generation,
        readAloud: speechRequested,
      }, request.signal, event => {
        if (destroyed) return;
        if (event.type === 'begin' && !panel.hidden && speechRequested)
          speechTurn = { region, scopeKey: event.scopeKey, generation: event.generation, requestId: event.requestId };
        if (event.type === 'text' && typeof event.text === 'string') appendText(event.text);
        if (event.type === 'speech' && Number.isInteger(event.sentence)) {
          speechFrames = true;
          if (!panel.hidden && speechTurn) reader.enqueueSentence(event.sentence, speechTurn);
        }
      });
      if (destroyed) return;
      update(result, true);
      received = true;
      if (!panel.hidden && !speechFrames)
        reader.enqueue(messages.at(-1), {region, scopeKey, generation});
      if (
        messages.at(-2)?.content === text &&
        startPage === location.hash
      )
        action = assistantCommand(getContext(), messages.at(-1));
      retry = null;
    } catch (e) {
      if (destroyed) return;
      reader.stop();
      if (!input.value) input.value = text;
      if (e.status === 401) {
        await getContext().refreshWorkspace();
        if (!destroyed) problem('登录已过期，请重新登录。');
      } else if (e.status === 409) {
        sending = false;
        await reloadConflict('对话或权限已变化，已重新读取，请核对后发送。');
      } else if (e.status === 403) {
        network.reset();
        loaded = false;
        scopeKey = '';
        messages = [];
        retry = null;
        problem(e.message, load, '重新读取');
      } else {
        if (e.status === 503) retry = null;
        try {
          const latest = await json(requestURL, { signal: request.signal });
          if (destroyed) return;
          if (latest.scopeKey !== scopeKey) {
            network.reset();
            loaded = false;
            messages = [];
            retry = null;
            problem('当前可查看的区域已变化，请重新打开对话。', load, '重新读取');
            return;
          }
          update(latest);
        } catch {
          /* Keep the draft when reconnecting is also unavailable. */
        }
        if (!destroyed) problem(e.message);
      }
    } finally {
      if (!destroyed) {
        cancelAnimationFrame(partialFrame);
        partialFrame = 0;
        partial = '';
        speechTurn = null;
        sending = false;
        draw(received ? 'answer' : 'preserve');
        adjustInput();
      }
    }
    if (!destroyed && !panel.hidden && action && !document.querySelector('dialog[open]'))
      perform(action);
  }
  composer.addEventListener('submit', (event) => {
    event.preventDefault();
    transmit(input.value);
  });
  input.addEventListener('input', adjustInput);
  let composing = false;
  input.addEventListener('compositionstart', () => {
    composing = true;
  });
  input.addEventListener('compositionend', () => {
    composing = false;
  });
  input.addEventListener('keydown', (event) => {
    if (
      event.key !== 'Enter' ||
      event.shiftKey ||
      event.isComposing ||
      composing ||
      event.keyCode === 229
    )
      return;
    event.preventDefault();
    if (!event.repeat && !send.disabled) composer.requestSubmit();
  });
  panel.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !event.isComposing && !composing) {
      event.preventDefault();
      event.stopPropagation();
      hide();
    }
  });
  function loseWindow() {
    if (voicePhase === 'starting' || voicePhase === 'recording') voice.cancel();
  }
  window.addEventListener('blur', loseWindow);
  return {
    panel,
    actor,
    area,
    hide,
    show() {
      if (!panel.hidden) {
        if (!input.disabled) input.focus();
        return;
      }
      lastFocused = document.activeElement;
      panel.hidden = false;
      document.getElementById('assistant-launch')?.setAttribute('aria-expanded', 'true');
      if (!sending && !waiting) load();
      if (loaded && !waiting) input.focus({ preventScroll: true });
      else close.focus({ preventScroll: true });
    },
    destroy() {
      destroyed = true;
      reader.stop();
      voice.cancel();
      network.reset();
      request?.abort();
      window.removeEventListener('blur', loseWindow);
      panel.remove();
      document.getElementById('assistant-launch')?.setAttribute('aria-expanded', 'false');
    },
  };
}
