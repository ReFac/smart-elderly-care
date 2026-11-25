import { residentLabel, residentAnchor, staffLabel } from './people-labels.js';
import { downloadDocument, openDocumentButton } from './secure-documents.js';
import {
  choose,
  badge,
  btn,
  byRecent,
  canAct,
  facts,
  field,
  staffField,
  link,
  memo,
  named,
  node,
  options,
  records,
  residentField,
  residentName,
  runForm,
  section,
  select,
  table,
  today,
} from './shared.js';

const priorities = ['常规随访', '重点跟进', '优先复核'];
const status = { value: (r) => r.status };
const assessmentChoices = (ctx, residentId) => [
  { value: '', label: '不引用量表' },
  ...byRecent(ctx.state.assessments || [])
    .filter((a) => a.residentId === residentId)
    .map((a) => ({
      value: a.id,
      label: a.date + ' · ' + (a.scale?.gradeName || a.level) + ' · ' + a.note,
    })),
];

function createScreen(ctx, residentId) {
  runForm(ctx, {
    title: '登记筛查',
    action: 'care.screen',
    fields: [
      ...(residentId ? [] : [residentField(ctx)]),
      field('subject', '筛查项目'),
      memo('finding', '观察或筛查结果', true),
    ],
    map: (values) => ({ ...values, residentId: residentId || values.residentId }),
  });
}

function schedule(ctx, r) {
  runForm(ctx, {
    title: '分级并安排随访',
    action: 'care.scheduleFollowup',
    description: residentName(ctx, r.residentId) + ' · ' + r.subject + ' · ' + r.finding,
    fields: [
      select('priority', '人工确认级别', options(priorities)),
      select('assessmentId', '关联评估', assessmentChoices(ctx, r.residentId), { required: false }),
      memo('basis', '分级依据', true),
      memo('intervention', '干预安排', true),
      staffField(ctx, 'assignee', '随访责任人'),
      field('dueDate', '预约随访日期', { type: 'date', value: today(ctx), min: today(ctx) }),
    ],
    map: (v) => ({ ...v, followupId: r.id }),
  });
}

function finish(ctx, r) {
  runForm(ctx, {
    title: '登记干预与效果评价',
    action: 'care.finishFollowup',
    description: residentName(ctx, r.residentId) + ' · ' + r.intervention,
    fields: [memo('actual', '实际干预与随访', true), memo('outcome', '效果评价', true)],
    map: (v) => ({ ...v, followupId: r.id }),
  });
}

function showFollowup(ctx, r) {
  ctx.detail(
    '筛查与随访记录',
    facts(
      [
        ['长辈', residentName(ctx, r.residentId)],
        ['项目', r.subject],
        ['筛查结果', r.finding],
        ['登记人', r.openedBy],
        ['日期', r.date],
        ['状态', r.status],
        ['级别', r.priority],
        ['分级依据', r.basis],
        ['关联评估编号', r.assessmentId],
        ['分级人', r.gradedBy],
        ['干预计划', r.intervention],
        ['预约', r.dueDate],
        ['责任人', staffLabel(ctx, r.assignee, r.assigneeId)],
        ['实际干预', r.actual],
        ['效果评价', r.outcome],
        ['完成人', r.finishedBy],
        ['完成日期', r.finishedAt],
      ].filter(([, v]) => v)
    )
  );
}

function followupAction(ctx, r) {
  if (r.status === '待分级') return link(ctx, '分级安排', () => schedule(ctx, r));
  if (r.status === '待随访') return link(ctx, '登记效果', () => finish(ctx, r));
  return link(ctx, '查看记录', () => showFollowup(ctx, r));
}

export function followups(ctx) {
  return table(ctx, {
    title: '筛查与随访',
    rows: byRecent(ctx.state.followups || []),
    search: {
      placeholder: '搜索长辈或项目',
      value: (r) => residentName(ctx, r.residentId) + r.subject,
    },
    filter: status,
    action: btn(ctx, '登记筛查', () => createScreen(ctx)),
    cols: [
      { label: '长辈', view: (r) => residentAnchor(ctx, r.residentId) },
      { label: '筛查项目', view: (r) => named(r.subject, r.finding) },
      { label: '跟进级别', view: (r) => r.priority || '待分级' },
      { label: '预约随访', view: (r) => named(r.dueDate || '待安排', staffLabel(ctx, r.assignee, r.assigneeId)) },
      {
        label: '状态',
        view: (r) =>
          r.status === '待随访' && r.dueDate <= today(ctx)
            ? badge(ctx, '随访到期', 'amber')
            : badge(ctx, r.status),
      },
      { label: '办理', view: (r) => followupAction(ctx, r) },
    ],
  });
}

function createReferral(ctx, residentId) {
  const choices = byRecent(ctx.state.residents).map((r) => ({
    value: r.id,
    label: residentLabel(ctx, r) + ' · ' + r.status,
  }));
  const fields = residentId
    ? [select('assessmentId', '依据评估', assessmentChoices(ctx, residentId), { required: false })]
    : [select('residentId', '长辈', choices)];
  runForm(ctx, {
    title: '登记院外衔接',
    action: 'care.refer',
    fields: [
      ...fields,
      select('kind', '交接类型', options(['院外转介', '出院衔接'])),
      select('channel', '接收渠道', options(['医联体', '基层公卫', '长护险经办', '其他机构'])),
      field('destination', '接收单位'),
      memo('summary', '交接情况与后续安排', true),
    ],
    map: (v) => ({ ...v, residentId: residentId || v.residentId }),
  });
}

function consentDialog(ctx, r, withdraw) {
  const scopes = ['姓名与交接摘要', '姓名、交接摘要和过敏及风险记录'];
  runForm(ctx, {
    title: withdraw ? '登记撤回授权' : '登记本人授权',
    action: 'care.referralConsent',
    description: '本次授权仅用于向' + r.destination + '交接。',
    fields: [
      ...(withdraw ? [] : [select('scope', '本人同意的共享范围', options(scopes))]),
      field('basis', '本人' + (withdraw ? '撤回' : '授权') + '凭据编号或核验记录'),
    ],
    map: (v) => ({ ...v, decision: withdraw ? '撤回' : '同意', referralId: r.id }),
  });
}

function exportDialog(ctx, r) {
  const consent = r.consents.at(-1);
  ctx.dialog({
    title: '导出交接数据包',
    description: r.destination + ' · 本人授权范围：' + consent.scope,
    fields: [],
    submitLabel: '确认导出',
    onSubmit: async () => {
      const bytes = crypto.getRandomValues(new Uint8Array(16));
      const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
      const exportId = [
        hex.slice(0, 8),
        hex.slice(8, 12),
        hex.slice(12, 16),
        hex.slice(16, 20),
        hex.slice(20),
      ].join('-');
      if (!(await ctx.command('care.exportReferral', { referralId: r.id, exportId }))) return false;
      return downloadDocument(ctx, { kind: 'referral', id: r.id, exportId });
    },
  });
}

function showReferral(ctx, r) {
  const body = node(
    'div',
    'fx-profile',
    facts(
      [
        ['长辈', residentName(ctx, r.residentId)],
        ['接收单位', r.destination],
        ['类型', r.kind],
        ['接收渠道', r.channel],
        ['交接摘要', r.summary],
        ['当时的过敏记录', r.allergies],
        ['当时的关注项', r.risk],
        ['依据评估编号', r.assessmentId],
        ['经办人', staffLabel(ctx, r.operator, r.operatorId)],
        ['日期', r.date],
        ['状态', r.status],
        ['接收人', r.receivedBy],
        ['核实依据', r.receipt],
        ['本院回执登记人', staffLabel(ctx, r.recordedBy)],
        ['登记回执日期', r.receivedAt],
      ].filter(([, value]) => value)
    )
  );
  const history = r.consents || [];
  const consent = history.at(-1);
  const granted = consent?.decision === '同意';
  body.append(
    section(
      '本人授权',
      records(
        history,
        (entry) =>
          named(
            entry.decision + (entry.scope ? ' · ' + entry.scope : ''),
            [entry.date, staffLabel(ctx, entry.operator), entry.basis].join(' · ')
          ),
        '尚未登记本人授权'
      )
    ),
    section(
      '本地导出凭证',
      records(
        r.exports || [],
        (e) =>
          node('div', 'fx-profile', [
            named(e.date + ' · ' + staffLabel(ctx, e.operator), e.id + ' · 授权记录 ' + e.consentNumber),
            granted && e.consentNumber === history.length
              ? link(ctx, '下载加密包', () =>
                  downloadDocument(ctx, { kind: 'referral', id: r.id, exportId: e.id })
                )
              : null,
          ]),
        '尚无导出记录'
      )
    )
  );
  const dialog = ctx.detail('院外衔接详情', body);
  body.append(
    btn(ctx, '登记本人授权', () => {
      dialog.close();
      consentDialog(ctx, r, false);
    })
  );
  if (granted)
    body.append(
      btn(ctx, '撤回授权', () => {
        dialog.close();
        consentDialog(ctx, r, true);
      }),
      btn(ctx, '导出交接数据包', () => {
        dialog.close();
        exportDialog(ctx, r);
      })
    );
  if (r.status === '待接收回执')
    body.append(
      btn(ctx, '登记接收方回执', () => {
        dialog.close();
        runForm(ctx, {
          title: '登记接收方回执',
          action: 'care.receiveReferral',
          fields: [field('receiver', '接收方联系人'), memo('receipt', '回执编号或核实记录', true)],
          map: (v) => ({ ...v, referralId: r.id }),
        });
      })
    );
}

export function referrals(ctx) {
  return table(ctx, {
    title: '院外衔接',
    rows: byRecent(ctx.state.referrals || []),
    action: choose(openDocumentButton(ctx), btn(ctx, '登记院外衔接', () => createReferral(ctx))),
    filter: status,
    search: {
      placeholder: '搜索长辈或接收单位',
      value: (r) => residentName(ctx, r.residentId) + r.destination,
    },
    cols: [
      { label: '长辈', view: (r) => residentAnchor(ctx, r.residentId) },
      { label: '交接类型', view: (r) => r.kind },
      { label: '接收单位', view: (r) => named(r.destination, r.date) },
      { label: '状态', view: (r) => badge(ctx, r.status) },
      { label: '办理', view: (r) => link(ctx, '查看交接', () => showReferral(ctx, r)) },
    ],
  });
}

export function clinicalHistory(ctx, resident) {
  if (!canAct(ctx, 'care.refer')) return null;
  const clinical = node('div', 'fx-profile');
  clinical.append(
    section(
      '筛查与随访',
      records(
        byRecent(ctx.state.followups || []).filter((r) => r.residentId === resident.id),
        (r) => link(ctx, r.subject + ' · ' + r.status, () => showFollowup(ctx, r))
      )
    )
  );
  if (resident.status === '在住')
    clinical.append(btn(ctx, '登记筛查', () => createScreen(ctx, resident.id)));
  clinical.append(
    section(
      '院外衔接',
      records(
        byRecent(ctx.state.referrals || []).filter((r) => r.residentId === resident.id),
        (r) =>
          link(ctx, r.kind + ' · ' + r.destination + ' · ' + r.status, () => showReferral(ctx, r))
      )
    ),
    btn(ctx, '登记院外衔接', () => createReferral(ctx, resident.id))
  );
  return clinical;
}
