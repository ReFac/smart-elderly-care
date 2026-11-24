import { voiceBar } from './agent-voice.js';
import { commentInput } from '../lib/change-review.js';
import { node, table, named, badge, btn, link, choose } from './shared.js';
import { showHandover } from './handovers.js';

const statuses = {
  awaiting_approval: '待确认',
  published: '已发布',
  cancelled: '已取消',
};
const names = {
  coordinator: '协调 Agent',
  care: '照护 Agent',
  inventory: '物资 Agent',
  finance: '运营 Agent',
};
const icons = { care: 'care', inventory: 'box', finance: 'chart' };
const events = {
  'run.started': '接单',
  'region.selected': '锁定区域',
  'planner.selected': '选择规划器',
  'plan.created': '拟定计划',
  handoff: '分派任务',
  'tool.called': '读取工具',
  'artifact.created': '形成草稿',
  'approval.requested': '请求确认',
  'run.published': '人工发布',
  'run.cancelled': '人工取消',
};
const example = {
  care: '核对当班照护工单',
  inventory: '检查耗材补货',
  finance: '复核欠费账单',
};
const statusBadge = (ctx, status) =>
  badge(
    ctx,
    statuses[status],
    { awaiting_approval: 'amber', published: 'green', cancelled: 'neutral' }[status],
  );

function composer(ctx, tools) {
  const form = node('form', 'agent-compose agent-voicebar');
  const settings = node('section', 'agent-options');
  const input = node('textarea', 'agent-goal');
  input.name = 'goal';
  input.maxLength = 500;
  input.required = true;
  input.rows = 2;
  input.placeholder = '例如：整理本班交接，核对照护工单、耗材库存和欠费账单';
  const title = node('h2', 'agent-prompt-label', [
    ctx.ui.icon('spark', 21),
    node('strong', '', '今天要处理什么？'),
  ]);
  input.setAttribute('aria-label', '给 Agent 的任务');
  input.id = 'agent-goal';
  const examples = node('div', 'agent-examples');
  function addExample(agent, goal) {
    const b = node('button', 'agent-example', [ctx.ui.icon(icons[agent], 14), goal]);
    b.type = 'button';
    b.addEventListener('click', () => {
      dock.write(goal);
    });
    examples.append(b);
  }
  for (const t of tools) addExample(t.agent, example[t.agent]);
  if (tools.some((t) => t.optionalTools?.some((tool) => tool.id === 'finance.revenue')))
    addExample('finance', '本月实收多少');
  if (tools.some((t) => t.optionalTools?.some((tool) => tool.id === 'handover.pending')))
    addExample('care', '查看我待签收的交班');
  if (
    tools.some((t) => t.optionalTools?.some((tool) => tool.id === 'care.planDraft')) &&
    (!ctx.agentRegion || ctx.agentRegion.roomId)
  )
    addExample('care', '生成健康照护计划');
  const scope = node('select', 'fx-input');
  scope.setAttribute('aria-label', '委派范围');
  scope.add(new Option('自动分派', 'auto'));
  for (const t of tools) scope.add(new Option(names[t.agent], t.agent));
  const resident = node('select', 'fx-input');
  resident.setAttribute('aria-label', '照护对象');
  let wantedResident = '';
  const canChooseResident =
    tools.some((t) => t.agent === 'care') && (!ctx.agentRegion || ctx.agentRegion.roomId);
  resident.add(new Option(ctx.agentRegion ? '本区全部长者' : '全院照护', ''));
  if (canChooseResident && ctx.agentRegion) {
    ctx
      .get('/api/facility/rooms/' + encodeURIComponent(ctx.agentRegion.roomId))
      .then((room) => {
        for (const bed of room.beds.filter((b) => b.residentId))
          resident.add(new Option(bed.residentName + ' · ' + bed.residentId, bed.residentId));
        if (wantedResident) resident.value = wantedResident;
      })
      .catch((error) => ctx.toast(error.message));
  } else if (canChooseResident) {
    for (const r of ctx.state.residents.filter((r) => r.status === '在住'))
      resident.add(new Option(r.name + ' · ' + r.id, r.id));
  } else resident.hidden = true;
  scope.addEventListener('change', () => {
    resident.hidden = !canChooseResident || !['auto', 'care'].includes(scope.value);
    if (resident.hidden) resident.value = '';
  });
  const start = node('button', 'btn btn-primary', [ctx.ui.icon('send', 18), '发送']);
  start.type = 'submit';
  const plan = ctx.state.agentCapabilities.plan;
  const mode = node('select', 'fx-input');
  mode.setAttribute('aria-label', '规划方式');
  mode.add(new Option('本地 · 节省额度', 'local'));
  if (plan?.available) mode.add(new Option('平台 AI · 按用量', 'platform'));
  const controls = node('div', 'agent-controls', [scope, resident, mode]);
  const selectedRegion = Object.fromEntries(
    Object.entries(ctx.agentRegion || {}).filter(([key]) => key !== 'label'),
  );
  const dock = voiceBar(ctx, form, input, start, selectedRegion, {
    read: () => ({
      scope: scope.value,
      resident: resident.value,
      mode: mode.value,
    }),
    restore(saved) {
      scope.value = saved.scope;
      scope.dispatchEvent(new Event('change'));
      mode.value = saved.mode;
      if (!resident.hidden) {
        wantedResident = saved.resident;
        if (wantedResident) resident.value = wantedResident;
      }
    },
  });
  let requestId;
  const freshId = () =>
    Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) =>
      b.toString(16).padStart(2, '0'),
    ).join('');
  settings.addEventListener('change', () => {
    requestId = undefined;
    form.dispatchEvent(new Event('input', { bubbles: true }));
  });
  form.addEventListener('input', () => {
    requestId = undefined;
  });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (start.disabled || !dock.canSend()) return;
    if (!input.value.trim()) {
      input.focus();
      return;
    }
    requestId ||= freshId();
    start.disabled = true;
    try {
      const result = await ctx.command(
        'agent.start',
        {
          goal: input.value.trim(),
          requestId,
          scope: scope.value,
          planning: mode.value,
          residentId: resident.value,
          ...(ctx.agentRegion ? { region: selectedRegion } : {}),
          ...(dock.receipt() ? { voiceTranscriptId: dock.receipt() } : {}),
        },
        {
          title: '确认发送给协调 Agent',
          target: ctx.agentRegion?.label || ctx.state.uiSettings.institutionName,
          fields: [
            ['任务', input.value.trim()],
            ['委派', scope.selectedOptions[0].textContent],
            ...(resident.value ? [['长者', resident.selectedOptions[0].textContent]] : []),
            ['规划', mode.selectedOptions[0].textContent],
            ['结果', '生成可核对的任务简报；发布建议须另行确认。'],
          ],
          confirmLabel: '发送并生成简报',
          returnResult: true,
        },
      );
      if (result?.runId && document.querySelector('.agent-voicebar')) {
        await showRun(ctx, { id: result.runId });
      }
    } finally {
      start.disabled = false;
    }
  });
  const region = node('div', 'agent-region');
  region.append(
    ctx.ui.icon('location', 16),
    node('strong', '', ctx.agentRegion?.label || ctx.state.uiSettings.institutionName),
  );
  if (ctx.available('rooms'))
    region.append(
      ctx.ui.button(
        ctx.agentRegion ? '更换区域' : '选择分院、楼层或房间',
        () => ctx.go('beds','plan'),
        'text',
      ),
    );
  if (ctx.hasSelectedRegion) region.append(ctx.ui.button('清除区域', ctx.clearAgentRegion, 'text'));
  settings.append(title, region, examples, controls);
  return { settings, form };
}

function teamPanel(ctx, tools) {
  const panel = node('aside', 'agent-team');
  panel.append(node('h2', '', [ctx.ui.icon('layers', 19), '本次可用团队']));
  for (const tool of tools) {
    panel.append(
      node('div', 'agent-team-row', [
        node('span', 'agent-icon', ctx.ui.icon(icons[tool.agent], 16)),
        node('div', '', [node('strong', '', names[tool.agent]), node('small', '', tool.title)]),
        node('code', '', tool.id),
      ]),
    );
  }
  panel.append(
    node(
      'p',
      'agent-engine',
      ctx.state.agentCapabilities.plan?.available
        ? '本地规则 · 已开通平台 AI'
        : '本地规则 · 云端规划需机构套餐',
    ),
  );
  return panel;
}

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
  const timeline = node('ol', 'agent-trace');
  for (const e of data.events)
    timeline.append(
      node('li', '', [
        node('strong', '', events[e.event] || e.event),
        node('span', '', e.message),
        node('small', '', names[e.agent] + ' · ' + e.at.slice(11, 19)),
      ]),
    );
  const trace = node('details', 'agent-evidence', [
    node('summary', '', '运行轨迹（' + data.events.length + ' 步）'),
    timeline,
  ]);
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
            '运行范围 · ' + data.region.label,
          ]),
        ]
      : []),
    results,
    trace,
  ]);
  const dialog = ctx.detail('协作运行详情', body);
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
        '确认后将以上草稿逐项写入建议台账，保留来源单据与本次运行编号。',
      ),
      comment.element,
      choose(cancel, publish),
    );
  }
}

function roomTasks(ctx, roomId) {
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
                ctx.agentRegion.label + ' · ' + target.label + '。提交后由授权人员核对。',
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

function lastConversation(ctx, run) {
  const reply = node('div', 'agent-chat-reply', [node('small', '', '协调 Agent')]);
  const body = node('p', '', '正在读取上次协作的简报…');
  const open = link(ctx, '查看完整简报', () => showRun(ctx, run));
  reply.append(body, open);
  const panel = node('section', 'agent-conversation', [
    node('div', 'agent-chat-heading', [
      node('h2', '', '最近一次对话'),
      statusBadge(ctx, run.status),
    ]),
    node('div', 'agent-chat-question', [
      node('small', '', run.actorName + ' · ' + run.started.slice(0, 16).replace('T', ' ')),
      node('p', '', run.goal),
    ]),
    reply,
  ]);
  ctx.get('/api/agent/runs/' + run.id).then(
    (answer) => {
      if (!panel.isConnected) return;
      body.textContent = answer.artifacts.map((a) => a.detail).join('\n') || '本次协作已结束。';
    },
    (error) => {
      if (panel.isConnected) body.textContent = error.message;
    },
  );
  return panel;
}

export function agentDesk(ctx) {
  const tools = (ctx.state.agentCapabilities?.tools || []).filter(
    (t) => !ctx.agentRegion || t.agent !== 'inventory',
  );
  const regionKeys = Object.entries(ctx.agentRegion || {}).filter(([k]) => k !== 'label');
  const runs = (ctx.state.agentRuns || []).filter((r) =>
    regionKeys.every(([key, value]) => r.region?.[key] === value),
  );
  const { settings, form } = composer(ctx, tools);
  const home = node('div', 'agent-home', [settings, teamPanel(ctx, tools)]);
  const list = table(ctx, {
    title: '协作任务',
    rows: runs,
    search: {
      placeholder: '搜索任务目标或发起人',
      value: (r) => r.goal + ' ' + r.actorName,
    },
    filter: { value: (r) => statuses[r.status] },
    empty: '暂无协作任务。输入任务目标即可生成第一份待确认简报。',
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
  const targets =
    ctx.agentRegion?.roomId && ctx.state.allowedActions.includes('gw.propose')
      ? roomTasks(ctx, ctx.agentRegion.roomId)
      : null;
  const history = runs.length
    ? node('details', 'agent-target-list', [
        node('summary', '', '协作历史（' + runs.length + '）'),
        list,
      ])
    : list;
  return node('div', 'agent-desk', [
    home,
    targets,
    runs.length ? lastConversation(ctx, runs[0]) : null,
    history,
    form,
  ]);
}
