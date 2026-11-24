import { node, btn } from './shared.js';

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

async function request(path, payload) {
  const response = await fetch(
    '/api/backups' + path,
    payload
      ? {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }
      : { cache: 'no-store' },
  );
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '无法读取备份状态');
  return data;
}

class BackupPanel extends HTMLElement {
  connectedCallback() {
    this.className = 'backup-panel fx-panel';
    this.refresh();
    this.timer = setInterval(() => {
      if (!document.hidden && !this.busy) this.refresh();
    }, 5000);
  }
  disconnectedCallback() {
    clearInterval(this.timer);
  }
  async refresh() {
    if (this.loading) return;
    this.loading = true;
    try {
      const data = await request('');
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
          await request(path, typeof payload === 'function' ? payload() : payload);
          this.ctx.toast(
            path === '/points'
              ? '已提交加密快照'
              : path === '/retry'
                ? '已安排重试'
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
      action,
    ]);
    const meters = node('div', 'backup-metrics', [
      metric('最近可用时间点', stamp(latest?.captured)),
      metric('下次自动备份 · 北京时间', stamp(data.nextAutomatic)),
      metric(
        '最近快照的异地校验',
        linked.length ? good + ' / ' + linked.length + ' 个位置' : '尚未接入位置',
      ),
    ]);
    const targets = node('div', 'backup-targets');
    for (const target of data.locations) {
      const body = node('div', '', [
        node('strong', '', target.label),
        node('small', '', locationStates[target.state]),
      ]);
      const parts = [body];
      if (target.available && target.state !== 'linked')
        parts.push(this.action('连接', '/locations', { provider: target.id }));
      targets.append(node('div', 'backup-target', parts));
    }
    const table = node('table', 'fx-table');
    table.append(
      node(
        'thead',
        '',
        node(
          'tr',
          '',
          ['创建时间', '触发方式', '本机状态', '快照大小', '异地副本', '恢复核验'].map((t) =>
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
        p.kind === 'automatic' ? '每 12 小时' : '管理员创建',
        p.error || states[p.state],
        p.bytes ? (p.bytes / 1048576).toFixed(2) + ' MiB' : '—',
        copy.join('；') || '等待异地位置',
      ];
      const trial = node('td', '');
      if (p.state === 'ready') {
        if (p.checked) trial.append(node('small', '', '最近核验 ' + stamp(p.checked)));
        trial.append(this.action('验证恢复', '/points/' + p.id + '/verify', {}));
      } else trial.textContent = '—';
      rows.append(node('tr', '', [...values.map((text) => node('td', '', text)), trial]));
    }
    table.append(rows);
    const list = node('div', 'backup-history', [
      node('h3', '', '最近 50 个时间点'),
      points.length
        ? node('div', 'fx-table-wrap', table)
        : node('p', 'fx-muted', '首次完整快照准备中。'),
    ]);
    this.replaceChildren(toolbar, meters, targets, list);
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
