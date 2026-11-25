import { badge, btn, facts, link, node, table } from './shared.js';
import { request, settings, importDialog, exportPoint, managePoint, maintenanceHeader, maintenanceLog, maintenanceViews } from './backup-exchange.js';

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

const origins = {automatic:'自动备份', manual:'手动创建', import:'文件导入', protection:'恢复前保护点', upgrade:'更新前保护点'};
const volume = value => value == null ? '—' : (value/1048576).toFixed(2) + ' MiB';
let pendingPoint = null;
export function openBackupPoint(ctx, id) {
  if (!/^ak-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{32}$/.test(id)) return;
  const current = document.querySelector('backup-panel');
  if (current?.isConnected) managePoint(current, id).catch((error) => ctx.toast(error.message));
  else pendingPoint = { id, actor: ctx.state.user.id };
}

class BackupPanel extends HTMLElement {
  connectedCallback() {
    this.className = 'recovery-page';
    this.preferences = this.ctx.workspaceState || {};
    this.view = this.preferences.backupSection || 'points';
    this.cursors ||= [0];
    if (!this.firstChild) this.append(node('p','fx-muted','正在读取备份设置…'));
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
    if (this.loading) { this.refreshAgain = true; return; }
    this.loading = true;
    try {
      const cursor = this.cursors[this.cursors.length - 1];
      const data = await request(cursor ? '?before=' + cursor : '');
      if (cursor !== this.cursors[this.cursors.length - 1]) return;
      if (!this.isConnected) return;
      const signature = JSON.stringify(data);
      if (this.rendered !== signature) {
        this.data = data;
        this.draw(data);
        this.rendered = signature;
      }
    } catch (error) {
      if (this.isConnected) {
        this.replaceChildren(node('p','form-error',error.message),btn(this.ctx,'重试读取备份',()=>this.refresh()));
        this.rendered = null;
      }
    } finally {
      this.loading = false;
      if (this.refreshAgain && this.isConnected) {
        this.refreshAgain = false;
        this.refresh();
      }
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
          if (button.closest('.recovery-detail')) button.closest('dialog')?.close();
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
  pointActions(data, point) {
    const open = fn => async () => {
      try { await fn(this,point.id); } catch (error) { this.ctx.toast(error.message); }
    };
    if (point.state === 'ready') return [
      btn(this.ctx,'恢复',open(managePoint),'primary'),
      btn(this.ctx,'导出',open(exportPoint)),
      this.action('核验','/points/'+point.id+'/verify',{}),
    ];
    return point.copies.filter(c=>c.state==='verified' &&
      data.locations.some(l=>l.id===c.provider && l.state==='linked')).map(c=>{
        const label=data.locations.find(l=>l.id===c.provider).label;
        return this.action('从'+label+'取回','/points/'+point.id+'/fetch',{provider:c.provider});
      });
  }

  inspect(data, point) {
    const controls = this.pointActions(data,point);
    this.ctx.detail('恢复点详情', node('div','recovery-detail',[
      facts([['创建时间',stamp(point.created)],['快照来源',origins[point.kind] || point.kind],
        ['恢复点编号',point.id],['业务修订',point.revision==null?'待生成':'v'+point.revision],
        ['本机状态',states[point.state] || point.state],['采集完成',stamp(point.captured)],
        ['最近核验',stamp(point.checked)],['快照文件',volume(point.bytes)],['压缩前',volume(point.sourceBytes)],
        ...(point.sourceBytes>0?[['压缩节省',Math.round((1-point.bytes/point.sourceBytes)*100)+'%']]:[]),
        ...(point.error?[['异常说明',point.error]]:[])]),
      table(this.ctx,{title:'此恢复点的异地副本', rows:point.copies,
        cols:[{label:'配送位置',view:c=>data.locations.find(l=>l.id===c.provider)?.label || c.provider},
          {label:'状态',view:c=>badge(this.ctx,states[c.state] || c.state)},
          {label:'最近校验',view:c=>stamp(c.verified)},{label:'异常说明',view:c=>c.error || '—'}],
        empty:'此恢复点尚无异地副本记录'}),
      controls.length ? node('div','dialog-actions',controls) : null,
    ]));
  }

  draw(data) {
    const ctx = this.ctx;
    const linked = data.locations.filter(t=>t.state==='linked').length;
    const recent = data.points.find(p=>p.state==='ready');
    if (this.cursors.length === 1) this.latest = recent?.captured;
    const header = maintenanceHeader(ctx,'机构备份策略',[
      ['自动周期','每 '+data.intervalHours+' 小时'], ['下次自动备份',stamp(data.nextAutomatic)],
      ['最近可用恢复点',stamp(this.latest)],['已连接异地位置',linked+' 个'],
      ['本机保留',data.policy.retentionDays ? data.policy.retentionDays+' 天' : '长期保留'],
      ['单次导入上限',data.policy.uploadLimitMiB+' MiB'],
    ],[btn(ctx,'备份设置',()=>settings(this,data,locationStates)),
       btn(ctx,'导入备份',()=>importDialog(this,data.policy)),
       this.action('立即创建快照','/points',()=>({requestId:crypto.randomUUID()}),true)]);
    const views = maintenanceViews(ctx, [['points','恢复点台账'],['locations','异地配送'],['logs','操作记录']],
      this.view, key=>{this.view=this.preferences.backupSection=key;this.draw(this.data);});
    let content;
    if (this.view==='logs') {
      content = this.querySelector('.recovery-log') || maintenanceLog(ctx,'backup');
    } else if (this.view==='locations') {
      content = table(ctx,{title:'异地配送位置',rows:data.locations,
        filter:{label:'授权状态',value:r=>locationStates[r.state]},
        search:{placeholder:'搜索配送位置',value:r=>r.label},
        action:btn(ctx,'管理配送设置',()=>settings(this,data,locationStates)),
        cols:[{label:'位置',view:r=>r.label},{label:'服务状态',view:r=>badge(ctx,locationStates[r.state])},
          {label:'服务端授权',view:r=>r.available?'已配置':'待授权'},
          {label:'详情',view:r=>link(ctx,'查看位置',()=>ctx.detail('异地配送位置',facts([
            ['服务商',r.label],['授权状态',locationStates[r.state]],
            ['可连接',r.available?'已在机构服务器配置':'尚未提供有效配置'],
          ])))}]});
    } else {
      const controls = node('div','fx-actions');
      if (this.cursors.length>1) controls.append(btn(ctx,'较新的 50 个恢复点',()=>{
        this.cursors.pop();this.refresh();
      }));
      if (data.nextCursor) controls.append(btn(ctx,'更早的 50 个恢复点',()=>{
        if (this.cursors.at(-1)!==data.nextCursor) this.cursors.push(data.nextCursor);
        this.refresh();
      }));
      if (data.points.some(p=>p.state==='failed'||p.copies.some(c=>c.state==='failed')))
        controls.append(this.action('重试失败的备份','/retry',{}));
      content = table(ctx,{
        title:'机构恢复点', rows:data.points,action:controls,
        search:{placeholder:'搜索本批编号、日期、来源或修订',value:p=>[p.id,stamp(p.created),origins[p.kind], 'v'+p.revision].join(' ')},
        filter:{label:'本机状态',value:p=>states[p.state] || p.state},
        cols:[{label:'创建时间（北京）',view:p=>stamp(p.created)},
          {label:'来源',view:p=>origins[p.kind] || p.kind},
          {label:'业务修订',view:p=>p.revision==null?'—':'v'+p.revision},
          {label:'本机状态',view:p=>badge(ctx,states[p.state] || p.state,p.state==='ready'?'green':p.error?'red':'amber')},
          {label:'快照大小',view:p=>volume(p.bytes)},
          {label:'已校验异地副本',view:p=>p.copies.filter(c=>c.state==='verified').length+' 个'},
          {label:'操作',view:p=>link(ctx,'查看恢复点',()=>this.inspect(data,p))}],
        empty:'当前批次没有恢复点。',
      });
    }
    this.replaceChildren(header,views,content);
    if (data.configError) this.append(node('p','fx-attention',data.configError));
  }
}
if (!customElements.get('backup-panel')) customElements.define('backup-panel', BackupPanel);
export function backupPanel(ctx) {
  const panel = document.createElement('backup-panel');
  panel.ctx = ctx;
  return panel;
}
