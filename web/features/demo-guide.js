import { button, el, icon } from '../lib/ui.js';
import { menuFor } from '../lib/desk-navigation.js';
import { residentLabel } from './people-labels.js';

const tours = [
  ['leads', '', '电话回访与参观预约'],
  ['residents', '', '待入住、试住与正式入住'],
  ['residents', 'discharged', '退住与床位变动'],
  ['care', 'scheduledWork', '三餐菜单、早晚巡查与派发'],
  ['care', 'handover', '交接事项与接班确认'],
  ['medications', 'receiving', '药品接收与入账'],
  ['inventory', 'moves', '物资入库与领用流水'],
  ['billing', 'receipts', '实收款与收费凭证'],
  ['inbox', '', '设备预警与复核'],
];

function visibleTours(ctx) {
  const entries = menuFor(ctx).flatMap(group => group.children || [[group.route, group.label, group.tab]])
    .map(([route,, tab]) => route + '/' + (tab || ''));
  return tours.filter(([route, tab]) => entries.includes(route + '/' + tab));
}

function visibleCases(ctx) {
  if (!ctx.available('dossier') || !ctx.permitted('medical')) return [];
  const ids = new Set(ctx.state.demoVisitIds);
  return (ctx.state.medicalVisits || []).filter(r => ids.has(r.id))
    .sort((a,b) => b.fields.eventDate.localeCompare(a.fields.eventDate));
}

export function demoGuideButton(ctx) {
  if (!ctx.state.demoGuide || !(visibleTours(ctx).length || visibleCases(ctx).length)) return null;
  return button('演示导览', () => {
    const live = ctx.current?.() || ctx;
    if (!live.state.demoGuide) return;
    const content = el('div','demo-guide');
    const dialog = live.detail('演示导览', content);
    const journeys = visibleTours(live);
    if (journeys.length) {
      content.append(el('h3','','业务流程'));
      const links = el('nav','demo-guide-list');
      links.setAttribute('aria-label','演示业务流程');
      for (const [route,tab,label] of journeys) {
        const a = el('a','desk-shortcut');
        a.href = '#' + route + (tab ? '?' + new URLSearchParams({tab}) : '');
        a.append(el('span','',label),icon('chevron',14));
        a.addEventListener('click', event => {
          if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
          dialog.close();
        });
        links.append(a);
      }
      content.append(links);
    }
    const cases = visibleCases(live);
    if (cases.length) {
      content.append(el('h3','','演示就诊病例'));
      for (const visit of cases) {
        const text = visit.attachments?.[0]?.filename || '';
        const title = text.slice(text.indexOf('-') + 1).replace(/\.pdf$/i,'') || visit.fields.department;
        const entry = button(residentLabel(live,visit.residentId) + ' · ' + title, async () => {
          const { openRecordedVisit } = await import('./dossier.js');
          dialog.close();
          openRecordedVisit(live, visit.residentId, visit.id);
        }, 'ghost');
        entry.classList.add('demo-guide-case');
        entry.append(el('small','',visit.fields.eventDate));
        content.append(entry);
      }
    }
  },'secondary','folder');
}
