import { node } from './shared.js';

import { internationalDeployment } from '../lib/international-profile.js';
const copy = (en, zh) => internationalDeployment() ? en : zh;
const publicTerm = term => term.trim().length >= 2 && term.trim().length <= 80 &&
  !/\d{7}|[\r\n\t@:/\\<>?=&%#]|身份证|手机号|床号|病历号|patient\s*(id|number)/i.test(term);

function link(label, url, cls = '') {
  const a = node('a', cls, label);
  a.href = url;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  a.referrerPolicy = 'no-referrer';
  return a;
}

function mapLink(label, term, placeId) {
  if (internationalDeployment()) {
    const params = new URLSearchParams({api: '1', query: term});
    if (placeId) params.set('query_place_id', placeId);
    return link(label, 'https://www.google.com/maps/search/?' + params, 'hospital-map-link');
  }
  return link(label, 'https://uri.amap.com/search?' + new URLSearchParams({keyword: term, view: 'map'}), 'hospital-map-link');
}

export function hospitalMapLink(facility) {
  if (typeof facility !== 'string' || !publicTerm(facility)) return null;
  return mapLink(copy('View hospital in Google Maps', '在高德地图查看医院'), facility.trim());
}

export function mapDirectory() {
  const box = node('details', 'medical-map-directory');
  const summary = node('summary', '', copy('Look up a hospital worldwide', '联网核对医院'));
  const input = node('input');
  input.type = 'search';
  input.autocomplete = 'off';
  input.maxLength = 80;
  input.setAttribute('aria-label', copy('Hospital name or city for map search', '发送至地图服务的医院或城市名'));
  input.placeholder = copy('Hospital name and city', '医院名称、城市');
  const button = node('button', 'btn btn-secondary', copy('Search Google Maps', '查询高德地图'));
  button.type = 'button';
  const action = node('div', 'medical-map-actions');
  const note = node('small', 'fx-muted', copy(
    'Only this search term is sent. Enter the hospital on the record as printed on the original.',
    '仅发送此处的医院或城市名称。请按就诊原件核对并填写机构名。'));
  const status = node('div', 'medical-map-status');
  status.setAttribute('role', 'status');
  const results = node('ul', 'medical-map-results');
  let sequence = 0;
  function reset() {
    sequence++;
    const query = input.value.trim();
    button.disabled = !publicTerm(query);
    action.replaceChildren(button);
    if (!button.disabled) action.append(mapLink(copy('Open Google Maps', '打开高德地图'), query));
    status.replaceChildren();
    results.replaceChildren();
  }
  async function search() {
    const query = input.value.trim();
    if (!publicTerm(query)) return;
    const ticket = ++sequence;
    button.disabled = true;
    results.replaceChildren();
    status.textContent = copy('Searching…', '正在查询…');
    try {
      const response = await fetch('/api/catalog/hospitals/online', {
        method: 'POST', credentials: 'same-origin', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({q:query}),
      });
      if (!response.ok) throw new Error('Map request failed');
      const data = await response.json();
      if (ticket !== sequence || !box.isConnected) return;
      if (data.status === 'not-configured') {
        status.textContent = copy('Open Google Maps above to search directly.', '可点击「打开高德地图」直接查找。');
      } else if (data.status !== 'ok') throw new Error('Directory unavailable');
      else if (!data.options.length) status.textContent = copy('No matching hospitals. Try adding a city.', '未找到医院，可加上城市名再次查询。');
      else {
        if (internationalDeployment()) {
          const logo = node('img', 'medical-map-attribution');
          logo.src = '/assets/google-maps-attribution.png';
          logo.alt = 'Google Maps';
          status.replaceChildren(logo);
        } else status.textContent = '地图信息由高德地图提供';
        results.replaceChildren(...data.options.map(place => {
          const item = node('li', '', [mapLink(place.name, place.name, place.placeId),
            node('small', 'fx-muted', place.locality)]);
          for (const credit of place.credits || []) item.append(
            credit.url?.startsWith('https://') ? link(credit.name, credit.url) : node('small', '', credit.name));
          return item;
        }));
      }
    } catch {
      if (ticket === sequence) status.textContent = copy(
        'Online lookup is unavailable. You can still enter the hospital from the original.',
        '在线查询暂不可用，仍可按原件手动填写。');
    } finally {
      if (ticket === sequence) button.disabled = false;
    }
  }
  input.addEventListener('input', reset);
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.isComposing) {
      event.preventDefault();
      if (!button.disabled) search();
    }
  });
  button.addEventListener('click', search);
  box.addEventListener('toggle', () => {if (!box.open) reset();});
  box.append(summary, input, note, action, status, results);
  reset();
  return box;
}
