import { el, icon } from '../lib/ui.js';

let catalog;

function loadCatalog() {
  if (!catalog) {
    catalog = fetch('/api/public/faq', { cache: 'no-store' }).then(async response => {
      if (!response.ok) throw new Error('无法打开常见问题');
      return (await response.json()).items;
    }).catch(error => {
      catalog = undefined;
      throw error;
    });
  }
  return catalog;
}

function anchor(text, href) {
  const link = el('a', 'faq-link', text);
  link.href = href;
  return link;
}

function question(item, opened) {
  const entry = el('details', 'faq-entry');
  entry.id = 'faq-' + item.id;
  entry.open = opened;
  const title = el('summary', 'faq-question');
  title.append(el('span', '', item.question), icon('chevron', 16));
  entry.append(title, el('p', 'faq-answer', item.answer));
  return entry;
}

function notes(parent, items, initial, field) {
  const totals = new Map();
  for (const item of items) totals.set(item.category, (totals.get(item.category) || 0) + 1);
  const categories = [...totals.keys()];
  const selection = items.find(item => item.id === initial);
  let active = selection?.category || '';
  const filters = el('nav', 'faq-filters');
  filters.setAttribute('aria-label', '问题分类');
  const area = el('section', 'faq-results');
  area.setAttribute('aria-label', '问题列表');
  const heading = el('div', 'faq-result-head');
  const title = el('h2');
  const count = el('p', 'faq-count');
  count.setAttribute('role', 'status');
  const results = el('div', 'faq-items');
  heading.append(title, count);
  area.append(heading, results);
  parent.replaceChildren(filters, area);
  const choices = new Map(['', ...categories].map(category => {
    const button = el('button', 'faq-filter', category || '全部问题');
    button.type = 'button';
    const count = el('small', '', totals.get(category) || items.length);
    count.setAttribute('aria-hidden','true');
    button.append(count);
    button.addEventListener('click', () => {
      active = category;
      display();
    });
    filters.append(button);
    return [category, button];
  }));

  function display() {
    const query = field.value.trim().normalize('NFKC').toLowerCase();
    const words = query.split(/\s+/).filter(Boolean);
    const found = items.filter(item => {
      const text = [item.question, item.answer, ...item.keywords].join(' ').normalize('NFKC').toLowerCase();
      return (!active || item.category === active) && words.every(word => text.includes(word));
    });
    for (const [category, button] of choices) button.setAttribute('aria-pressed', String(active === category));
    title.textContent = active || '全部问题';
    count.textContent = `共 ${found.length} 条`;
    results.replaceChildren(...found.map(item => question(item, item.id === initial)));
    if (!found.length) results.append(el('p', 'faq-state', '没有匹配的问题，请试试其他关键词或分类。'));
  }
  field.addEventListener('input', () => {
    active = '';
    display();
  });
  display();
}

export function faqDirectory({ initial = '', standalone = false } = {}) {
  const page = el('section', 'faq-directory');
  const banner = el('header', 'faq-banner');
  banner.append(el('h1', '', '常见问题'), el('p', '', '查找来访、入住、照护和平台操作的常见问题。'));
  if (!standalone) banner.append(anchor('打开公开常见问题', '/faq'));
  const search = el('label', 'faq-search');
  const field = el('input');
  field.type = 'search';
  field.placeholder = '搜索常见问题';
  field.setAttribute('aria-label', '搜索常见问题');
  search.append(icon('search'), field);
  banner.append(search);
  const body = el('div', 'faq-layout');
  page.append(banner, body);

  async function load() {
    body.replaceChildren(el('p', 'faq-state', '正在加载常见问题…'));
    field.disabled = true;
    try {
      notes(body, await loadCatalog(), initial, field);
      field.disabled = false;
    } catch {
      const retry = el('button', 'faq-filter', '重新加载');
      retry.type = 'button';
      retry.addEventListener('click', load);
      const state = el('p', 'faq-state', '常见问题暂时无法加载。');
      state.append(retry);
      body.replaceChildren(state);
    }
  }
  void load();
  return page;
}

export function renderFaqPage() {
  const initial = new URLSearchParams(location.hash.split('?')[1]).get('item');
  return faqDirectory({ initial });
}
