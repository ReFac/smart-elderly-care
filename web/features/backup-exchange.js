import { node, btn } from './shared.js';

export async function request(path, payload) {
  const response = await fetch(
    '/api/backups' + path,
    payload === undefined
      ? { cache: 'no-store' }
      : {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
  );
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '备份操作未完成');
  return data;
}

function textSize(value) {
  return (value / 1048576).toFixed(2) + ' MiB';
}
function facts(items) {
  const list = node('dl', 'backup-facts');
  for (const [name, value] of items) list.append(node('dt', '', name), node('dd', '', value));
  return list;
}

function differences(view) {
  const body = node('div', 'backup-preview', [
    facts([
      ['来源业务版本', String(view.sourceRevision)],
      ['当前业务版本', String(view.currentRevision)],
      [
        '来源内容',
        view.residents + ' 位长者 · ' + view.staff + ' 名员工 · ' + view.documents + ' 份医疗原件',
      ],
    ]),
  ]);
  if (view.changes.length) {
    const table = node('table', 'fx-table');
    table.append(
      node(
        'thead',
        '',
        node(
          'tr',
          '',
          ['有差异的内容', '当前数量', '来源数量'].map((x) => node('th', '', x)),
        ),
      ),
    );
    table.append(
      node(
        'tbody',
        '',
        view.changes.map((row) =>
          node(
            'tr',
            '',
            [row.label, row.current, row.incoming].map((x) => node('td', '', String(x))),
          ),
        ),
      ),
    );
    body.append(node('div', 'backup-differences', table));
  } else body.append(node('p', 'fx-muted', '可恢复的业务内容与当前记录一致。'));
  if (view.blockers.length)
    body.append(
      node(
        'p',
        'fx-attention',
        '完整快照可导入收藏。在线覆盖受以下记录保护：' + view.blockers.join('、') + '。',
      ),
    );
  return body;
}

export function settings(panel, data, labels) {
  const ctx = panel.ctx;
  const wrapper = node('section', 'backup-settings-form');
  const field = (label, select) => node('label', 'field', [node('span', '', label), select]);
  const choices = (items, current) => {
    const select = node('select');
    for (const [value, title] of items) {
      select.add(new Option(title, value));
    }
    select.value = String(current);
    return select;
  };
  const keep = choices(
    [[0, '长期保留'], ...[60, 90, 180, 365].map((v) => [v, v + ' 天'])],
    data.policy.retentionDays,
  );
  const limit = choices(
    [64, 256, 1024, 4096].map((v) => [v, v + ' MiB']),
    data.policy.uploadLimitMiB,
  );
  wrapper.append(
    facts([
      ['自动备份', '北京时间 00:00'],
      ['变更回溯', '60 天'],
    ]),
    field('本机完整快照保留期', keep),
    node('p', 'fx-muted', '到期后的本机副本仅在已校验异地副本、且有更新的恢复点时释放。'),
    field('网页单次导入上限', limit),
    node('h3', '', '异地副本位置'),
  );
  const targets = node('div', 'backup-targets');
  for (const target of data.locations) {
    const current = target.state === 'linked';
    const parts = [
      node('div', '', [node('strong', '', target.label), node('small', '', labels[target.state])]),
    ];
    if (current || target.available || target.state === 'changed') {
      const controls = node('div', 'backup-controls');
      if (!current && target.available)
        controls.append(btn(ctx, '连接', () => updateLocation(target, '/locations', '连接')));
      if (current || target.state === 'changed')
        controls.append(
          btn(ctx, '停止配送', () => updateLocation(target, '/locations/unlink', '停止配送')),
        );
      parts.push(controls);
    }
    targets.append(node('div', 'backup-target', parts));
  }
  wrapper.append(targets);
  if (data.configError) wrapper.append(node('p', 'fx-attention', data.configError));
  const save = btn(
    ctx,
    '保存备份设置',
    async () => {
      const confirmation = await ctx.confirmChange({
        title: '保存备份设置',
        target: '机构备份策略',
        fields: [
          ['本机保留', keep.selectedOptions[0].text],
          ['导入上限', limit.selectedOptions[0].text],
        ],
        confirmLabel: '保存设置',
        allowComment: true,
      });
      if (!confirmation) return;
      try {
        await request('/settings', {
          retentionDays: Number(keep.value),
          uploadLimitMiB: Number(limit.value),
          version: data.policy.version,
          comment: confirmation.comment,
        });
        dialog.close();
        ctx.toast('备份策略已保存');
        await panel.refresh();
      } catch (error) {
        ctx.toast(error.message);
      }
    },
    'primary',
  );
  wrapper.append(node('div', 'dialog-actions', save));
  const dialog = ctx.detail('备份设置', wrapper);
  async function updateLocation(target, path, title) {
    const confirmed = await ctx.confirmChange({
      title: title + '异地备份',
      target: target.label,
      fields: [['操作', title]],
      confirmLabel: title,
      allowComment: true,
    });
    if (!confirmed) return;
    try {
      await request(path, { provider: target.id, comment: confirmed.comment });
      dialog.close();
      ctx.toast('异地配送设置已更新');
      await panel.refresh();
    } catch (error) {
      ctx.toast(error.message);
    }
  }
}

export function importDialog(panel, policy) {
  const ctx = panel.ctx,
    input = node('input');
  input.type = 'file';
  input.accept = '.akbak,application/octet-stream';
  const status = node('p', 'fx-muted', '选择本机构导出的 .akbak 文件，先在隔离目录核对内容。');
  const preview = node('div', '');
  const wrap = node('div', 'backup-settings-form', [
    node('label', 'field', [node('span', '', '加密备份文件'), input]),
    status,
    preview,
  ]);
  const dialog = ctx.detail('导入加密备份', wrap);
  let seq = 0;
  input.onchange = async () => {
    const file = input.files[0],
      serial = ++seq;
    preview.replaceChildren();
    if (!file) return;
    if (file.size > policy.uploadLimitMiB * 1048576) {
      status.textContent = '文件超过当前单次导入上限 ' + policy.uploadLimitMiB + ' MiB';
      return;
    }
    status.textContent = '正在核验密文和数据库页…';
    try {
      const resp = await fetch('/api/backups/imports/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: file,
      });
      const view = await resp.json();
      if (!resp.ok) throw new Error(view.error);
      if (serial !== seq || !dialog.open) return;
      status.textContent = file.name + ' · ' + textSize(file.size) + ' · 已通过完整性核验';
      const save = btn(
        ctx,
        '导入快照库',
        async () => {
          const c = await ctx.confirmChange({
            title: '导入完整加密快照',
            target: file.name,
            fields: [
              ['业务版本', String(view.sourceRevision)],
              ['写入位置', '机构快照库，当前业务记录继续使用'],
            ],
            confirmLabel: '确认导入',
            allowComment: true,
          });
          if (!c) return;
          save.disabled = true;
          try {
            const result = await request('/imports/' + view.id + '/confirm', {
              comment: c.comment,
            });
            dialog.close();
            await panel.showLatest();
            ctx.toast('已导入快照库');
            await managePoint(panel, result.point);
          } catch (error) {
            ctx.toast(error.message);
            save.disabled = false;
          }
        },
        'primary',
      );
      preview.append(differences(view), node('div', 'dialog-actions', save));
    } catch (error) {
      if (serial === seq) status.textContent = error.message || '无法导入此备份';
    }
  };
}

export async function exportPoint(panel, id) {
  const ctx = panel.ctx;
  const choice = await ctx.confirmChange({
    title: '导出加密快照',
    target: id,
    fields: [
      ['导出范围', '整家机构、全部分院及已归档原件'],
      ['文件格式', '.akbak 加密文件'],
    ],
    confirmLabel: '导出文件',
    allowComment: true,
  });
  if (!choice) return;
  const receipt = await request('/points/' + id + '/export', { comment: choice.comment });
  const link = node('a');
  link.href = receipt.url;
  link.download = receipt.filename;
  document.body.append(link);
  link.click();
  link.remove();
  ctx.toast('已开始下载加密快照');
}

export async function managePoint(panel, id) {
  const ctx = panel.ctx;
  const view = await request('/points/' + id + '/preview', {});
  const wrapper = differences(view);
  wrapper.append(
    node('p', 'fx-muted', '应用时将保留当前账号授权、审计和套餐，系统先保存完整回退点。'),
  );
  const button = btn(
    ctx,
    '应用到当前工作库',
    async () => {
      const choice = await ctx.confirmChange({
        title: '应用备份到当前工作库',
        target: '当前机构全部分院',
        fields: [
          ['业务版本', String(view.currentRevision) + ' → 来源 ' + view.sourceRevision],
          ['将更新', view.changes.map((r) => r.label).join('、')],
          ['回退方式', '在本机保留执行前的完整加密快照'],
        ],
        confirmLabel: '确认恢复',
        allowComment: true,
      });
      if (!choice) return;
      button.disabled = true;
      try {
        const result = await request('/points/' + id + '/apply', {
          revision: view.currentRevision,
          approval: view.approval,
          confirmed: true,
          comment: choice.comment,
        });
        dialog.close();
        await panel.showLatest();
        ctx.toast('已应用，业务修订 ' + result.revision + '；可从恢复前保护点回退。');
      } catch (error) {
        ctx.toast(error.message);
        button.disabled = false;
      }
    },
    'primary',
  );
  button.disabled = Boolean(view.blockers.length) || !view.changes.length;
  wrapper.append(node('div', 'dialog-actions', button));
  const dialog = ctx.detail('核对恢复内容', wrapper);
}
