import { node } from './shared.js';
import { bounds, comparison, metricsSource, periods } from './business-metrics.js';

const metrics = [
  ['census', '在院人数', '人', 'residents'],
  ['served', '服务人数', '人', 'care'],
  ['visits', '服务人次', '次', 'care'],
  ['admissions', '新入住', '人', 'residents'],
  ['discharges', '退住', '人', 'residents'],
  ['gross', '总收入', '元', 'billing'],
  ['perCapita', '人均收入', '元', 'billing'],
];
const colors = ['#5eb6ff', '#9472fa', '#ffc25c', '#4dd8b0', '#e873aa', '#5bd5f1', '#a7c7ea'];
const number = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 });
const pct = (n, total) => (total ? number.format((100 * n) / total) + '%' : '—');
const fmt = (n) => (n == null ? '—' : number.format(n));
const compact = (n) => (n != null && Math.abs(n) >= 10000 ? [fmt(n / 10000), '万'] : [fmt(n), '']);
const colorsAt = (i) => colors[i % colors.length];
function action(text, fn, cls = '') {
  const b = node('button', cls, text);
  b.type = 'button';
  b.onclick = fn;
  return b;
}
function card(title, ...children) {
  return node('section', 'biz-card', [node('h2', '', title), ...children]);
}
function count(rows, key) {
  const m = new Map();
  for (const row of rows) {
    const v = key(row);
    m.set(v, (m.get(v) || 0) + 1);
  }
  return m;
}
function progress(rows, total, percentOnly = false) {
  if (!rows.length) return node('p', 'biz-empty', '本期暂无记录');
  return node(
    'div',
    'biz-bars',
    rows.map(([text, value], i) => {
      const meter = node('i');
      meter.style.width = (total ? (100 * value) / total : 0) + '%';
      meter.style.backgroundColor = colorsAt(i);
      return node('div', 'biz-bar', [
        node('span', '', text),
        node('div', '', meter),
        node('span', '', percentOnly ? pct(value, total) : value + ' · ' + pct(value, total)),
      ]);
    }),
  );
}
function ring(rows, total, center, formatter) {
  let fraction = 0;
  const stops = rows.map(([, v], i) => {
    const a = fraction;
    fraction += total ? (v * 100) / total : 0;
    return colorsAt(i) + ' ' + a + '% ' + fraction + '%';
  });
  const dial = node('div', 'biz-ring', node('strong', '', center));
  if (total && stops.length) dial.style.background = 'conic-gradient(' + stops.join(',') + ')';
  return node('div', 'biz-pie', [
    dial,
    node(
      'div',
      'biz-key',
      rows.map(([text, value], i) => {
        const dot = node('i');
        dot.style.background = colorsAt(i);
        return node('div', '', [
          dot,
          node('span', '', text),
          node('b', '', formatter(value)),
          node('small', '', pct(value, total)),
        ]);
      }),
    ),
  ]);
}
function chart(samples, metric, color, unit, breakdown) {
  const ns = 'http://www.w3.org/2000/svg';
  function elem(tag, attrs) {
    const e = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
    return e;
  }
  const svg = elem('svg', {
    viewBox: '0 0 270 110',
    role: 'img',
    'aria-label': samples.map((r) => r.label + ' ' + fmt(r[metric]) + unit).join('，'),
  });
  const vals = samples.map((r) => r[metric] ?? 0);
  const top = Math.max(1, ...vals),
    bar = Math.min(14, 180 / Math.max(1, samples.length));
  const x = (i) => (samples.length === 1 ? 135 : 12 + (i * 244) / (samples.length - 1)),
    y = (v) => 87 - (v / top) * 66;
  for (const pos of [22, 54, 87])
    svg.append(
      elem('line', { x1: 6, x2: 264, y1: pos, y2: pos, stroke: '#31415e', 'stroke-dasharray': '2 3' }),
    );
  vals.forEach((v, i) => {
    let cumulative = 0;
    const segments = breakdown
      ? breakdown.categories.map(([name], index) => ({
          name,
          value: breakdown.rows[i].get(name) || 0,
          fill: colorsAt(index),
        }))
      : [{ name: '', value: v, fill: color }];
    for (const segment of segments) {
      if (!segment.value) continue;
      const bottom = y(cumulative);
      cumulative += segment.value;
      const p = elem('rect', {
        x: x(i) - bar / 2,
        y: y(cumulative),
        width: bar,
        height: Math.max(0, bottom - y(cumulative)),
        rx: 1,
        fill: segment.fill,
        opacity: breakdown ? '.9' : '.54',
      });
      const t = elem('title', {});
      t.textContent = [samples[i].label, segment.name, fmt(segment.value) + unit].filter(Boolean).join(' · ');
      p.append(t);
      svg.append(p);
    }
  });
  svg.append(
    elem('polyline', {
      fill: 'none',
      stroke: color,
      'stroke-width': 2.25,
      points: vals.map((v, i) => x(i) + ',' + y(v)).join(' '),
    }),
  );
  vals.forEach((v, i) => {
    svg.append(elem('circle', { cx: x(i), cy: y(v), r: 2.3, fill: color }));
    if (samples.length <= 6 || i === samples.length - 1 || i % 2 === 0) {
      const t = elem('text', { x: x(i), y: 104, fill: '#afc1df', 'font-size': 9, 'text-anchor': 'middle' });
      t.textContent = samples[i].label;
      svg.append(t);
    }
  });
  return svg;
}
function summariseChange(a, b, unit) {
  if (a == null || b == null) return '基期数据不足';
  if (!b) return a === 0 ? '与基期持平' : '基期为零 · 新增 ' + fmt(a) + unit;
  const delta = ((a - b) / Math.abs(b)) * 100;
  return delta === 0 ? '与基期持平' : (delta > 0 ? '▲ +' : '▼ ') + fmt(delta) + '%';
}
function stats(items) {
  return node(
    'div',
    'biz-inline',
    items.map(([label, val]) => node('div', '', [node('strong', '', val), node('small', '', label)])),
  );
}
function details(ctx, title, rows, columns) {
  const table = node('table', 'fx-table', [
    node(
      'thead',
      '',
      node(
        'tr',
        '',
        columns.map((c) => node('th', '', c[0])),
      ),
    ),
    node(
      'tbody',
      '',
      rows.map((row) =>
        node(
          'tr',
          '',
          columns.map((c) => node('td', '', c[1](row))),
        ),
      ),
    ),
  ]);
  ctx.detail(
    title,
    rows.length ? node('div', 'fx-table-wrap', table) : node('p', 'fx-muted', '所选时间范围暂无记录'),
  );
}

export function businessDashboard(ctx, openOperations) {
  const s = ctx.state,
    day = s.today;
  const finance = ctx.permitted('finance'),
    care = ctx.permitted('care'),
    longCare = ctx.permitted('longCare');
  const censusAccess = ctx.available('residents') || finance;
  const grant = {
    census: censusAccess,
    served: care,
    visits: care,
    admissions: censusAccess,
    discharges: censusAccess,
    gross: finance,
    perCapita: finance && care,
  };
  const source = metricsSource(s);
  const workspace = ctx.workspaceState || {};
  const saved = workspace.cockpit || {};
  let period = saved.period || '本月',
    mode = saved.mode || '较上一周期',
    start = saved.start || day.slice(0, 7) + '-01',
    end = saved.end || day;
  const clock = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date());
  const root = node('section', 'biz-screen'),
    top = node('header', 'biz-header'),
    body = node('div', 'biz-body');
  const err = node('p', 'form-error');
  err.setAttribute('role', 'alert');
  const pick = node('select');
  pick.setAttribute('aria-label', '对比方式');
  for (const item of ['较上一周期', '上年同期', '关闭对比']) pick.add(new Option(item, item));
  pick.value = mode;
  pick.onchange = () => {
    mode = pick.value;
    draw();
  };
  const picker = node('div', 'biz-datepick');
  const first = node('input'),
    last = node('input');
  for (const [input, value, text] of [
    [first, start, '开始日期'],
    [last, end, '结束日期'],
  ]) {
    input.type = 'date';
    input.max = day;
    input.value = value;
    input.setAttribute('aria-label', text);
    input.onchange = () => {
      start = first.value;
      end = last.value;
      draw();
    };
  }
  const group = node('div', 'biz-periods');
  for (const name of ['今日', '本周', '本月', '本季度', '本年', '自定义'])
    group.append(
      action(name, () => {
        period = name;
        draw();
      }),
    );
  const full = action('全屏', async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await root.requestFullscreen();
    } catch {
      ctx.toast('此窗口未允许全屏显示');
    }
  });
  root.addEventListener('fullscreenchange', () => {
    full.textContent = document.fullscreenElement === root ? '退出全屏' : '全屏';
  });
  const reload = action('刷新', async () => {
    reload.disabled = true;
    try {
      await ctx.refreshWorkspace(root);
    } catch (e) {
      ctx.toast(e.message);
    } finally {
      reload.disabled = false;
    }
  });
  picker.append(first, ' 至 ', last);
  top.append(
    node('h1', '', '医养经营管理大屏'),
    node('div', 'biz-controls', [
      node('div', 'biz-controls-group', ['时间范围', group]),
      node('label', 'biz-controls-group', ['对比方式', pick]),
      picker,
      node('div', 'biz-asof', [node('span', '', '数据读取 ' + clock), reload, full]),
    ]),
    err,
  );
  root.append(top, body);
  function draw() {
    for (const b of group.children) b.setAttribute('aria-pressed', String(b.textContent === period));
    picker.hidden = period !== '自定义';
    err.textContent = '';
    let range;
    try {
      range = bounds(day, period, { start, end });
    } catch (e) {
      err.textContent = e.message;
      body.replaceChildren();
      return;
    }
    workspace.cockpit = { period, mode, start, end };
    const previous = comparison(range, period, mode),
      a = source.activity(range),
      b = previous && source.activity(previous);
    const series = periods(range).map((r) => ({ ...r, ...source.activity(r) }));
    const indicators = node('div', 'biz-kpis');
    for (const [key, label, unit, route] of metrics) {
      const value = grant[key] ? a[key] : null;
      const [n, u] = compact(value);
      const k = node('button', 'biz-kpi', [
        node('span', '', label),
        node('strong', '', [n, node('small', '', u + unit)]),
        node(
          'small',
          'biz-delta',
          !grant[key] ? '按岗位授权查看' : b ? summariseChange(value, b[key], unit) : '',
        ),
      ]);
      k.type = 'button';
      k.disabled = !grant[key];
      k.onclick = () => {
        if (['gross', 'perCapita'].includes(key))
          details(ctx, label + ' · 实收凭证', a.incoming, [
            ['到账日期', (r) => r.date],
            ['凭证', (r) => r.id],
            ['实收（元）', (r) => fmt(r.gross / 100)],
          ]);
        else if (['visits', 'served'].includes(key))
          details(ctx, label + ' · 已完成照护', a.done, [
            ['日期', (r) => r.date],
            ['护理项目', (r) => r.title],
            ['长辈档案号', (r) => r.id],
          ]);
        else if (ctx.available(route)) ctx.go(route);
        else
          details(ctx, label + ' · 时段明细', series, [
            ['至', (r) => r.end],
            [label, (r) => fmt(r[key])],
          ]);
      };
      indicators.append(k);
    }
    const people = (s.residents || []).filter((p) => a.servedIds.has(p.id));
    const ages = ['90岁以上', '80–89岁', '70–79岁', '60–69岁', '60岁以下', '年龄未登记'];
    const ageGroups = count(people, (p) =>
      p.age == null
        ? ages[5]
        : p.age >= 90
          ? ages[0]
          : p.age >= 80
            ? ages[1]
            : p.age >= 70
              ? ages[2]
              : p.age >= 60
                ? ages[3]
                : ages[4],
    );
    const assessed = new Map();
    for (const r of [...(s.assessments || [])].sort((x, y) =>
      (x.scale?.assessedOn || x.date || '').localeCompare(y.scale?.assessedOn || y.date || ''),
    )) {
      if (r.scale?.gradeName && (r.scale.assessedOn || r.date) <= range.end)
        assessed.set(r.residentId, r.scale.gradeName);
    }
    const grades = ['完全失能', '重度失能', '中度失能', '轻度失能', '能力完好', '未有量表结论'];
    const levels = count(people, (p) => assessed.get(p.id) || grades.at(-1));
    const insurance = new Map();
    for (const r of [...(s.longCareEvents || [])].sort((x, y) => x.date.localeCompare(y.date))) {
      if (r.date <= range.end) insurance.set(r.residentId, r);
    }
    const insured = people.filter((p) => insurance.has(p.id));
    const ins = count(insured, (p) => insurance.get(p.id)?.insuranceType || '险种未登记');
    const insuranceList = [
      ['城乡居民', ins.get('城乡居民') || 0],
      ['城镇职工', ins.get('城镇职工') || 0],
      ['险种未登记', ins.get('险种未登记') || 0],
      ['未见有效登记', people.length - insured.length],
    ];
    const structure = card(
      '服务对象与险种结构',
      stats([
        ['服务人数', care ? fmt(a.served) : '—'],
        ['有参保记录', care && longCare ? pct(insured.length, a.served) : '—'],
      ]),
      node('h3', '', '年龄段分布'),
      care
        ? progress(
            ages.map((k) => [k, ageGroups.get(k) || 0]),
            people.length,
            true,
          )
        : node('p', 'biz-empty', '需照护数据权限'),
      node('h3', '', '险种结构'),
      care && longCare
        ? ring(insuranceList, people.length, pct(insured.length, people.length), (n) => n + ' 人')
        : node('p', 'biz-empty', '需照护与长护险数据权限'),
      node('h3', '', '失能等级分布'),
      care
        ? progress(
            grades.map((k) => [k, levels.get(k) || 0]),
            people.length,
          )
        : null,
    );
    const beds = s.beds || [],
      active = beds.filter((x) => !['维修', '停用', '维修中'].includes(x.status)),
      occupied = active.filter((x) => x.residentId).length;
    const vacant = active.filter((x) => x.status === '空闲').length,
      leaves = new Set(
        (s.leaves || []).filter((l) => l.startDate <= day && day <= l.endDate).map((l) => l.residentId),
      );
    const bedAccess = ctx.available('beds') || finance;
    const bedPanel = card(
      '床位运营 · 今日',
      stats([
        ['入住率', bedAccess ? pct(occupied, active.length) : '—'],
        [
          '在院床位使用率',
          bedAccess
            ? pct(active.filter((x) => x.residentId && !leaves.has(x.residentId)).length, active.length)
            : '—',
        ],
      ]),
      node(
        'div',
        'biz-bed-grid',
        [
          ['开放床位', active.length],
          ['占用床位', occupied],
          ['空闲床位', vacant],
          ['新入住', a.admissions],
          ['本期退住', a.discharges],
          ['请假在外', leaves.size],
        ].map(([t, v]) =>
          node('div', '', [node('small', '', t), node('strong', '', bedAccess ? fmt(v) : '—')]),
        ),
      ),
    );
    const ranks = [...count(a.done, (x) => x.title)].sort((x, y) => y[1] - x[1]).slice(0, 15);
    const rankPanel = card(
      '服务量排行榜',
      node('p', 'biz-hint', '护理项目 · 已完成服务人次'),
      care ? progress(ranks, a.visits) : node('p', 'biz-empty', '需照护数据权限'),
    );
    const income = finance ? source.structure(a.incoming) : [];
    const summary = card(
      '服务与收入联动',
      stats([
        ['服务人数', care ? fmt(a.served) : '—'],
        ['服务人次', care ? fmt(a.visits) : '—'],
        ['人均实收（元）', grant.perCapita ? fmt(a.perCapita) : '—'],
      ]),
    );
    const financePanel = card(
      '收入结构统计',
      finance && income.length
        ? ring(income, a.gross, fmt(a.gross) + '元', (n) => '¥' + fmt(n))
        : node('p', 'biz-empty', finance ? '本期无到账记录' : '需财务数据权限'),
      node('h3', '', '分类实收走势（元）'),
      finance
        ? chart(series, 'gross', colors[2], '元', {
            categories: income,
            rows: series.map((sample) => new Map(source.structure(sample.incoming))),
          })
        : null,
      node('p', 'biz-hint', '按到账日归集，含预缴。账单核销按正向明细金额比例分摊。'),
    );
    const trend = card(
      '趋势走势',
      ...[
        [0, 0],
        [2, 3],
        [5, 2],
      ].map(([ix, col]) => {
        const [k, t, u] = metrics[ix];
        return node('div', 'biz-trend', [
          node('h3', '', [t + '趋势', node('strong', '', grant[k] ? fmt(series.at(-1)?.[k]) + u : '—')]),
          grant[k] ? chart(series, k, colors[col], u) : node('p', 'biz-empty', '需相应业务权限'),
        ]);
      }),
      action('查看分期明细', () =>
        details(ctx, '本期指标明细', series, [
          ['日期', (r) => r.start + ' 至 ' + r.end],
          ...metrics.filter(([k]) => grant[k]).map(([k, t]) => [t, (r) => fmt(r[k])]),
        ]),
      ),
    );
    const rangeText =
      range.start + ' 至 ' + range.end + (previous ? '　对比 ' + previous.start + ' 至 ' + previous.end : '');
    body.replaceChildren(
      indicators,
      node('div', 'biz-grid', [
        structure,
        node('div', 'biz-column', [bedPanel, rankPanel]),
        node('div', 'biz-column', [summary, financePanel]),
        trend,
      ]),
      node('footer', 'biz-foot', [node('span', '', rangeText), action('查看日常运营明细', openOperations)]),
    );
  }
  draw();
  return root;
}
