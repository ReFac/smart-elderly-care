import { commentInput } from '../lib/change-review.js';
import { node, table, named, badge, btn, link, choose } from './shared.js';
import { showHandover } from './handovers.js';

const statuses = {
  awaiting_approval: '待确认',
  published: '已发布',
  cancelled: '已取消',
};
const names = {coordinator:'机构简报', care:'日常照护', inventory:'物资', finance:'财务'};
const statusBadge = (ctx, status) =>
  badge(
    ctx,
    statuses[status],
    { awaiting_approval: 'amber', published: 'green', cancelled: 'neutral' }[status],
  );

export async function showRun(ctx, row) {
  let data;
  try {
    data = await ctx.get('/api/agent/runs/' + row.id);
  } catch (error) {
    ctx.toast(error.message);
    return;
  }
  const results = node('div', 'agent-artifacts');
  for (const a of data.artifacts) {
    const sources = node('details', 'agent-evidence');
    sources.append(node('summary', '', '查看依据（' + a.evidence.length + ' 项）'));
    for (const item of a.evidence) {
      const entry = node('div', 'agent-source', [
        node('strong', '', item.label),
        ' · ' + item.value,
      ]);
      if (a.tool === 'handover.pending' && item.recordIds.length) {
        for (const id of item.recordIds) {
          const handover = ctx.state.handovers.find((r) => r.id === id);
          if (!handover || handover.assigneeId !== ctx.state.user.id) {
            entry.append(node('small', '', id));
            continue;
          }
          const label = ['核对交班', handover.date, handover.senderName, id.slice(-6)].join(' · ');
          entry.append(
            link(ctx, label, async () => {
              try {
                const row = await ctx.get('/api/agent/runs/' + data.id + '/handovers/' + id);
                if (dialog.open) {
                  dialog.close();
                  showHandover(ctx, row);
                }
              } catch (error) {
                ctx.toast(error.message);
              }
            }),
          );
        }
      } else entry.append(node('small', '', item.recordIds.join('、') || '本期无单据'));
      sources.append(entry);
    }
    results.append(
      node('article', 'agent-artifact', [
        node('small', '', names[a.agent]),
        node('h3', '', a.title),
        node('p', '', a.detail),
        sources,
      ]),
    );
  }
  const body = node('div', 'fx-profile', [
    node('div', 'agent-run-heading', [
      statusBadge(ctx, data.status),
      node('strong', '', data.goal),
    ]),
    node(
      'p',
      'fx-muted',
      data.actorName +
        ' · ' +
        data.started.slice(0, 16).replace('T', ' ') +
        ' · 来源数据版本 ' +
        data.sourceRevision,
    ),
    ...(data.region
      ? [
          node('p', 'agent-region', [
            ctx.ui.icon('location', 15),
            '资料范围 · ' + data.region.label,
          ]),
        ]
      : []),
    results,
  ]);
  const dialog = ctx.detail('历史简报', body);
  if (data.status === 'awaiting_approval') {
    dialog.dataset.agentRunId = data.id;
    const comment = commentInput();
    const publish = btn(
      ctx,
      '确认发布到建议台账',
      () =>
        ctx.command(
          'agent.publish',
          { runId: data.id },
          { confirmed: true, comment: comment.read() },
        ),
      'primary',
    );
    const cancel = btn(ctx, '取消此任务', () => ctx.command('agent.cancel', { runId: data.id }));
    body.append(
      node(
        'p',
        'agent-confirm-note',
        '确认后将以上草稿逐项写入建议台账，保留来源单据与简报编号。',
      ),
      comment.element,
      choose(cancel, publish),
    );
  }
}

export function roomTasks(ctx, roomId, roomLabel) {
  const title = node('summary', '', '本房间可提交变更的工单');
  const body = node('div', 'agent-targets');
  const details = node('details', 'agent-target-list', [title, body]);
  let loaded = false;
  async function load(offset = 0) {
    try {
      const response = await ctx.get(
        '/api/agent/room-context?' + new URLSearchParams({ roomId, offset: String(offset) }),
      );
      if (!offset) body.replaceChildren();
      if (!response.targets.length && !offset)
        body.append(node('p', 'fx-muted', '本房间暂无可申请完成的到期工单。'));
      for (const target of response.targets) {
        const act = ctx.ui.button(
          '拟写执行记录',
          () => {
            const requestId = Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) =>
              b.toString(16).padStart(2, '0'),
            ).join('');
            ctx.dialog({
              title: '提交区域工单草稿',
              description:
                roomLabel + ' · ' + target.label + '。提交后由授权人员核对。',
              fields: [
                {
                  name: 'note',
                  label: '拟写入的执行记录',
                  type: 'textarea',
                  required: true,
                  maxLength: 1000,
                },
              ],
              submitLabel: '提交人工确认',
              onSubmit: (v) =>
                ctx.proposeRoom({
                  roomId,
                  taskId: target.id,
                  note: v.note,
                  requestId,
                }),
            });
          },
          'text',
        );
        body.append(
          node('div', 'agent-target', [node('span', '', target.date + ' · ' + target.label), act]),
        );
      }
      if (response.nextOffset != null) {
        const more = ctx.ui.button('加载更多', () => {
          more.remove();
          load(response.nextOffset);
        });
        body.append(more);
      }
      loaded = true;
    } catch (error) {
      ctx.toast(error.message);
    }
  }
  details.addEventListener('toggle', () => {
    if (details.open && !loaded) load();
  });
  return details;
}


export function priorReports(ctx) {
  return table(ctx, {
    title: '历史简报',
    rows: ctx.state.agentRuns || [],
    search: {
      placeholder: '搜索任务目标或发起人',
      value: (r) => r.goal + ' ' + r.actorName,
    },
    filter: { value: (r) => statuses[r.status] },
    empty: '暂无历史简报。',
    cols: [
      {
        label: '任务目标',
        view: (r) => named(r.goal, r.agents.map((a) => names[a]).join('、')),
      },
      { label: '发起人', view: (r) => r.actorName },
      {
        label: '发起时间',
        view: (r) => r.started.slice(0, 16).replace('T', ' '),
      },
      { label: '状态', view: (r) => statusBadge(ctx, r.status) },
      {
        label: '操作',
        align: 'end',
        view: (r) =>
          link(ctx, r.status === 'awaiting_approval' ? '核对简报' : '查看记录', () =>
            showRun(ctx, r),
          ),
      },
    ],
  });
}
