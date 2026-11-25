import { node, table, kpis, choose, btn, named, badge } from './shared.js';

export const monitors = [
  ['onlineUsers','在线用户'], ['timers','定时任务'], ['dataMonitor','数据监控'],
  ['serviceMonitor','服务监控'], ['cacheMonitor','缓存监控'], ['cacheList','缓存列表'],
];

const localTime = value => new Intl.DateTimeFormat('zh-CN',{
  dateStyle:'short',timeStyle:'medium',timeZone:'Asia/Shanghai',hour12:false,
}).format(new Date(value));

function content(ctx,view,data) {
  const rows = data.rows;
  if (view === 'onlineUsers') return table(ctx,{
    title:'最近 5 分钟活跃的登录账号',rows,empty:'采样期间没有活跃的登录账号',
    search:{placeholder:'搜索账号、姓名或岗位',value:r=>[r.login,r.name,r.role].join(' ')},
    cols:[{label:'登录账号',view:r=>r.login},{label:'姓名',view:r=>r.name},{label:'岗位',view:r=>r.role},
      {label:'有效活跃会话',view:r=>r.sessions},{label:'最后活动',view:r=>localTime(r.lastSeen)}],
  });
  if (view === 'timers') return node('div','fx-profile',[
    table(ctx,{ title:'后台定时服务',rows, cols:[
      {label:'服务',view:r=>r.name},{label:'任务标识',view:r=>r.worker},
      {label:'运行状态',view:r=>badge(ctx,r.active?'运行中':'未运行',r.active?'green':'amber')},
    ]}),
    table(ctx,{title:'最近派发批次',rows:data.runs,action:ctx.available('care') ?
      btn(ctx,'管理定时工单',()=>ctx.go('care','scheduledWork'),'primary') : null,
      empty:'还没有派发批次',cols:[{label:'派发日期',view:r=>r.day},{label:'计划时间',view:r=>r.time},
        {label:'工单',view:r=>r.title},{label:'派发量',view:r=>r.count},{label:'状态',view:r=>badge(ctx,r.status)}]}),
  ]);
  if (view === 'cacheMonitor' || view === 'cacheList') {
    const total = name => rows.reduce((sum,row)=>sum + row[name],0);
    const rate = row => row.hits+row.misses ? (100*row.hits/(row.hits+row.misses)).toFixed(1)+'%' : '—';
    const detail = row => ctx.detail(row.label,node('dl','fx-facts',[
      ['命名空间',row.name],['缓存条目',row.entries],['命中次数',row.hits],['未命中次数',row.misses],
      ['容量上限',row.limit ?? '未设固定上限'],
    ].map(([label,value])=>node('div','',[node('dt','',label),node('dd','',String(value))]))));
    return node('div','fx-profile',[
      view==='cacheMonitor' ? kpis([['缓存条目',total('entries')],['命中次数',total('hits')],
        ['未命中次数',total('misses')],['命中率',rate({hits:total('hits'),misses:total('misses')})]]) : null,
      table(ctx,{title:view==='cacheMonitor'?'缓存使用情况':'缓存命名空间',rows,
        search:{placeholder:'搜索缓存名称或命名空间',value:r=>r.label+' '+r.name},cols:[
          {label:'名称',view:r=>named(r.label,r.name)},{label:'条目',view:r=>r.entries},
          {label:'容量上限',view:r=>r.limit ?? '按需缓存'},{label:'命中率',view:rate},
          {label:'操作',align:'end',view:r=>btn(ctx,'查看',()=>detail(r),'ghost')},
        ]}),
    ]);
  }
  return table(ctx,{title:view==='dataMonitor'?'业务数据与存储':'当前服务运行情况',rows,
    cols:[{label:'监测项',view:r=>r[0]},{label:'当前值',view:r=>r[1]},{label:'统计口径',view:r=>r[2]}]});
}

export function monitorPage(ctx,view) {
  const title = monitors.find(([key])=>key === view)[1];
  const panel = node('section','fx-page');
  const stamp = node('small','fx-muted');
  const body = node('div','fx-profile');
  const refresh = btn(ctx,'刷新',load,'secondary');
  panel.append(node('header','fx-module-head',[node('h1','',title),choose(stamp,refresh)]),body);
  async function load() {
    refresh.disabled=true;
    try {
      const data = await ctx.get('/api/system/monitor?' + new URLSearchParams({view}));
      stamp.textContent = '采样时间 ' + localTime(data.sampledAt);
      body.replaceChildren(content(ctx,view,data));
    } catch (err) { body.replaceChildren(ctx.ui.empty(err.message)); }
    finally { refresh.disabled=false; }
  }
  load();
  return panel;
}
