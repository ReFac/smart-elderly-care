import { node } from './shared.js';

const base = '/api/facility';
export const lookup = (ctx, path, params = {}) => {
  const query = new URLSearchParams(Object.entries(params).filter(([, value]) => value !== ''));
  return ctx.get(base + path + (query.size ? '?' + query : ''));
};

export function button(label, handler, className = '', content) {
  const item = node('button', className, content || label);
  item.type = 'button';
  item.setAttribute('aria-label', label);
  item.addEventListener('click', handler);
  return item;
}

export function heading(ctx, icon, title, aside) {
  return node('div', 'room-card-head', [node('h2', '', [ctx.ui.icon(icon, 18), title]), aside]);
}

export function statusText(message, error = false) {
  const line = node('p', 'room-status' + (error ? ' error' : ''), message);
  line.setAttribute('role', error ? 'alert' : 'status');
  return line;
}

export function failure(ctx, host, error, retry) {
  host.replaceChildren(statusText(error.message || '读取失败', true), ctx.ui.button('重试', retry));
}

export function pathName(...parts) {
  return parts.filter(Boolean).join(' / ');
}
