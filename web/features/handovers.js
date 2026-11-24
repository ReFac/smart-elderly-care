import {
  badge,
  btn,
  byRecent,
  canAct,
  facts,
  link,
  memo,
  named,
  node,
  residentField,
  residentName,
  runForm,
  section,
  select,
  table,
} from './shared.js';

const statusOf = (row) => (row.assigneeId ? row.status : '历史记录');
const subject = (ctx, row) => (row.residentId ? residentName(ctx, row.residentId) : '全院');
const stamp = (at) => at?.slice(0, 19).replace('T', ' ');
const mine = (ctx, row) => row.status === '待签收' && row.assigneeId === ctx.state.user.id;

async function create(ctx, button) {
  button.disabled = true;
  try {
    const { recipients } = await ctx.get('/api/care/handover-recipients');
    if (!button.isConnected) return;
    if (!recipients.length) {
      const body = node(
        'div',
        'fx-profile',
        node('p', '', '请由总管理员在「账号与权限」为另一位在岗人员开通照护服务权限。')
      );
      const dialog = ctx.detail('暂无可选接班人', body);
      if (ctx.available('access'))
        body.append(
          btn(ctx, '前往账号与权限', () => {
            dialog.close();
            ctx.go('access');
          })
        );
      return;
    }
    const resident = residentField(ctx, { required: false, label: '交接范围' });
    resident.options.unshift({ value: '', label: '全院交班' });
    const accounts = recipients.map((r) => ({
      value: r.id,
      label: r.displayName + ' · ' + r.username,
    }));
    accounts.unshift({ value: '', label: '请选择接班人员' });
    runForm(ctx, {
      title: '登记交班',
      action: 'care.handover',
      description: '提交时保存当班工单摘要，交给所选账号签收。',
      fields: [
        resident,
        select('assigneeId', '接班人员', accounts),
        memo('note', '交接要点', true, { maxLength: 1000 }),
      ],
      submitLabel: '提交交班',
    });
  } catch (error) {
    if (button.isConnected) ctx.toast(error.message || '接班人员名单暂时无法读取，请重试。');
  } finally {
    button.disabled = false;
  }
}

export function showHandover(ctx, row) {
  const body = node('div', 'fx-profile', [
    facts([
      ['交接范围', subject(ctx, row)],
      ['状态', statusOf(row)],
      ['交班人', row.senderName],
      ['交班时间', stamp(row.createdAt) || row.date],
      ['接班人', row.assignee],
    ]),
    section('交接要点', node('p', '', row.note || '未填写')),
  ]);
  if (row.snapshot) {
    const s = row.snapshot;
    const counts = [
      ['当日待完成工单', s.pendingToday + ' 项'],
      ['逾期待完成工单', s.overdue + ' 项'],
      ['当日已完成工单', s.completedToday + ' 项'],
    ];
    if (s.openVitals != null) counts.push(['待复核体征异常', s.openVitals + ' 项']);
    body.append(section('交班时的业务摘要', facts(counts)));
  } else if (row.summary) {
    body.append(section('交班时的业务摘要', node('p', '', row.summary)));
  }
  if (row.status === '已签收') {
    body.append(
      section(
        '签收回执',
        facts([
          ['签收人', row.acceptedByName],
          ['签收时间', stamp(row.acceptedAt)],
          ['签收备注', row.receiptNote || '未填写'],
        ])
      )
    );
  }
  if (row.status === '已撤回') {
    body.append(
      section(
        '撤回记录',
        facts([
          ['撤回人', row.withdrawnByName],
          ['撤回时间', stamp(row.withdrawnAt)],
          ['撤回原因', row.withdrawReason],
        ])
      )
    );
  }
  if (mine(ctx, row) && canAct(ctx, 'care.acceptHandover')) {
    const dialog = ctx.dialog({
      title: '核对并签收交班',
      content: body,
      fields: [memo('note', '签收备注（选填）', false, { maxLength: 1000 })],
      submitLabel: '确认签收',
      onSubmit: ({ note }) => ctx.command('care.acceptHandover', { handoverId: row.id, note }),
    });
    dialog.dataset.handoverId = row.id;
  } else {
    const dialog = ctx.detail(row.status === '已签收' ? '交班与签收回执' : '交班记录', body);
    if (
      row.status === '待签收' &&
      row.senderId === ctx.state.user.id &&
      canAct(ctx, 'care.withdrawHandover')
    ) {
      dialog.dataset.pendingHandoverId = row.id;
      body.append(
        btn(ctx, '撤回交班', () => {
          dialog.close();
          const confirmation = ctx.dialog({
            title: '撤回交班',
            description: '撤回后本次交接结束。如需另选接班人，请重新登记交班。',
            fields: [memo('reason', '撤回原因', true, { maxLength: 1000 })],
            submitLabel: '确认撤回',
            onSubmit: ({ reason }) =>
              ctx.command('care.withdrawHandover', { handoverId: row.id, reason }),
          });
          confirmation.dataset.pendingHandoverId = row.id;
        })
      );
    }
  }
}

export function handovers(ctx) {
  const rows = byRecent(ctx.state.handovers);
  return table(ctx, {
    title: '交班记录',
    rows,
    action: btn(ctx, '登记交班', (event) => create(ctx, event.currentTarget)),
    search: {
      placeholder: '搜索长者、交接人员或要点',
      value: (r) =>
        [subject(ctx, r), r.senderName, r.assignee, r.note, r.receiptNote, r.withdrawReason].join(
          ' '
        ),
    },
    filter: {
      label: '交班筛选',
      all: '全部交班',
      options: ['待我签收', '待签收', '已签收', '已撤回', '历史记录'],
      initial: rows.some((r) => mine(ctx, r)) ? '待我签收' : '',
      matches: (r, choice) => (choice === '待我签收' ? mine(ctx, r) : statusOf(r) === choice),
    },
    cols: [
      { label: '交班时间', view: (r) => named(r.date, r.createdAt?.slice(11, 16)) },
      { label: '交接范围', view: (r) => subject(ctx, r) },
      { label: '交班人', view: (r) => r.senderName || '—' },
      { label: '接班人', view: (r) => r.assignee },
      {
        label: '交接要点',
        view: (r) => (r.note?.length > 36 ? r.note.slice(0, 36) + '…' : r.note || '—'),
      },
      {
        label: '状态',
        view: (r) =>
          badge(ctx, statusOf(r), { 待签收: 'amber', 已签收: 'green' }[statusOf(r)] || 'neutral'),
      },
      {
        label: '操作',
        align: 'end',
        view: (r) => {
          const label = mine(ctx, r)
            ? '核对并签收'
            : r.status === '已签收'
              ? '查看回执'
              : '查看交班';
          return link(ctx, label, () => showHandover(ctx, r));
        },
      },
    ],
    empty: '目前没有交班记录',
  });
}
