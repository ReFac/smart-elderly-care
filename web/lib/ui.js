export function el(tag, className = '', text = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== '' && text != null) node.textContent = String(text);
  return node;
}

const paths = {
  grid: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  home: 'm3 10 9-7 9 7v10h-6v-6H9v6H3z',
  intake: 'M13 20H4v-3c0-3 3-5 7-5 M8 4a3.5 3.5 0 1 0 3.5 6A3.5 3.5 0 0 0 8 4 M18 11v8m-4-4h8',
  people:
    'M15 20v-2c0-3-3-5-6-5s-6 2-6 5v2m6-16a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7m7 0a3.5 3.5 0 0 1 0 7m2 3c2 0 3.5 2 3.5 4v2',
  file: 'M5 3h10l4 4v14H5z M14 3v5h5 M8 13h8m-8 4h6',
  assessment: 'M8 5H5v16h14V5h-3 M9 3h6v4H9z M8 13l2 2 5-5',
  care: 'M6 5h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2 M8 3v4m8-4v4 M7 14h3l2-4 2 7 2-3h2',
  pill: 'm4 12 8-8a5.65 5.65 0 0 1 8 8l-8 8a5.65 5.65 0 0 1-8-8z M8 8l8 8',
  bed: 'M3 4v16m18-9v9 M3 16h18 M6 12V8h3a2 2 0 0 1 2 2v2z M12 12V8h6a3 3 0 0 1 3 3v1z',
  box: 'm3 7 9-5 9 5-9 5z M3 7v10l9 5 9-5V7m-9 5v10m-5-17 9 5',
  wallet: 'M20 7H4V5l13-3v5 M4 7h16v13H4z M20 11h-5v5h5 M17 13.5h.1',
  shifts: 'M3 6h18v15H3z M7 3v6m10-6v6 M3 11h18m-13 4h2m3 0h2',
  reports: 'M4 3v17h17 M8 16v-5m5 5V7m5 9v-7',
  globe: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z M3 12h18 M12 3c2.3 2.6 3.5 5.6 3.5 9s-1.2 6.4-3.5 9c-2.3-2.6-3.5-5.6-3.5-9s1.2-6.4 3.5-9z',
  spark: 'm12 2 2.4 7.6L22 12l-7.6 2.4L12 22l-2.4-7.6L2 12l7.6-2.4z M20 2v4m-2-2h4',
  speaker: 'M3 9h4l5-4v14l-5-4H3z M15 8a6 6 0 0 1 0 8 M18 5a10 10 0 0 1 0 14',
  mic: 'M9 7a3 3 0 0 1 6 0v5a3 3 0 0 1-6 0z M5 11v1a7 7 0 0 0 14 0v-1 M12 19v3m-3 0h6',
  keyboard: 'M2 5h20v14H2z M5 9h1m3 0h1m3 0h1m3 0h1 M5 12h1m3 0h1m3 0h1m3 0h1 M8 15h8',
  send: 'm12 20 0-16m-7 7 7-7 7 7',
  calendar: 'M3 6h18v15H3z M7 3v6m10-6v6 M3 11h18',
  search: 'M10.5 3a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15 M16 16l5 5',
  bell: 'M4 17h16l-2-3V9a6 6 0 0 0-12 0v5z M10 20a2.5 2.5 0 0 0 4 0',
  menu: 'M3 6h18M3 12h18M3 18h18',
  close: 'm5 5 14 14M19 5 5 19',
  chevron: 'm9 5 7 7-7 7',
  down: 'm6 9 6 6 6-6',
  plus: 'M12 5v14M5 12h14',
  building: 'M4 21V5h11v16m0-13h5v13M2 21h20 M7 9h1m3 0h1m-5 4h1m3 0h1m-3 8v-4h3v4',
  location: 'M12 22S4 14 4 9a8 8 0 1 1 16 0c0 5-8 13-8 13z M12 6a3 3 0 1 0 0 6 3 3 0 0 0 0-6',
  history: 'M3 11a9 9 0 1 1 2.6 7M3 4v7h7m2-4v5l3 2',
  undo: 'M3 4v7h7M4 10a8 8 0 1 1 2 9',
  clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7v5l3 2',
  check: 'm4 12 5 5L20 6',
  pulse: 'M2 13h5l3-9 4 16 3-9 2 2h3',
  heart: 'M12 20 4.4 12.5a5.3 5.3 0 0 1 7.6-7.3 5.3 5.3 0 0 1 7.6 7.3z',
  list: 'M9 6h12M9 12h12M9 18h12 M3 6h1m-1 6h1m-1 6h1',
  flag: 'M4 21V4c6-4 10 4 16 0v10c-6 4-10-4-16 0',
  trend: 'm3 17 6-6 4 4 8-9m-6 0h6v6',
  chart: 'M3 4v16h18 M6 15l5-5 4 3 5-7',
  layers: 'm3 7 9-5 9 5-9 5z M3 12l9 5 9-5 M3 17l9 5 9-5',
  folder: 'M3 6h7l2 2h9v12H3z',
  leaf: 'M20 3c0 12-3 17-10 17a6 6 0 0 1-6-6C4 7 12 7 20 3z M4 21l10-11',
  info: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 11v6m0-10v.8',
  shield: 'm12 2 8 3v6c0 5-4 9-8 11-4-2-8-6-8-11V5z M8 11l3 3 5-6',
};

export function icon(name, size = 18) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  for (const [key, value] of Object.entries({
    viewBox: '0 0 24 24',
    width: size,
    height: size,
    fill: 'none',
    stroke: 'currentColor',
    'stroke-width': 1.65,
    'stroke-linecap': 'round',
    'stroke-linejoin': 'round',
    'aria-hidden': true,
    focusable: false,
  }))
    svg.setAttribute(key, value);
  const path = document.createElementNS(ns, 'path');
  path.setAttribute('d', paths[name] || paths.file);
  svg.append(path);
  return svg;
}

export function button(label, onClick, variant = 'secondary', iconName) {
  const b = el('button', 'btn btn-' + variant);
  b.type = 'button';
  if (iconName) b.append(icon(iconName, 16));
  b.append(document.createTextNode(label));
  b.addEventListener('click', onClick);
  return b;
}
export function badge(text, tone = 'neutral') {
  return el('span', 'badge badge-' + tone, text);
}
export function heading(title, description = '', action) {
  const header = el('header', 'page-heading');
  const block = el('div');
  block.append(el('h1', '', title));
  if (description) block.append(el('p', 'muted', description));
  header.append(block);
  if (action) header.append(action);
  return header;
}
export function empty(message) {
  const node = el('div', 'empty');
  node.append(icon('folder', 24), el('p', '', message));
  return node;
}
export function cardTitle(title, action) {
  const row = el('div', 'card-title');
  row.append(el('h2', '', title));
  if (action) row.append(action);
  return row;
}
export function toast(message) {
  const node = document.getElementById('announcer');
  node.textContent = message;
  node.classList.add('visible');
  clearTimeout(toast.timeout);
  toast.timeout = setTimeout(() => node.classList.remove('visible'), 4800);
}
