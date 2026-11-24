import { node, btn } from './shared.js';
import { request, settings, importDialog, exportPoint, managePoint } from './backup-exchange.js';

const dateFormat = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});
const stamp = (value) => (value ? dateFormat.format(value * 1000) : '—');
const states = {
  queued: '等待处理',
  creating: '正在加密',
  ready: '本机已保存',
  damaged: '本机校验失败',
  missing: '本机副本缺失',
  retired: '本机保留期已满',
  recheck: '正在重新校验',
  failed: '等待重试',
  sending: '上传并回读',
  verified: '异地已校验',
};
const locationStates = {
  unconfigured: '等待服务器授权',
  available: '可连接',
  linked: '已连接',
  changed: '需重新核对配置',
};

let pendingPoint = null;
export function openBackupPoint(ctx, id) {
  if (!/^ak-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{32}$/.test(id)) return;
  const current = document.querySelector('backup-panel');
  if (current?.isConnected) managePoint(current, id).catch((error) => ctx.toast(error.message));
  else pendingPoint = { id, actor: ctx.state.user.id };
}

class BackupPanel extends HTMLElement {
  connectedCallback() {
    this.className = 'backup-panel fx-panel';
    this.cursors = [0];
    this.refresh();
    if (pendingPoint) {
      const pending = pendingPoint;
      pendingPoint = null;
      if (pending.actor === this.ctx.state.user.id)
        managePoint(this, pending.id).catch((error) => this.ctx.toast(error.message));
    }
    this.timer = setInterval(() => {
      if (!document.hidden && !this.busy) this.refresh();
    }, 5000);
  }
  disconnectedCallback() {
    clearInterval(this.timer);
  }
  async showLatest() {
    this.cursors = [0];
    this.rendered = null;
    await this.refresh();
  }
  async refresh() {
    if (this.loading) return;
    this.loading = true;
    try {
      const cursor = this.cursors[this.cursors.length - 1];
      const data = await request(cursor ? '?before=' + cursor : '');
      if (cursor !== this.cursors[this.cursors.length - 1]) return;
      if (!this.isConnected) return;
      const signature = JSON.stringify(data);
      if (this.rendered !== signature) {
        this.draw(data);
        this.rendered = signature;
      }
    } catch (error) {
      if (this.isConnected) {
        this.textContent = error.message;
        this.rendered = null;
      }
    } finally {
      this.loading = false;
    }
  }
  action(label, path, payload, primary = false) {
    return btn(
      this.ctx,
      label,
      async (event) => {
        if (this.busy) return;
        this.busy = true;
        const button = event.currentTarget;
        button.disabled = true;
        try {
          const choice = await this.ctx.confirmChange({
            title: label,
            target: '机构完整备份',
            fields: [['操作', label]],
            confirmLabel: label,
            allowComment: true,
          });
          if (!choice) return;
          const values = typeof payload === 'function' ? payload() : payload;
          await request(path, { ...values, comment: choice.comment });
          this.ctx.toast(
            path === '/points'
              ? '已提交加密快照'
              : path === '/retry'
                ? '已安排重试'
                : path.endsWith('/fetch')
                  ? '已从异地重新取回并核验'
                  : path.endsWith('/verify')
                    ? '已在隔离目录恢复并核对业务版本'
                    : '已接入副本位置',
          );
          await this.refresh();
        } catch (error) {
          this.ctx.toast(error.message);
        } finally {
          this.busy = false;
          button.disabled = false;
        }
      },
      primary ? 'primary' : 'secondary',
    );
  }
  draw(data) {
    const action = this.action(
      '立即创建快照',
      '/points',
      () => ({ requestId: crypto.randomUUID() }),
      true,
    );
    const points = data.points;
    const onFirst = this.cursors.length === 1;
    const latest = points.find((p) => p.state === 'ready');
    const linked = data.locations.filter((t) => t.state === 'linked');
    const good =
      latest?.copies.filter(
        (c) => c.state === 'verified' && linked.some((l) => l.id === c.provider),
      ).length || 0;
    const metric = (label, value) =>
      node('div', 'backup-metric', [node('small', '', label), node('strong', '', value)]);
    const toolbar = node('header', 'fx-toolbar', [
      node('h2', 'access-settings-heading', [this.ctx.ui.icon('shield', 20), '加密快照与异地备份']),
      node('div', 'backup-controls', [
        btn(this.ctx, '备份设置', () => settings(this, data, locationStates)),
        btn(this.ctx, '导入备份', () => importDialog(this, data.policy)),
        action,
      ]),
    ]);
    const meters = node('div', 'backup-metrics', [
      metric('最近可用时间点', stamp(latest?.captured)),
      metric('下次自动备份 · 北京时间', stamp(data.nextAutomatic)),
      metric(
        '最近快照的异地校验',
        linked.length ? good + ' / ' + linked.length + ' 个位置' : '尚未接入位置',
      ),
    ]);
    const table = node('table', 'fx-table');
    table.append(
      node(
        'thead',
        '',
        node(
          'tr',
          '',
          ['创建时间', '来源', '业务版本', '本机状态', '快照大小', '异地副本', '操作'].map((t) =>
            node('th', '', t),
          ),
        ),
      ),
    );
    const rows = node('tbody');
    for (const p of points) {
      const copy = p.copies.map(
        (c) =>
          (data.locations.find((t) => t.id === c.provider)?.label || c.provider) +
          ' · ' +
          (c.error || states[c.state]),
      );
      const values = [
        stamp(p.captured || p.created),
        {
          automatic: '每日一次',
          manual: '管理员创建',
          import: '文件导入',
          protection: '恢复前保护点',
          upgrade: '更新前保护点',
        }[p.kind] || '管理员创建',
        p.revision === null ? '—' : 'v' + p.revision,
        p.error || states[p.state],
        p.bytes ? (p.bytes / 1048576).toFixed(2) + ' MiB' +
          (p.sourceBytes > p.bytes ? ' · 节省 ' + Math.round(100*(1-p.bytes/p.sourceBytes)) + '%' : '') : '—',
        copy.join('；') || '等待异地位置',
      ];
      const trial = node('td', '');
      if (p.state === 'ready') {
        if (p.checked) trial.append(node('small', '', '最近核验 ' + stamp(p.checked)));
        const task = (fn) => async () => {
          try {
            await fn(this, p.id);
          } catch (error) {
            this.ctx.toast(error.message);
          }
        };
        trial.append(
          node('div', 'backup-controls', [
            btn(this.ctx, '恢复', task(managePoint)),
            btn(this.ctx, '导出', task(exportPoint)),
            this.action('核验', '/points/' + p.id + '/verify', {}),
          ]),
        );
      } else {
        const replica = p.copies.find(
          (c) => c.state === 'verified' && linked.some((location) => location.id === c.provider),
        );
        if (replica)
          trial.append(
            this.action('从异地取回', '/points/' + p.id + '/fetch', { provider: replica.provider }),
          );
        else trial.textContent = '—';
      }
      rows.append(node('tr', '', [...values.map((text) => node('td', '', text)), trial]));
    }
    table.append(rows);
    const list = node('div', 'backup-history', [
      node('h3', '', '机构恢复点'),
      points.length
        ? node('div', 'fx-table-wrap', table)
        : node('p', 'fx-muted', '首次完整快照准备中。'),
    ]);
    const nav = node('div', 'backup-controls backup-navigation');
    if (!onFirst)
      nav.append(
        btn(this.ctx, '上一页', async () => {
          this.cursors.pop();
          await this.refresh();
        }),
      );
    if (data.nextCursor)
      nav.append(
        btn(this.ctx, '更早的时间点', async () => {
          this.cursors.push(data.nextCursor);
          await this.refresh();
        }),
      );
    this.replaceChildren(toolbar, ...(onFirst ? [meters] : []), list, nav);
    if (data.configError) this.append(node('p', 'fx-attention', data.configError));
    if (points.some((p) => p.state === 'failed' || p.copies.some((c) => c.state === 'failed')))
      this.append(this.action('重试失败的备份', '/retry', {}));
  }
}
if (!customElements.get('backup-panel')) customElements.define('backup-panel', BackupPanel);
export function backupPanel(ctx) {
  const panel = document.createElement('backup-panel');
  panel.ctx = ctx;
  return panel;
}
