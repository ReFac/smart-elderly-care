import { badge, canAct, facts, link, memo, named, node, select, table } from './shared.js';

const mine = (ctx, row) => row.status === '待回访' && row.assigneeId === ctx.state.user.id;
const personName = (ctx, row) => ctx.state.residents.find(r => r.id === row.residentId)?.name || row.residentId;

function show(ctx, row) {
  const target = personName(ctx, row);
  const details = facts([
    ['长者', target],
    ['未入住原因', row.reason],
    ['回访人员', row.assignee],
    ['派发人', row.assignedByName],
    ['计划回访日', row.dueDate],
  ]);
  if (mine(ctx, row) && canAct(ctx, 'care.finishTrialFollowup')) {
    return ctx.dialog({
      title: '填写试住回访报告',
      content: details,
      fields: [
        select('method', '回访方式', ['电话', '微信', '面谈', '上门', '其他']),
        select('outcome', '回访结果', ['有再次入住意向', '暂缓入住', '无入住意向', '未能联系', '其他']),
        memo('feedback', '沟通经过与反馈', true, { maxLength: 1000 }),
        memo('nextSteps', '后续安排', true, { maxLength: 1000 }),
      ],
      submitLabel: '核对报告',
      onSubmit: values => ctx.command('care.finishTrialFollowup', { taskId: row.id, ...values }, {
        title: '提交试住回访报告', target,
        fields: [
          ['回访结果', values.outcome], ['沟通经过与反馈', values.feedback], ['后续安排', values.nextSteps],
        ],
      }),
    });
  }
  const body = node('div', 'fx-profile', [details]);
  if (row.report) body.append(facts([
    ['回访方式', row.report.method], ['回访结果', row.report.outcome],
    ['沟通经过与反馈', row.report.feedback], ['后续安排', row.report.nextSteps],
    ['报告人', row.reportedByName], ['提交时间', row.reportedAt.slice(0, 16).replace('T', ' ')],
  ]));
  return ctx.detail('试住回访记录', body);
}

async function reassign(ctx, row) {
  try {
    const query = new URLSearchParams({ residentId: row.residentId });
    const { recipients } = await ctx.get('/api/care/trial-assignees?' + query);
    const choices = recipients.filter(a => a.id !== row.assigneeId).map(a => ({
      value: a.id, label: a.displayName + ' · ' + a.username,
    }));
    if (!choices.length) return ctx.toast('暂无其他有权接手的在岗人员');
    return ctx.dialog({
      title: '改派试住回访',
      fields: [select('assigneeId', '新回访人员', choices)],
      submitLabel: '核对改派',
      onSubmit: ({ assigneeId }) => ctx.command('care.reassignTrialFollowup', { taskId: row.id, assigneeId }, {
        title: '改派试住回访', target: personName(ctx, row),
        fields: [['原负责人', row.assignee], ['新负责人', choices.find(c => c.value === assigneeId).label]],
      }),
    });
  } catch (e) {
    ctx.toast(e.message);
  }
}

export function trialFollowups(ctx) {
  const rows = [...(ctx.state.trialFollowups || [])].reverse();
  return table(ctx, {
    title: '试住回访', rows, empty: '暂无需要跟进的试住回访',
    filter: {
      label: '回访进度', all: '全部回访', options: ['待我回访', '待回访', '已回访'],
      initial: rows.some(r => mine(ctx, r)) ? '待我回访' : '',
      matches: (r, choice) => choice === '待我回访' ? mine(ctx, r) : r.status === choice,
    },
    cols: [
      { label: '长者', view: r => named(personName(ctx, r), r.reason) },
      { label: '回访人员', view: r => r.assignee },
      { label: '计划回访日', view: r => r.dueDate },
      { label: '进度', view: r => badge(ctx, r.status, r.report ? 'green' : 'amber') },
      {
        label: '操作', view: r => node('div', 'fx-actions', [
          link(ctx, mine(ctx, r) ? '填写报告' : '查看记录', () => show(ctx, r)),
          r.status === '待回访' && canAct(ctx, 'care.reassignTrialFollowup')
            ? link(ctx, '改派', () => reassign(ctx, r)) : null,
        ]),
      },
    ],
  });
}
