import { el, icon } from '../lib/ui.js';

export function networkControl({ probe, changed }) {
  const button = el('button', 'assistant-network');
  button.type = 'button';
  button.setAttribute('aria-label', '联网搜索');
  const avatar = el('span', 'assistant-mark assistant-network-avatar');
  avatar.append(icon('spark', 15));
  const label = el('span');
  button.append(avatar, label);
  const status = el('p', 'assistant-status assistant-network-status');
  status.setAttribute('role', 'status');
  let enabled = false;
  let pending;

  function paint() {
    button.setAttribute('aria-pressed', String(enabled));
    button.setAttribute('aria-busy', String(Boolean(pending)));
    label.textContent = pending ? '连接中…' : enabled ? '已联网' : '联网搜索';
    button.title = pending ? '取消连接测试' : enabled ? '关闭联网搜索' : '连接并启用联网搜索';
  }
  function reset() {
    pending?.abort();
    pending = null;
    enabled = false;
    status.textContent = '';
    paint();
  }
  button.addEventListener('click', async () => {
    if (enabled || pending) {
      reset();
      changed();
      return;
    }
    const controller = new AbortController();
    pending = controller;
    status.textContent = '正在测试搜索服务连接…';
    paint();
    changed();
    try {
      const result = await probe(controller.signal);
      if (controller.signal.aborted) return;
      if (result?.connected !== true) throw new Error('搜索服务未连接，请重试。');
      enabled = true;
      status.textContent = '已连接，可查养老运营、长护险、照护和相关医疗的公开资料。';
    } catch (error) {
      if (controller.signal.aborted) return;
      status.textContent = error.status
        ? error.message
        : '搜索服务连接失败，点击「联网搜索」可重试。';
    } finally {
      if (pending === controller) {
        pending = null;
        paint();
        changed();
      }
    }
  });
  paint();
  return {
    button,
    status,
    reset,
    get enabled() {
      return enabled;
    },
    get probing() {
      return Boolean(pending);
    },
  };
}

// Search results are shown as text and deliberate external links. Never embed remote previews.
function publicLink(value) {
  if (
    typeof value !== 'string' ||
    value.length > 2048 ||
    !/^https?:\/\//i.test(value) ||
    /[\s\\\p{C}]/u.test(value)
  )
    return null;
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase().replace(/\.$/, '');
    if (
      url.origin === location.origin ||
      !host.includes('.') ||
      host.startsWith('[') ||
      /^\d+(?:\.\d+){3}$/.test(host) ||
      /(?:^|\.)(?:localhost|local|internal|lan|home|test|invalid)$/.test(host) ||
      host.endsWith('.home.arpa') ||
      url.port === '0' ||
      url.username ||
      url.password
    )
      return null;
    return url;
  } catch {
    return null;
  }
}

export function searchSources(message) {
  if (message?.role !== 'assistant' || message.webSearched !== true) return null;
  const panel = el('section', 'assistant-sources');
  panel.setAttribute('aria-label', '联网搜索来源');
  const list = el('ol');
  const urls = new Set();
  const sources = Array.isArray(message.sources) ? message.sources : [];
  for (const [index, item] of sources.entries()) {
    const url = publicLink(item?.url);
    if (!url || urls.has(url.href)) continue;
    urls.add(url.href);
    const link = el('a', 'assistant-source-link');
    link.href = url.href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.referrerPolicy = 'no-referrer';
    const title = typeof item.title === 'string' && item.title.trim();
    link.append(el('span', '', title || url.hostname), el('small', '', url.hostname));
    const row = el('li');
    row.value = index + 1; // Preserve the numbers cited in the answer.
    row.append(link);
    list.append(row);
  }
  const heading = el('p', 'assistant-source-label');
  heading.append(
    icon('globe', 14),
    document.createTextNode(
      list.childElementCount ? '已联网搜索 · 网页来源' : '已联网搜索 · 暂无可列出的来源',
    ),
  );
  panel.append(heading);
  if (list.childElementCount) panel.append(list);
  return panel;
}
