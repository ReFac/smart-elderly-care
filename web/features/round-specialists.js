import { displayLocale } from '../lib/locale.js';
import { badge, btn, node } from './shared.js';
import { taskReceipt } from './evidence-runtime.js';

const agents = [
  { id: 'health-review', title: '长辈健康变化', description: '整理这位长辈近期有记录的健康变化，列出供医护人员核对的依据。' },
  { id: 'daily-life', title: '今日生活', description: '整理这位长辈已登记的三餐、起居和活动，保留对应的照护记录。' },
];

const clock = new Intl.DateTimeFormat(displayLocale, {
  timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
});

export const localStamp = value => value ? clock.format(new Date(value)) : '尚无记录';

const sourceNames = {
  task: '照护工单', vital: '体征记录', healthRecord: '健康记录', reviewedCough: '已复核的咳嗽观察',
  resident: '长辈档案', groupActivity: '活动出席确认', reviewedFall: '现场核实的跌倒记录',
};
const providers = {records:'院内记录', deepseek:'DeepSeek', openai:'OpenAI', anthropic:'Anthropic', google:'Google'};

function valueRow(label, value) {
  return node('div', '', [node('dt', '', label), node('dd', '', value)]);
}

export function specialistSchedules(ctx, schedules, configure, refresh) {
  const section = node('section', 'rounds-card specialist-settings', [
    node('header', 'rounds-heading', [
      node('h2', '', '长辈档案自动整理'), btn(ctx, '刷新运行状态', refresh, 'ghost'),
    ]),
  ]);
  const grid = node('div', 'round-specialist-grid');
  for (const def of agents) {
    const plan = schedules.find(row => row.id === def.id);
    if (!plan) continue;
    const configureButton = btn(ctx, '调整计划', () => configure(plan, def.title));
    configureButton.setAttribute('aria-label', '调整' + def.title + '计划');
    const card = node('article', 'round-specialist', [
      node('header', 'rounds-heading', [
        node('h3', '', def.title), badge(ctx, plan.enabled ? '已启用' : '已暂停', plan.enabled ? 'green' : 'neutral'),
      ]),
      node('p', 'fx-muted', def.description),
      node('dl', 'round-specialist-facts', [
        valueRow('运行周期', '每 ' + plan.intervalMinutes + ' 分钟'),
        valueRow('下次运行', plan.enabled ? localStamp(plan.nextRunAt) : '已暂停'),
        valueRow('上次运行', localStamp(plan.lastRunAt)),
        valueRow('上次结果', plan.lastResult || '尚无运行结果'),
        valueRow('排队中（含重试）', String(plan.pending) + ' 份'),
        valueRow('等待重试', String(plan.retrying) + ' 份'),
      ]),
      configureButton,
    ]);
    card.dataset.agentSchedule = def.id;
    grid.append(card);
  }
  if (grid.childElementCount) section.append(grid);
  else section.append(node('p', 'fx-muted', '暂无可用的定时整理计划。'));
  return section;
}

function sourceList(evidence) {
  if (!evidence?.length) return null;
  return node('details', 'rounds-evidence', [
    node('summary', '', '查看依据（' + evidence.length + '）'),
    node('ul', '', evidence.map(item => node('li', '', [
      item.date, item.label || sourceNames[item.kind] || '来源记录', item.id,
    ].filter(Boolean).join(' · ')))),
  ]);
}

export function residentSpecialists(ctx, drafts, residentId, compact) {
  if (!drafts) return null;
  const grid = node('div', 'round-specialist-grid resident-specialists');
  for (const def of agents) {
    if (!Object.hasOwn(drafts, def.id)) continue;
    const draft = drafts[def.id];
    if (draft && (draft.residentId !== residentId || draft.agentId !== def.id)) continue;
    const rows = draft?.items || [];
    const body = node('article', 'round-specialist', [
      node('header', 'rounds-heading', [
        node('h4', '', def.title),
        draft ? badge(ctx, draft.source === 'records' && !rows.length ? '暂无依据' : 'AI 草稿', 'blue') : null,
      ]),
    ]);
    body.dataset.residentAgent = def.id;
    if (!draft) {
      body.append(node('p', 'fx-muted', '尚无已生成的草稿。'));
    } else {
      body.append(node('small', 'fx-muted', [
        draft.day, '生成于 ' + localStamp(draft.generatedAt), draft.model || providers[draft.source] || draft.source,
      ].filter(Boolean).join(' · ')));
      const renderItem = row => node('div', 'rounds-paragraph', [
        row.day && row.day !== draft.day ? node('small', 'fx-muted', row.day) : null,
        node('p', '', row.text), sourceList(row.evidence),
      ]);
      const visible = compact ? rows.slice(0, 1) : rows;
      for (const row of visible) body.append(renderItem(row));
      if (visible.length < rows.length) body.append(node('details', 'rounds-evidence', [
        node('summary', '', '其余 ' + (rows.length - visible.length) + ' 条记录'),
        ...rows.slice(visible.length).map(renderItem),
      ]));
      if (!rows.length) body.append(node('p', 'fx-muted', '本次整理没有可展示的条目。'));
      const receipt = taskReceipt(draft.draftRuntime, draft.taskId);
      if (receipt) body.append(receipt);
    }
    grid.append(body);
  }
  return grid.childElementCount ? grid : null;
}
