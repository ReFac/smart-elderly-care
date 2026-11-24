import { auditActorLabel } from './people-labels.js';
import { node, page, table, named } from './shared.js';

export function activityPage(ctx) {
  const room = node('input', 'fx-input');
  room.placeholder = '房间，如 101';
  const actor = node('input', 'fx-input');
  actor.placeholder = '姓名、账号或人员编号';
  const form = node('form', 'audit-filter', [
    node('label', 'field', [node('span', '', '房间'), room]),
    node('label', 'field', [node('span', '', '操作者'), actor]),
  ]);
  const submit = node('button', 'btn btn-primary', '查询日志');
  submit.type = 'submit';
  form.append(submit);
  const reset = node('button', 'btn btn-secondary', '清除筛选');
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
          title: '业务变更记录',
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
