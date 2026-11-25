import { node, residentName } from './shared.js';

export function evaluationHeader(ctx, residentId, metadata, tags, attention = []) {
  const person = ctx.state.residents?.find(row => row.id === residentId);
  const bed = person?.bedId && ctx.state.beds?.find(item => item.id === person.bedId);
  const location = ctx.state.bedDirectory?.[person?.bedId] || {};
  const currentBed = [location.buildingName, location.floorLabel, bed?.label].filter(Boolean).join(' · ');
  return node('header', 'evaluation-person', [
    node('span', 'evaluation-avatar', person?.name?.slice(0, 1) || '档'),
    node('div', 'evaluation-identity', [
      node('div', 'evaluation-name', [node('strong', '', residentName(ctx, residentId)),
        ...[person?.sex || person?.gender, ...tags].filter(Boolean).map(tag => node('span','',tag))]),
      currentBed ? node('small', '', currentBed) : null,
      node('small', '', metadata.filter(Boolean).join('　')),
    ]),
    attention.length ? node('div', 'evaluation-tags', [node('small', '', '评估关注'),
      ...attention.map(tag => node('span', '', tag))]) : null,
  ]);
}

export function evaluationResult({ title, topic, finding, score, maximum, lastScore, tone = 'neutral', bands = [] }) {
  const result = node('section', 'risk-result', [
    node('div', '', [
      node('div', 'evaluation-grade', [node('h2', '', title), topic ? node('span', '', topic) : null]),
      finding ? node('p', '', finding) : null,
      bands.length ? node('ul','evaluation-bands', bands.map(band => {
        const range = band.max == null ? band.min + '+' : band.min + '–' + band.max;
        const item = node('li','', band.level + ' ' + range);
        item.dataset.level = band.level;
        if (band.level === title) item.setAttribute('aria-current','true');
        return item;
      })) : null,
    ]),
    node('div', 'risk-score', [
      node('strong', '', score ?? '—'),
      node('small', '', score == null ? '未登记分值' : maximum == null ? '原表总分' : '总得分 / ' + maximum),
      lastScore != null ? node('small', '', '上次 ' + lastScore + ' 分') : null,
    ]),
  ]);
  result.dataset.tone = tone;
  return result;
}

// When the source has no dimension maximum, show absolute scores against a common axis.
export function evaluationBars(rows, maximum) {
  const axis = Math.max(1, ...rows.map(([, value]) => value));
  return node('dl', 'evaluation-bars', rows.map(([label, value]) => {
    const max = maximum?.[label];
    const strip = node('div', 'evaluation-track');
    strip.setAttribute('aria-hidden', 'true');
    const fill = node('span');
    fill.style.width = Math.min(100, value / (max || axis) * 100) + '%';
    strip.append(fill);
    return node('div', '', [
      node('dt', '', label),
      node('dd', '', [max == null ? value + ' 分' : value + ' / ' + max + ' 分', strip]),
    ]);
  }));
}
