// Sidebar entries target the same permission-checked routes as search and the assistant.
export const deskMenu = [
  { label: 'AI', icon: 'spark', route: 'assistants' },
  { label: '首页', icon: 'home', route: 'overview' },
  { label: '入住管理', icon: 'intake', route: 'residents' },
  { label: '床位管理', icon: 'bed', route: 'beds' },
  { label: '照护工单', icon: 'list', route: 'care', tab: 'tasks', grant: '@care.completeTask' },
  { label: '接待入住', icon: 'people', children: [
    ['leads', '接待管理'], ['residents', '退住记录', 'discharged'],
    ['medications','药品接收登记','receiving','clinical'], ['residents', '请假管理', 'leaves'],
  ] },
  { label: '长辈档案', icon: 'person', route: 'dossier' },
  { label: '照护服务', icon: 'care', children: [
    ['assessments', '能力评估'], ['assessments','安全风险评估','risk','clinical'], ['assessments', '照护计划', 'plans'], ['assessments', '复评安排', 'review'],
    ['care', '照护工作台'],
    ['care', '定时工单与批量派发', 'scheduledWork', 'care|clinical|care.schedule'],
    ['care','健康体征','vitals','@care.vital'], ['care','班次交接','handover','@care.handover'],
    ['medications', '用药管理'], ['inbox', '预警与确认'],
  ] },
  { label: '仓库管理', icon: 'box', children: [
    ['inventory', '库存台账'], ['inventory', '出入库流水', 'moves'], ['inventory','护理用具工单','orders'],
  ] },
  { label: '费用管理', icon: 'wallet', children: [
    ['billing','财务总览','summary'], ['billing','待收费','unpaid'], ['billing','月度账单确认','due'],
    ['billing','医疗费用','medicalFees'], ['billing','退住结算','discharge'], ['billing','收费记录','receipts'],
    ['billing','民政补贴申报材料','subsidies','finance'], ['billing','日结报表','daily'],
  ] },
  { label: '运营看板', icon: 'chart', route: 'overview', view: 'cockpit' },
  { label: '部署控制台', icon: 'monitor', route: 'deployment' },
  { label: '系统管理', icon: 'settings', children: [
    ['access','账号与权限'], ['access','岗位权限模板','templates'], ['shifts','人员排班'], ['settings','机构设置'],
    ['integrations','设备与接口'], ['activity','操作日志'], ['history','最近改动'],
    ['reports','统计报送'], ['longCare','长期护理保险'], ['account','个人中心'],
    ['family','家属服务'], ['tour','环境导览'], ['faq','常见问题'],
  ] },
  { label: '系统监控', icon: 'monitor', children: [
    ['settings','在线用户','onlineUsers'], ['settings','定时任务','timers'], ['settings','数据监控','dataMonitor'],
    ['settings','服务监控','serviceMonitor'], ['settings','缓存监控','cacheMonitor'], ['settings','缓存列表','cacheList'],
  ] },
];

export function menuFor(ctx) {
  if (ctx.state.user.kind === 'family') {
    const children = [['family',ctx.state.user.portalSelf?'长辈服务':'家属服务'],['tour','环境导览'],['faq','常见问题'],['account','个人中心']]
      .filter(([id])=>ctx.available(id));
    return children.map(([route,label])=>({route,label,icon:route==='account'?'person':route==='faq'?'info':'building'}));
  }
  function visible(route, grant) {
    return ctx.available(route) && (!grant || (grant.startsWith('@') ?
      ctx.state.allowedActions.includes(grant.slice(1)) : grant.split('|').some(ctx.permitted)));
  }
  return deskMenu.flatMap(group => {
    if (group.route) return visible(group.route, group.grant) ? [group] : [];
    const children = group.children.filter(([route,,, grant]) => visible(route, grant));
    return children.length ? [{ ...group, children }] : [];
  });
}

export function deskPath(menu, route, tab, view) {
  let fallback;
  for (const group of menu) {
    if (group.route === route && group.view === view) {
      if (group.tab === tab) return { label: group.label };
      if (!group.tab) fallback = { label: group.label };
    }
    for (const [r, label, key] of group.children || []) {
      if (r !== route) continue;
      if (key === tab) return { group: group.label, label };
      if (!key || (!fallback && group.label === '费用管理' && r === 'billing')) fallback = { group: group.label, label };
    }
  }
  return fallback || {};
}

const viewIcons = {
  discharged:'undo', receiving:'pill', leaves:'calendar', zones:'layers', plan:'grid', plans:'file', risk:'shield',
  review:'clock', tasks:'list', scheduledWork:'clock', moves:'history', bills:'wallet', due:'calendar',
  receipts:'file', expenses:'list', orders:'box', reminders:'bell', billingNotices:'bell',
  deposits:'wallet', subsidies:'folder', payments:'check', backups:'layers', platformUpdates:'refresh',
  onlineUsers:'people', timers:'clock', dataMonitor:'layers', serviceMonitor:'monitor', cacheMonitor:'chart', cacheList:'list',
  medicalFees:'file', discharge:'undo', daily:'reports', unpaid:'wallet', summary:'chart',
  medRounds:'pill', vitals:'pulse', handovers:'shifts', accounts:'people',
};
export const viewIcon = (key,fallback) => viewIcons[key] || fallback;
