import { receiptRows } from './receipt-ledger.js';

const DAY = 86400000;
const parse = (day) => new Date(day + 'T00:00:00Z');
const iso = (d) => d.toISOString().slice(0, 10);
const shift = (day, days) => iso(new Date(parse(day).getTime() + days * DAY));
const inRange = (date, r) => date && r.start <= date && date <= r.end;
const length = (range) => Math.round((parse(range.end) - parse(range.start)) / DAY) + 1;

function shiftMonth(day, delta) {
  const d = parse(day),
    n = d.getUTCDate();
  d.setUTCDate(1);
  d.setUTCMonth(d.getUTCMonth() + delta);
  const end = new Date(d);
  end.setUTCMonth(end.getUTCMonth() + 1, 0);
  d.setUTCDate(Math.min(n, end.getUTCDate()));
  return iso(d);
}
export function bounds(today, period, custom = {}) {
  const end = today,
    month = today.slice(0, 7) + '-01';
  if (period === '自定义') {
    if (
      !/^\d{4}-\d{2}-\d{2}$/.test(custom.start) ||
      !/^\d{4}-\d{2}-\d{2}$/.test(custom.end) ||
      custom.start > custom.end ||
      custom.end > today
    )
      throw Error('请选择有效日期，结束日期不能晚于今天');
    return { start: custom.start, end: custom.end };
  }
  const m = parse(month).getUTCMonth();
  const start = {
    今日: today,
    本周: shift(today, -((parse(today).getUTCDay() + 6) % 7)),
    本月: month,
    本季度: shiftMonth(month, -(m % 3)),
    本年: today.slice(0, 4) + '-01-01',
  }[period];
  return { start, end };
}
export function comparison(range, period, mode) {
  if (mode === '关闭对比') return null;
  const months = mode === '上年同期' ? 12 : { 本月: 1, 本季度: 3, 本年: 12 }[period];
  if (months) return { start: shiftMonth(range.start, -months), end: shiftMonth(range.end, -months) };
  const days = period === '本周' ? 7 : length(range);
  return { start: shift(range.start, -days), end: shift(range.end, -days) };
}
export function periods(range) {
  const days = length(range);
  if (days <= 31) {
    // With a single observation day, show one labelled point rather than inventing hourly records.
    const width = Math.ceil(days / 10),
      result = [];
    for (let i = 0; i < days; i += width) {
      const start = shift(range.start, i),
        end = shift(range.start, Math.min(i + width - 1, days - 1));
      result.push({ start, end, label: end.slice(5) });
    }
    return result;
  }
  const count =
    (Number(range.end.slice(0, 4)) - Number(range.start.slice(0, 4))) * 12 +
    Number(range.end.slice(5, 7)) -
    Number(range.start.slice(5, 7)) +
    1;
  const result = [],
    width = Math.ceil(count / 12),
    anchor = range.start.slice(0, 7) + '-01';
  for (let i = 0; i < count; i += width) {
    const start = i ? shiftMonth(anchor, i) : range.start;
    const end = i + width >= count ? range.end : shift(shiftMonth(anchor, i + width), -1);
    result.push({ start, end, label: count > 12 ? end.slice(0, 7) : Number(end.slice(5, 7)) + '月' });
  }
  return result;
}

function portion(totals, name, amount) {
  totals.set(name, (totals.get(name) || 0) + amount);
}
function spread(totals, amount, bill) {
  const weights = new Map();
  for (const line of bill?.lineItems || []) {
    if (line.amount > 0) portion(weights, line.label || '其他费用', Math.round(line.amount * 100));
  }
  if (!weights.size) {
    portion(totals, bill?.kind === 'security' ? '押金到账' : '未分项核销', amount);
    return;
  }
  const total = [...weights.values()].reduce((a, b) => a + b, 0);
  const parts = [...weights].map(([name, w]) => ({
    name,
    n: Math.floor((amount * w) / total),
    rest: (amount * w) % total,
  }));
  let remaining = amount - parts.reduce((sum, p) => sum + p.n, 0);
  for (const p of parts.sort((a, b) => b.rest - a.rest)) {
    portion(totals, p.name, p.n + (remaining-- > 0 ? 1 : 0));
  }
}

export function metricsSource(state) {
  const residents = state.residents || [],
    moves = new Map();
  for (const move of state.bedMoves || []) {
    if (!move.date || !move.residentId) continue;
    if (!moves.has(move.residentId)) moves.set(move.residentId, []);
    moves.get(move.residentId).push(move);
  }
  for (const history of moves.values()) history.sort((a, b) => a.date.localeCompare(b.date));
  const tasks = (state.tasks || [])
    .filter((t) => t.status === '已完成' && t.residentId)
    .map((t) => ({
      id: t.residentId,
      date: (t.completedAt || t.date || '').slice(0, 10),
      title: t.title || t.kind || '其他照护',
    }));
  const receipts = receiptRows(state),
    bills = new Map((state.bills || []).map((b) => [b.id, b]));
  function census(end) {
    return residents.filter((p) => {
      if (end === state.today) return p.status === '在住';
      const events = moves.get(p.id);
      if (events?.length) {
        const m = events.filter((e) => e.date <= end).at(-1);
        if (m) return Boolean(m.bedId);
        if (events[0].kind === '入住') return false;
      }
      return p.admittedAt && p.admittedAt <= end && (!p.dischargedAt || p.dischargedAt > end);
    });
  }
  function activity(range) {
    const done = tasks.filter((t) => inRange(t.date, range));
    const served = new Set(done.map((t) => t.id));
    const incoming = receipts.filter((r) => inRange(r.date, range));
    const gross = incoming.reduce((sum, r) => sum + r.gross, 0);
    const admits = new Set(),
      exits = new Set();
    for (const p of residents) {
      const events = moves.get(p.id) || [];
      for (const [kind, field, target] of [
        ['入住', 'admittedAt', admits],
        ['退住', 'dischargedAt', exits],
      ]) {
        const matches = events.filter((e) => e.kind === kind);
        if (matches.length ? matches.some((e) => inRange(e.date, range)) : inRange(p[field], range))
          target.add(p.id);
      }
    }
    return {
      census: census(range.end).length,
      served: served.size,
      visits: done.length,
      admissions: admits.size,
      discharges: exits.size,
      gross: gross / 100,
      perCapita: served.size ? gross / 100 / served.size : null,
      done,
      servedIds: served,
      incoming,
    };
  }
  function structure(incoming) {
    const totals = new Map();
    for (const receipt of incoming) {
      if (receipt.advance) portion(totals, '预缴到账', receipt.advance);
      for (const [billId, amount] of receipt.bills) spread(totals, amount, bills.get(billId));
      const unlinked = receipt.applied - [...receipt.bills.values()].reduce((a, b) => a + b, 0);
      if (unlinked) portion(totals, '未分项核销', unlinked);
    }
    return [...totals].sort((a, b) => b[1] - a[1]).map(([name, value]) => [name, value / 100]);
  }
  return { activity, structure };
}
