import { residentLabel, staffLabel } from './people-labels.js';
import { editResident } from './profile-editor.js';
import { badge, btn, canAct, choose, facts, field, memo, node, select } from './shared.js';

const endpoint = '/api/permission-requests';
const scopeLabel = '编辑长者登记资料';
const statusLabels = {
  pending: ['待审批', 'amber'],
  approved: ['可办理', 'blue'],
  rejected: ['未通过', 'neutral'],
  expired: ['已到期', 'neutral'],
  used: ['已办理', 'green'],
};
const closedStatuses = new Set(['已退住', '归档', '已归档', '已出院', '归档到期']);
const formatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});

export function canOpenPermissionRequests(ctx) {
  return ['owner', 'staff'].includes(ctx.state.user?.kind);
}

export function pendingPermissionRequests(ctx) {
  return ctx.state.pendingPermissionRequests || 0;
}

function dateLabel(value) {
  if (!value) return '';
  const date = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value);
  return Number.isNaN(date.valueOf()) ? value : formatter.format(date).replaceAll('/', '-');
}

function targetLabel(ctx, request) {
  const resident = ctx.state.residents.find(row => row.id === request.residentId);
  if (resident) return residentLabel(ctx, resident);
  const location = request.room ? '（' + request.room + '）' : '';
  return request.residentName ? request.residentName + location : '档案 ' + request.residentId;
}

function employeeLabel(ctx, name, id, role) {
  return staffLabel(ctx, { displayName: name, id, role });
}

function approveForm(ctx, request, decision, expectedRevision, afterSave) {
  const approve = decision === 'approve';
  const caption = approve ? '签名并批准' : '签名并驳回';
  const dialog = ctx.dialog({
    title: approve ? '批准权限申请' : '驳回权限申请',
    content: node('div', 'permission-scope', [
      facts([
        ['申请人', employeeLabel(ctx, request.requesterName, request.requesterId, request.requesterRole)],
        ['授权档案', targetLabel(ctx, request)],
        ['允许操作', scopeLabel],
        ...(approve ? [['授权期限', '批准后 24 小时内可保存一次']] : []),
      ]),
      node('div', 'permission-reason', [node('strong', '', '申请事由'), node('p', '', request.reason)]),
    ]),
    description: approve
      ? '签名将与本人的账号及审批时间一同留存。请核对档案和授权范围。'
      : '签名后提交驳回结果。可附上处理意见供申请人查看。',
    fields: [
      memo('note', '审批意见（选填）', false, { maxLength: 300 }),
      field('signature', '本人实名签名', { maxLength: 60, placeholder: '输入机构登记的本人姓名' }),
      field('currentPassword', '当前登录密码', { type: 'password', maxLength: 128 }),
    ],
    submitLabel: caption,
    onSubmit: async values => {
      const live = ctx.current?.() || ctx;
      const saved = await live.command('permissionRequest.review', {
        requestId: request.id, decision, signature: values.signature.trim(),
        currentPassword: values.currentPassword, note: values.note.trim(),
      }, { confirmed: true, quiet: true, expectedRevision });
      if (!saved) return false;
      live.toast(approve ? '已签名批准权限申请' : '已签名驳回权限申请');
      afterSave?.();
      return true;
    },
  });
  dialog.classList.add('permission-request-form');
  dialog.querySelector('[name=currentPassword]').autocomplete = 'current-password';
  dialog.querySelector('[name=signature]').autocomplete = 'off';
  dialog.querySelector('[name=signature]').focus();
}

async function openApprovedProfile(ctx, request, trigger) {
  trigger.disabled = true;
  try {
    const live = ctx.current?.() || ctx;
    const { resident, basic, revision } = await live.get(endpoint + '/' + encodeURIComponent(request.id) + '/profile');
    if (!trigger.isConnected) return;
    await editResident(live, resident, basic, {
      requestId: request.id,
      revision,
      target: targetLabel(live, request),
      description: '本次授权仅可保存一回登记资料，有效至 ' + dateLabel(request.expiresAt) + '。',
    });
  } catch (error) {
    ctx.toast(error.message);
  } finally {
    trigger.disabled = false;
  }
}

function resultCard(ctx, request, direction, revision, afterSave) {
  const [label, tone] = statusLabels[request.status];
  const counterpart = direction === 'received'
    ? ['申请人', request.requesterName, request.requesterId, request.requesterRole]
    : ['审批人', request.approverName, request.approverId, request.approverRole];
  const details = [
    [counterpart[0], employeeLabel(ctx, ...counterpart.slice(1))],
    ['发起于', dateLabel(request.requestedAt)],
    ...(request.expiresAt && request.status === 'approved' ? [['有效至', dateLabel(request.expiresAt)]] : []),
    ...(request.decidedAt ? [['审批时间', dateLabel(request.decidedAt)]] : []),
    ...(request.signature ? [['电子签名', request.signature]] : []),
    ...(request.usedAt ? [['办理于', dateLabel(request.usedAt)]] : []),
  ];
  const actions = choose();
  if (request.canReview) actions.append(
    btn(ctx, '驳回', () => approveForm(ctx, request, 'reject', revision, afterSave)),
    btn(ctx, '批准', () => approveForm(ctx, request, 'approve', revision, afterSave), 'primary'),
  );
  if (request.canEdit) {
    const edit = btn(ctx, '打开登记资料', () => openApprovedProfile(ctx, request, edit), 'primary');
    actions.append(edit);
  }
  return node('article', 'permission-request-card', [
    node('div', 'permission-card-head', [
      node('span', 'permission-card-mark', ctx.ui.icon('shield', 19)),
      node('div', 'permission-card-title', [
        node('h3', '', targetLabel(ctx, request)), node('p', '', scopeLabel),
      ]),
      badge(ctx, label, tone),
    ]),
    facts(details),
    node('div', 'permission-reason', [node('strong', '', '申请事由'), node('p', '', request.reason)]),
    request.decisionNote ? node('div', 'permission-reason', [
      node('strong', '', '审批意见'), node('p', '', request.decisionNote),
    ]) : null,
    actions.childElementCount ? actions : null,
  ]);
}

function requestTarget(ctx, initial) {
  if (initial) return {
    element: facts([['授权档案', residentLabel(ctx, initial)], ['允许操作', scopeLabel]]),
    read: () => initial.id,
  };
  const selector = node('select');
  selector.required = true;
  selector.add(new Option('请选择档案', ''));
  for (const row of ctx.state.residents.filter(row => !closedStatuses.has(row.status)))
    selector.add(new Option(residentLabel(ctx, row) + ' · ' + row.id, row.id));
  selector.add(new Option('输入其他档案编号', 'other'));
  const input = node('input');
  input.type = 'text';
  input.maxLength = 100;
  input.autocomplete = 'off';
  input.placeholder = '完整档案编号';
  const manual = node('label', 'field', [node('span', '', '档案编号'), input]);
  function sync() {
    const active = selector.value === 'other';
    manual.hidden = !active;
    input.disabled = !active;
    input.required = active;
  }
  selector.addEventListener('change', sync);
  sync();
  return {
    element: node('div', 'permission-target', [
      facts([['允许操作', scopeLabel]]),
      node('label', 'field', [node('span', '', '授权档案'), selector]),
      manual,
    ]),
    read: () => selector.value === 'other' ? input.value.trim() : selector.value,
  };
}

export async function openPermissionRequest(ctx, resident, knownData) {
  try {
    const data = knownData || await ctx.get(endpoint);
    if (resident && data.sent?.some(row => row.residentId === resident.id && (row.status === 'pending' || row.canEdit))) {
      openPermissionRequests(ctx.current?.() || ctx, 'sent');
      return;
    }
    const { approvers, revision } = data;
    if (!approvers.length) {
      ctx.detail('申请权限', ctx.ui.empty('当前没有可选的审批人，请联系机构管理员安排。'));
      return;
    }
    const target = requestTarget(ctx, resident);
    const dialog = ctx.dialog({
      title: '申请编辑权限',
      content: node('div', 'permission-scope', target.element),
      description: '请选择有权处理该档案的人员并说明事由。审批通过后可编辑并保存一次登记资料。',
      fields: [
        select('approverId', '指定审批人', [
          { value: '', label: '请选择审批人' },
          ...approvers.map(person => ({
            value: person.id,
            label: employeeLabel(ctx, person.name, person.id, person.role) + (person.username ? ' · ' + person.username : ''),
          })),
        ]),
        memo('reason', '申请事由', true, { maxLength: 300, placeholder: '例如代班时发现本人手机号需要更正。' }),
      ],
      submitLabel: '发送申请',
      onSubmit: async values => {
        const live = ctx.current?.() || ctx;
        const residentId = target.read();
        if (!residentId) throw new Error('请选择长者或填写完整档案编号。');
        const saved = await live.command('permissionRequest.create', {
          residentId, approverId: values.approverId, reason: values.reason.trim(),
        }, { confirmed: true, quiet: true, expectedRevision: revision });
        if (saved) {
          live.toast('权限申请已发送');
          openPermissionRequests(ctx.current?.() || ctx, 'sent');
        }
        return saved;
      },
    });
    dialog.classList.add('permission-request-form');
    dialog.querySelector('form select')?.focus();
  } catch (error) {
    ctx.toast(error.message);
  }
}

export function permissionRequestsPanel(ctx, requestedSection, afterSave) {
  const shell = node('div', 'permission-workbench');
  const list = node('div', 'permission-card-list');
  const loading = node('p', 'permission-load-status', '正在载入权限申请…');
  loading.setAttribute('role', 'status');
  shell.append(loading);
  async function load() {
    const live = ctx.current?.() || ctx;
    try {
      const data = await live.get(endpoint);
      const { sent, received, canReview, revision } = data;
      if (!shell.isConnected) return;
      const pending = received.filter(request => request.status === 'pending');
      const history = received.filter(request => request.status !== 'pending');
      const views = [
        ...(canReview || received.length ? [
          ['review', '待我审批', 'received', pending, '暂无待你审批的申请。'],
          ['handled', '审批记录', 'received', history, '暂无已处理的申请。'],
        ] : []),
        ['sent', '我发出的', 'sent', sent, '暂无已发出的申请。'],
      ];
      const bar = node('div', 'permission-views');
      bar.setAttribute('role', 'group');
      bar.setAttribute('aria-label', '权限申请分类');
      function show(view) {
        requestedSection = view[0];
        for (const button of bar.children)
          button.setAttribute('aria-pressed', String(button.dataset.view === view[0]));
        list.replaceChildren(...(view[3].length
          ? view[3].map(request => resultCard(live, request, view[2], revision, () => {
            if (afterSave) afterSave('handled');
            else if (shell.isConnected) load();
          }))
          : [live.ui.empty(view[4])]));
      }
      for (const view of views) {
        const button = btn(live, view[1] + (view[0] === 'review' && pending.length ? ' ' + pending.length : ''),
          () => show(view), 'ghost');
        button.dataset.view = view[0];
        bar.append(button);
      }
      const create = canAct(live, 'permissionRequest.create')
        ? btn(live, '申请编辑权限', () => openPermissionRequest(live, null, data), 'primary') : null;
      const refresh = btn(live, '刷新', async () => {
        refresh.disabled = true;
        try { await load(); } finally { refresh.disabled = false; }
      });
      const notice = pending.length && !canReview
        ? node('p', 'permission-load-status', '请联系 Owner 核对本账号的签名实名后，再处理待审批申请。') : null;
      shell.replaceChildren(node('div', 'permission-toolbar', [bar, choose(refresh, create)]), notice || '', list);
      show(views.find(view => view[0] === requestedSection) || (pending.length ? views[0] : views.at(-1)));
    } catch (error) {
      if (!shell.isConnected) return;
      shell.replaceChildren(node('p', 'form-error', error.message), btn(live, '重新载入', load));
    }
  }
  load();
  return shell;
}

export function openPermissionRequests(ctx, initialSection) {
  if (!canOpenPermissionRequests(ctx)) return;
  const dialog = ctx.detail('权限申请', permissionRequestsPanel(ctx, initialSection, section =>
    openPermissionRequests(ctx.current?.() || ctx, section)));
  dialog.classList.add('permission-requests-dialog');
}
