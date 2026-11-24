import { btn, facts, node, section } from './shared.js';

const endpoint = '/api/updates';

async function request(path = '', body) {
  const response = await fetch(endpoint + path, body === undefined ? {} : {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '机构更新服务暂时不可用');
  return result;
}

function timestamp(value) {
  return value ? new Date(value * 1000).toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai', hour12: false,
  }) : '—';
}

class PlatformUpdates extends HTMLElement {
  connectedCallback() {
    this.refresh();
    this.timer = setInterval(() => {
      if (this.pending && !this.busy) this.refresh();
    }, 4000);
  }

  disconnectedCallback() {
    clearInterval(this.timer);
  }

  async refresh(path, body) {
    if (this.busy) return;
    this.busy = true;
    const error = this.querySelector('[role=alert]');
    if (error) error.textContent = '';
    for (const control of this.querySelectorAll('button')) control.disabled = true;
    try {
      this.view = await request(path, body);
      this.pending = Boolean(this.view.pendingVersion);
      this.draw();
    } catch (failure) {
      if (this.view) this.draw(this.pending ? '正在等待机构服务恢复连接。' : failure.message);
      else this.replaceChildren(node('p', 'form-error', '暂时无法读取机构更新设置。'));
    } finally {
      this.busy = false;
    }
  }

  draw(message = '') {
    const view = this.view;
    const settings = node('form', 'fx-profile');
    const automatic = node('input');
    automatic.type = 'checkbox';
    automatic.checked = view.settings.automatic;
    const canEnable = view.managed && view.configured;
    automatic.disabled = !(canEnable || view.settings.automatic);
    const hour = node('select');
    for (let n = 0; n < 24; n++) hour.add(new Option(String(n).padStart(2, '0') + ':00', String(n)));
    hour.value = view.settings.hour;
    hour.disabled = !automatic.checked || !canEnable;
    const save = node('button', 'btn btn-primary', '保存更新设置');
    save.type = 'submit';
    save.disabled = !canEnable;
    automatic.addEventListener('change', () => {
      hour.disabled = !automatic.checked || !canEnable;
      save.disabled = automatic.checked && !canEnable;
    });
    settings.append(
      node('label', 'access-check', [automatic, '每天自动检查、下载并安装新版本']),
      node('label', 'field', [node('span', '', '每日更新时间（北京时间）'), hour]),
      node('div', 'dialog-actions', save),
    );
    settings.addEventListener('submit', event => {
      event.preventDefault();
      this.refresh('/settings', { automatic: automatic.checked, hour: Number(hour.value) });
    });
    const controls = [];
    if (view.configured && !view.pendingVersion) {
      controls.push(btn(this.ctx, '检查更新', () => this.refresh('/check', {})));
      if (view.available && view.available.version !== view.stagedVersion) {
        controls.push(btn(this.ctx, '下载并校验', () =>
          this.refresh('/download', { version: view.available.version }), 'primary'));
      } else if (view.stagedVersion && view.managed && view.available?.version === view.stagedVersion) {
        controls.push(btn(this.ctx, '备份并安装', () => this.confirm(view.stagedVersion), 'primary'));
      }
    }
    const alert = node('p', 'form-error', message);
    alert.setAttribute('role', 'alert');
    const result = view.outcome;
    this.replaceChildren(
      section('机构服务版本', node('div', 'fx-profile', [
        facts([
          ['当前版本', view.installedVersion],
          ['更新来源', view.configured ? '已配置签名更新源' : '等待部署配置发布地址和公钥'],
          ['安装方式', view.managed ? '受托管启动器管理' : '需由托管启动器安装'],
          ['可用新版', view.available?.version || '—'],
          ['已下载', view.stagedVersion || '—'],
        ]),
        view.available?.notes ? node('p', 'fx-muted', view.available.notes) : null,
        node('div', 'dialog-actions', controls),
        view.pendingVersion ? node('p', '', '正在准备安装 ' + view.pendingVersion + '，服务会短时重启。') : null,
        alert,
      ])),
      section('自动更新', settings),
      result ? section('最近更新结果', facts([
        ['处理时间', timestamp(result.at)],
        ['更新状态', result.message],
        ['更新前完整快照', result.snapshotId || '—'],
      ])) : null,
      node('p', 'fx-muted', '更新成功后刷新工作台即可使用新版。桌面客户端的原生外壳使用各平台的发行安装包。'),
    );
  }

  confirm(version) {
    this.ctx.dialog({
      title: '确认升级到 ' + version,
      description: '服务会短时离线。系统会先加密备份并核验全部机构资料，再启动新版。',
      fields: [],
      submitLabel: '备份并安装',
      onSubmit: async () => {
        await request('/install', { version });
        this.pending = true;
        await this.refresh();
        return true;
      },
    });
  }
}

customElements.define('platform-updates', PlatformUpdates);

export function platformUpdates(ctx) {
  const panel = new PlatformUpdates();
  panel.ctx = ctx;
  return panel;
}
