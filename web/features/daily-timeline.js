import { btn, node, today } from './shared.js';
import { staffLabel } from './people-labels.js';

function weekStart(end) {
  const day = new Date(end + 'T12:00:00Z');
  day.setUTCDate(day.getUTCDate() - 6);
  return day.toISOString().slice(0, 10);
}

export function dailyTimeline(ctx, resident) {
  const panel = node('section', 'life-timeline');
  panel.dataset.roundsResidentId = resident.id;
  const list = node('div', 'life-days');
  const last = node('input');
  last.type = 'date';
  last.max = last.value = today(ctx);
  last.setAttribute('aria-label', '生活时间线的截止日期');
  const range = node('small', 'fx-muted');
  panel.append(node('header', 'group-heading', [
    node('div', '', [node('h3', '', '生活时间线'), range]),
    node('label', 'life-date', ['截至', last]),
  ]), list);
  let sequence = 0;
  async function draw() {
    const ticket = ++sequence;
    const end = last.value || today(ctx);
    const start = weekStart(end);
    range.textContent = start + ' 至 ' + end;
    const params = new URLSearchParams({ start, end });
    list.replaceChildren(node('p', 'fx-muted', '正在读取个人记录…'));
    try {
      const result = await ctx.get('/api/residents/' + encodeURIComponent(resident.id) + '/daily-life?' + params);
      if (ticket !== sequence) return;
      const groups = new Map();
      for (const event of result.events) {
        if (!groups.has(event.day)) groups.set(event.day, []);
        groups.get(event.day).push(event);
      }
      const days = [...groups].map(([day, rows]) => {
        const events = rows.map(e => {
          const meal = e.kind !== '集体活动';
          return node('li', 'life-event', [
            node('time', '', e.startsAt + '–' + e.endsAt),
            node('div', '', [
              node('strong', '', meal ? e.kind : e.details),
              meal ? node('p', '', (e.intake ? '实际进食：' + e.intake : '当餐提供：' + e.details)) : null,
              node('small', 'fx-muted', [e.roomNumber ? e.roomNumber + ' 房' : '', e.confirmedBy &&
                staffLabel(ctx, { id: e.confirmedById, displayName: e.confirmedBy, role: e.confirmedByPosition }) + ' 确认'].filter(Boolean).join(' · ')),
            ]),
          ]);
        });
        return node('section', 'life-day', [node('h4', '', day), node('ol', '', events)]);
      });
      list.replaceChildren(...(days.length ? days : [node('p', 'fx-muted', '这七天还没有已确认的用餐或集体活动。')]));
    } catch (error) {
      if (ticket === sequence) list.replaceChildren(node('p', 'form-error', error.message), btn(ctx, '重试', draw));
    }
  }
  last.onchange = draw;
  draw();
  return panel;
}
