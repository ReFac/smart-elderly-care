import { badge, btn, facts, link, node, table } from './shared.js';
import { maintenanceHeader, maintenanceLog, maintenanceViews } from './backup-exchange.js';
import { openBackupPoint } from './backups.js';

async function request(path = '', body) {
  const response = await fetch('/api/updates' + path, body === undefined ? { cache:'no-store' } : {
    method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(result.error || '机构更新服务暂时不可用');
    error.status = response.status;
    throw error;
  }
  return result;
}

const clock = new Intl.DateTimeFormat('zh-CN', {
  timeZone:'Asia/Shanghai', dateStyle:'medium', timeStyle:'medium', hourCycle:'h23',
});
const timestamp = value => value ? clock.format(value * 1000) : '—';
const scheduled = hour => String(hour).padStart(2,'0') + ':00';

class PlatformUpdates extends HTMLElement {
  connectedCallback() {
    this.className = 'recovery-page';
    this.preferences = this.ctx.workspaceState || {};
    this.section = this.preferences.updateSection || 'releases';
    if (!this.firstChild) this.append(node('p','fx-muted','正在读取平台版本与更新设置…'));
    this.refresh();
    this.timer = setInterval(() => {
      if (!document.hidden && this.view?.pendingVersion && !this.busy) this.refresh();
    },4000);
  }

  disconnectedCallback() { clearInterval(this.timer); }

  async refresh(path, body) {
    if (this.busy) return;
    this.busy = true;
    try {
      for (const button of this.querySelectorAll('.recovery-banner button,.recovery-views button')) button.disabled=true;
      const view = await request(path,body);
      if (!this.isConnected) return;
      this.view = view;
      this.draw();
    } catch (error) {
      if (!this.isConnected) return;
      if (this.view && ![401,403].includes(error.status)) {
        this.draw(this.view.pendingVersion ? '服务正在重新连接，请稍候。' : error.message);
      } else {
        this.view = null;
        const message = node('p','form-error',error.message);
        message.setAttribute('role','alert');
        this.replaceChildren(message,btn(this.ctx,'重新读取',()=>this.refresh()));
      }
    } finally { this.busy = false; }
  }

  editSettings() {
    const { configured,managed,settings } = this.view;
    const canEnable = configured && managed;
    const automatic = node('input'); automatic.type='checkbox'; automatic.checked=settings.automatic;
    automatic.disabled = !canEnable && !settings.automatic;
    const hour = node('select','fx-input');
    for (let n=0;n<24;n++) hour.add(new Option(scheduled(n),String(n)));
    hour.value=String(settings.hour);
    const save = node('button','btn btn-primary','保存更新设置'); save.type='submit';
    const adjust = () => {
      hour.disabled=!canEnable || !automatic.checked;
      save.disabled=(!canEnable && automatic.checked) ||
        (settings.automatic===automatic.checked && settings.hour===Number(hour.value));
    };
    automatic.onchange=hour.onchange=adjust;
    adjust();
    const form=node('form','recovery-setting-form',[
      node('label','access-check',[automatic,'每天自动检查、下载并安装新版本']),
      node('label','field',[node('span','','计划时间（北京时间）'),hour]),
      !canEnable ? node('p','fx-muted','启用自动安装需要先配置签名更新源，并通过托管启动器运行。') : null,
      node('div','dialog-actions',save),
    ]);
    const dialog = this.ctx.detail('自动更新设置',form);
    form.onsubmit = async event => {
      event.preventDefault();
      if (save.disabled) return;
      const fields={automatic:automatic.checked,hour:Number(hour.value)};
      const choice = await this.ctx.confirmChange({
        title:'保存自动更新设置',target:'机构服务',
        fields:[['自动更新',fields.automatic?'已启用':'已关闭'],
          ['计划时间（北京）',fields.automatic?scheduled(fields.hour):'—']],
        confirmLabel:'保存设置',
      });
      if (!choice || !dialog.open) return;
      save.disabled=true;
      try {
        const view=await request('/settings',fields);
        dialog.close();
        if (this.isConnected) {this.view=view;this.draw();this.ctx.toast('更新设置已保存');}
      } catch (error) {this.ctx.toast(error.message);adjust();}
    };
  }

  inspect(row) {
    const body=node('div','recovery-detail',[facts([
      ['版本',row.version || '—'],['状态',row.status],['记录时间（北京）',timestamp(row.at)],
      ['说明',row.message],['更新包大小',row.size==null?'—':(row.size/1048576).toFixed(2)+' MiB'],
      ['更新前快照',row.snapshotId || '—'],
    ])]);
    const dialog=this.ctx.detail('版本处理详情',body);
    if (row.snapshotId) body.append(btn(this.ctx,'查看更新前快照',()=>{
      dialog.close();
      this.ctx.go('settings','backups',()=>openBackupPoint(this.ctx,row.snapshotId));
    }));
  }

  draw(message = '') {
    const ctx=this.ctx,view=this.view;
    const controls=[btn(ctx,'自动更新设置',()=>this.editSettings())];
    if (view.configured && !view.pendingVersion) {
      controls.push(btn(ctx,'检查更新',()=>this.refresh('/check',{})));
      if (view.available && view.available.version!==view.stagedVersion)
        controls.push(btn(ctx,'下载并校验',()=>this.refresh('/download',{version:view.available.version}),'primary'));
      if (view.managed && view.stagedVersion && view.stagedVersion===view.available?.version)
        controls.push(btn(ctx,'备份并安装',()=>this.confirm(view.stagedVersion),'primary'));
    }
    const header=maintenanceHeader(ctx,'版本与更新策略',[
      ['机构服务版本',view.installedVersion],['签名更新源',view.configured?'已配置':'等待发布地址和公钥'],
      ['安装方式',view.managed?'托管启动器':'独立运行'],
      ['自动安装',view.settings.automatic?'已启用':'已关闭'],
      ['计划时间（北京）',view.settings.automatic?scheduled(view.settings.hour):'—'],
      ['安装前保护','创建并核验完整加密快照'],
    ],controls);
    const switcher=maintenanceViews(ctx,[['releases','版本工作记录'],['logs','设置操作记录']],
      this.section,key=>{this.section=this.preferences.updateSection=key;this.draw();});
    let ledger;
    if (this.section==='logs') ledger=this.querySelector('.recovery-log') || maintenanceLog(ctx,'update');
    else {
      const rows=[];
      const release=view.available;
      if (view.pendingVersion) rows.push({version:view.pendingVersion,status:'等待完成安装',
        message:'正在准备安装，请等待服务重新连接。'});
      if (view.stagedVersion && view.stagedVersion!==view.pendingVersion) rows.push({version:view.stagedVersion,
        status:'已下载并校验',size:release?.version===view.stagedVersion?release.size:null,
        message:release?.version===view.stagedVersion?release.notes:'更新包已暂存'});
      if (release && ![view.stagedVersion,view.pendingVersion].includes(release.version))
        rows.push({version:release.version,status:'可用新版',message:release.notes,size:release.size});
      if (view.outcome) {
        const names={'backing-up':'正在创建保护点',starting:'正在启动新版',installed:'安装完成',failed:'更新失败'};
        rows.push({...view.outcome,status:names[view.outcome.state] || '上次处理结果'});
      }
      rows.push({version:view.installedVersion,status:'当前运行',message:'当前机构服务使用此版本'});
      ledger=table(ctx,{
        title:'版本工作记录',rows,search:{placeholder:'搜索版本、状态或发布说明',value:r=>[r.version,r.status,r.message].join(' ')},
        filter:{label:'处理状态',value:r=>r.status},
        cols:[{label:'版本',view:r=>r.version || '—'}, {label:'处理状态',view:r=>badge(ctx,r.status)},
          {label:'记录时间（北京）',view:r=>timestamp(r.at)}, {label:'说明',view:r=>r.message || '未提供发布说明'},
          {label:'详情',view:r=>link(ctx,'查看详情',()=>this.inspect(r))}],
      });
    }
    this.replaceChildren(header,switcher,ledger);
    if (message) { const alert=node('p','form-error',message);alert.setAttribute('role','alert');this.append(alert); }
  }

  confirm(version) {
    this.ctx.dialog({
      title:'确认升级到 '+version,
      description:'服务会短时离线。系统先加密备份并核验全部机构资料，再启动新版。',
      fields:[], submitLabel:'备份并安装',
      onSubmit:async()=>{await request('/install',{version});await this.refresh();return true;},
    });
  }
}

if (!customElements.get('platform-updates')) customElements.define('platform-updates',PlatformUpdates);
export function platformUpdates(ctx) {
  const panel=document.createElement('platform-updates');panel.ctx=ctx;return panel;
}
