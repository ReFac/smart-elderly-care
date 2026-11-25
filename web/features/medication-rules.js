import { residentAnchor, staffLabel } from './people-labels.js';
import {
  badge,
  btn,
  byRecent,
  canAct,
  facts,
  field,
  link,
  memo,
  named,
  node,
  residentName,
  runForm,
  table,
} from './shared.js';

export function medicationDue(row, now) {
  return (
    row.status === '待执行' &&
    Boolean(row.scheduledAt) &&
    Date.parse(row.scheduledAt + ':00+08:00') <= now
  );
}

export const dueMedicationCount = (rows, now = Date.now()) =>
  rows.filter((r) => medicationDue(r, now)).length;

class MedicationSchedule extends HTMLElement {
  connectedCallback() {
    this.renderList();
    this.timer = setInterval(() => this.renderList(), 30000);
  }
  disconnectedCallback() {
    clearInterval(this.timer);
  }
}
if (!customElements.get('medication-schedule'))
  customElements.define('medication-schedule', MedicationSchedule);

export function medicationReminders(ctx, execute) {
  const host = document.createElement('medication-schedule');
  const rows = ctx.state.medications
    .filter((r) => r.status === '待执行' && r.scheduledAt)
    .sort((a, b) => a.scheduledAt.localeCompare(b.scheduledAt));
  let lastCount = -1;
  host.renderList = () => {
    const now = Date.now();
    const count = dueMedicationCount(rows, now);
    if (count === lastCount) return;
    lastCount = count;
    host.replaceChildren(
      table(ctx, {
        title: '已复核给药安排',
        rows,
        search: {
          placeholder: '搜索长辈或药品',
          value: (r) => residentName(ctx, r.residentId) + r.name,
        },
        cols: [
          { label: '给药时间（上海）', view: (r) => r.scheduledAt.replace('T', ' ') },
          { label: '长辈', view: (r) => residentAnchor(ctx, r.residentId) },
          { label: '药品', view: (r) => r.name },
          { label: '负责人员', view: (r) => staffLabel(ctx, r.assignee, r.assigneeId) },
          {
            label: '提醒',
            view: (r) =>
              medicationDue(r, now) ? badge(ctx, '已到时', 'amber') : badge(ctx, '待到时', 'neutral'),
          },
          { label: '办理', view: (r) => link(ctx, '登记执行', () => execute(r)) },
        ],
        empty: '尚无已复核、有计划时间的待执行用药。',
      })
    );
  };
  return host;
}

export function drugRules(ctx) {
  function publish() {
    runForm(ctx, {
      title: '发布配伍规则',
      action: 'care.publishDrugRule',
      description:
        '请按机构已核准的资料填写药品通用名、核查内容与版本。规则核对同一长辈待复核和待执行医嘱中的药名组合。',
      fields: [
        field('drugA', '药品一'),
        field('drugB', '药品二'),
        field('version', '核准版本'),
        field('source', '核准资料及编号'),
        memo('message', '核查提醒', true),
      ],
      submitLabel: '确认发布',
    });
  }
  function show(r) {
    const body = node(
      'div',
      'fx-profile',
      facts(
        [
          ['药品一', r.drugA],
          ['药品二', r.drugB],
          ['版本', r.version],
          ['核准资料', r.source],
          ['核查提醒', r.message],
          ['发布人', staffLabel(ctx, r.reviewer)],
          ['发布日期', r.date],
          ['状态', r.status],
          ['停用人', r.retiredBy],
          ['停用时间', r.retiredAt],
          ['停用原因', r.reason],
        ].filter(([, v]) => v)
      )
    );
    const dialog = ctx.detail('配伍规则与依据', body);
    if (canAct(ctx, 'care.retireDrugRule') && r.status === '生效')
      body.append(
        btn(ctx, '停用此版本', () => {
          dialog.close();
          runForm(ctx, {
            title: '停用配伍规则',
            action: 'care.retireDrugRule',
            fields: [memo('reason', '停用原因', true)],
            map: (v) => ({ ...v, ruleId: r.id }),
          });
        })
      );
  }
  return table(ctx, {
    title: '机构配伍规则',
    rows: byRecent(ctx.state.drugRules || []),
    action: canAct(ctx, 'care.publishDrugRule') ? btn(ctx, '发布配伍规则', publish) : null,
    filter: { value: (r) => r.status },
    search: {
      placeholder: '搜索药品或核准资料',
      value: (r) => [r.drugA, r.drugB, r.source].join(' '),
    },
    cols: [
      { label: '药品组合', view: (r) => named(r.drugA + ' / ' + r.drugB, r.version) },
      { label: '提醒', view: (r) => r.message },
      { label: '发布人', view: (r) => staffLabel(ctx, r.reviewer) },
      { label: '状态', view: (r) => badge(ctx, r.status) },
      { label: '依据', view: (r) => link(ctx, '查看规则', () => show(r)) },
    ],
    empty: '机构尚未发布已核准的配伍规则。',
  });
}
