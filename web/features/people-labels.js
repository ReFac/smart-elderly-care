function findResident(ctx, ref) {
  return ref && (typeof ref === 'object' ? ref : ctx.state.residents?.find(row => row.id === ref));
}

export function residentLabel(ctx, ref) {
  const row = findResident(ctx, ref);
  if (!row) return '—';
  const room = ctx.state.residentRooms?.[row.id];
  const bed = row.bedId && ctx.state.beds?.find(b => b.id === row.bedId);
  const fallback = bed?.label?.match(/^(.+)-[^-]+$/)?.[1];
  const location = room || fallback || (row.status === '已退住' ? '已退住' :
    row.status === '未入住' || row.status === '试住到期待确认' ? '未分房' :
    row.status === '在住' || row.bedId ? '房号待核实' : '房号未提供');
  return row.name + '（' + location + '）';
}

export function residentHref(ctx, ref) {
  const row = findResident(ctx, ref);
  if (!row || !ctx.available) return '';
  const route = ['residents', 'dossier', 'billing', 'longCare', 'family'].find(key => ctx.available(key));
  return route && ('#' + route + '?resident=' + encodeURIComponent(row.id)) || '';
}

export function residentAnchor(ctx, ref) {
  const href = residentHref(ctx, ref);
  const element = document.createElement(href ? 'a' : 'span');
  element.textContent = residentLabel(ctx, ref);
  if (href) {
    element.href = href;
    element.className = 'resident-profile-link';
  }
  return element;
}

export function staffLabel(ctx, value, id) {
  const row = value && typeof value === 'object' ? value : null;
  const name = row?.displayName || (typeof value === 'string' ? value : '');
  if (!name) return '—';
  const accountId = id || row?.id;
  const account = row?.role ? row : [ctx.state.user, ...(ctx.state.accounts || [])]
    .find(a => a?.id && a.id === accountId);
  if (account?.kind === 'family') return account.portalSelf ? residentLabel(ctx, account.residentId) : name;
  const role = account?.role === '自定义' ? account.staffDuties?.join('、') : account?.role;
  const roles = ctx.state.staffPositions;
  const position = role || roles?.ids?.[accountId] || roles?.names?.[name];
  if (!position && /^(?:—|未登记|待登记|系统|机构系统|宣传页|宣传页访客|DeepSeek|平台运营方|自动巡查|AI 助理定时巡查|健康助理定时巡查|试住到期服务|档案保管服务|历史记录)$/.test(name)) return name;
  return name + '（' + (position || '岗位未登记') + '）';
}

export function auditActorLabel(ctx, row, fallback = '系统') {
  if (!row.actorName) return fallback;
  return staffLabel(ctx, { id: row.actorId, displayName: row.actorName, role: row.actorPosition });
}
