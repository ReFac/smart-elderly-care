import { auditActorLabel } from './people-labels.js';
import { node, page, table, named, facts, btn } from './shared.js';

export function activityPage(ctx) {
  const filters = ctx.workspaceState?.auditFilters || {};
  const room = node('input', 'fx-input');
  room.type = 'search';
  room.value = filters.room || '';
  room.placeholder = '房间，如 101';
  const actor = node('input', 'fx-input');
  actor.type = 'search';
  actor.value = filters.actor || '';
  actor.placeholder = '姓名、账号或人员编号';
  const form = node('form', 'fx-table-tools', [
    node('label', 'desk-filter', [node('span', '', '房间'), room]),
    node('label', 'desk-filter', [node('span', '', '操作人'), actor]),
  ]);
  const submit = node('button', 'btn btn-primary', '搜索');
  submit.type = 'submit';
  form.append(submit);
  const reset = node('button', 'btn btn-secondary', '重置');
  reset.type = 'button';
  reset.addEventListener('click', () => {
    room.value = '';
    actor.value = '';
    query(false);
  });
  form.append(reset);
  const body = node('div');
  const more = node('button', 'btn btn-secondary', '加载更早记录');
  more.type = 'button';
  more.hidden = true;
  let next = null,
    seq = 0,
    rows = [],
    appliedRoom = '',
    appliedActor = '';
  async function query(append) {
    const id = ++seq;
    if (!append) {
      next = null;
      rows = [];
      appliedRoom = room.value.trim();
      appliedActor = actor.value.trim();
      if (ctx.workspaceState) ctx.workspaceState.auditFilters = {room:appliedRoom, actor:appliedActor};
    }
    const q = new URLSearchParams({ room: appliedRoom, actor: appliedActor, limit: '50' });
    if (append && next) q.set('before', next);
    more.disabled = true;
    try {
      const result = await ctx.get('/api/activity?' + q);
      if (id !== seq) return;
      rows = rows.concat(result.rows);
      next = result.nextBefore;
      body.replaceChildren(
        table(ctx, {
          title: '操作记录',
          rows,
          cols: [
            { label: '时间', view: (r) => named(r.at.slice(0, 10), r.at.slice(11, 19)) },
            { label: '操作人', view: (r) => named(auditActorLabel(ctx, r, '早期记录'), r.actorLogin || '') },
            {
              label: '房间',
              view: (r) =>
                r.previousRoom && r.previousRoom !== r.room
                  ? r.previousRoom + ' → ' + r.room
                  : r.room || '机构级 / 未登记',
            },
            { label: '变更', view: (r) => named(r.summary, r.action + ' · v' + r.revision) },
            { label:'操作', align:'end', view:r => btn(ctx,'查看记录',() => ctx.detail('操作凭证 · v' + r.revision, facts([
              ['操作时间',r.at], ['操作人',auditActorLabel(ctx,r,'早期记录')], ['账号',r.actorLogin],
              ['业务操作',r.action], ['摘要',r.summary], ['原房间',r.previousRoom], ['房间',r.room],
            ])), 'ghost') },
          ],
          empty: '没有符合条件的操作记录',
        })
      );
      more.hidden = !next;
    } catch (error) {
      if (id === seq) body.replaceChildren(ctx.ui.empty(error.message));
    } finally {
      if (id === seq) more.disabled = false;
    }
  }
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    query(false);
  });
  more.addEventListener('click', () => query(true));
  query(false);
  return page(
    ctx,
    '操作日志',
    '按房间和实际登录人员回溯业务变更。两项留空时显示当前权限范围内的全部记录。',
    null,
    form,
    body,
    more
  );
}
