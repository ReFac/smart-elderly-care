import { btn, choose, node, residentField, today } from './shared.js';
import { residentLabel, staffLabel } from './people-labels.js';

function sourceLink(url, label) {
  const link = node('a', 'resident-profile-link medication-source-link', label);
  link.href = url;
  link.target = '_blank';
  link.rel = 'noopener noreferrer'; link.referrerPolicy = 'no-referrer';
  return link;
}

function historyRow(ctx, row) {
  const author = row.bySelf ? '长辈本人' : staffLabel(ctx, { displayName: row.actorName, role: row.actorRole });
  return node('article', 'fx-time-row', [node('time', '', row.day), node('div', 'fx-named', [
    node('strong', '', row.name || row.rawName),
    node('span', '', row.name ? ['本人填报「' + row.rawName + '」 · ', sourceLink(row.url, row.source)] : '药名待核对'),
    row.regimen ? node('p', '', '本人陈述的用法：' + row.regimen) : null,
    node('small', 'fx-muted', author + ' · ' + row.at.slice(0, 16).replace('T', ' ') + ' · 第 ' + row.version + ' 版'),
  ])]);
}

function reportForm(ctx, residentId, endpoint, revision, row, refresh) {
  const me = ctx.state.user.kind === 'family';
  const target = residentLabel(ctx, residentId);
  const form = node('form', 'dialog-form medication-source-scope');
  const raw = node('input');
  raw.name = 'rawName'; raw.required = true; raw.maxLength = 60; raw.autocomplete = 'off';
  raw.value = row?.rawName || '';
  raw.placeholder = '例如：阿莫西林';
  const day = node('input');
  day.type = 'date'; day.required = true; day.max = today(ctx); day.value = row?.day || today(ctx);
  const regimen = node('textarea');
  regimen.rows = 2; regimen.maxLength = 400; regimen.value = row?.regimen || '';
  regimen.placeholder = '可选，按本人描述记录服用时间、频次和剂量';
  const message = node('p', 'fx-muted', '输入两个字即可查询目录，也可以按药盒原文保存待核对。');
  message.setAttribute('role', 'status');
  const catalogChoices = node('div', 'fx-profile');
  const liveChoices = node('div', 'fx-profile');
  const liveMessage = node('p', 'fx-muted');
  liveMessage.setAttribute('role', 'status');
  const liveResults = node('div', 'fx-profile', [liveMessage, liveChoices]);
  liveResults.hidden = true;
  for (const group of [catalogChoices, liveChoices]) group.id = 'drug-options-' + crypto.randomUUID();
  raw.setAttribute('aria-controls', catalogChoices.id + ' ' + liveChoices.id);
  const automatic = node('input');
  automatic.type = 'checkbox'; automatic.name = 'automaticDrugSearch';
  const preference = ctx.state.user.id && 'ankang.drugSearch.' + ctx.state.user.id;
  try { automatic.checked = Boolean(preference && sessionStorage.getItem(preference) === 'on'); } catch { /* Optional browser preference. */ }
  const selected = node('p', 'fx-muted');
  const error = node('p', 'form-error'); error.setAttribute('role', 'alert');
  const save = node('button', 'btn btn-primary', '核对并保存'); save.type = 'submit';
  let candidate = row?.reference ? row : null;
  let catalogTimer, liveTimer, termVersion = 0, liveVersion = 0;
  function invalidate() {
    clearTimeout(catalogTimer); clearTimeout(liveTimer); termVersion++; liveVersion++;
  }
  function selection() {
    selected.replaceChildren(...(candidate ? ['待保存的药名：' + candidate.name + ' · ', sourceLink(candidate.url, '查看名称来源'),
      btn(ctx, '撤回选择', () => { candidate = null; selection(); raw.focus(); })] : []));
  }
  selection();
  const lookup = async (query, current, online = false, request = liveVersion) => {
    const isCurrent = () => current === termVersion && (!online || request === liveVersion) && form.isConnected;
    const choices = online ? liveChoices : catalogChoices;
    const status = online ? liveMessage : message;
    try {
      const result = await ctx.get(endpoint + '/drug-names?q=' + encodeURIComponent(query) + (online ? '&online=1' : ''));
      if (!isCurrent()) return;
      const stale = result.status === 'cached' ? '联网暂不可用，使用上次成功读取的目录。' : '';
      if (online) {
        status.textContent = result.status === 'unavailable' ? '实时检索暂时不可用，可查看药学数据中心或按原文保存。' :
          result.matches.length ? '实时药名 · Wikidata（含 ATC 编码）' : '未查到含 ATC 编码的匹配，可查看药学数据中心或保留原文。';
      } else status.textContent = result.status === 'unavailable' ? '医保目录暂时无法联网。可先按原文保存。' :
        stale + (result.matches.length ? '医保目录 · 请对照药盒选择相符的名称' : '医保目录中未找到相符药名。');
      choices.replaceChildren(...result.matches.map(option => {
        const button = btn(ctx, option.name + ' · ' + option.match, () => {
          invalidate(); candidate = { ...option, source: result.source }; selection();
          catalogChoices.replaceChildren(); liveChoices.replaceChildren(); liveResults.hidden = true; live.disabled = false;
          message.textContent = '已选择核对药名，原文会一同保存。'; save.focus();
        });
        return choose(button, sourceLink(option.url, option.page ? '目录第 ' + option.page + ' 页' : '查看药名词条'));
      }));
      if (online && result.publicUrl) choices.append(sourceLink(result.publicUrl, '到药学数据中心搜索「' + query + '」'));
    } catch (ex) {
      if (isCurrent()) status.textContent = ex.message + '。可先按原文保存待核对。';
    }
  };
  function searchLive() {
    clearTimeout(liveTimer);
    const query = raw.value.trim();
    if (query.length < 2) return;
    const request = ++liveVersion;
    live.disabled = true; liveResults.hidden = false; liveChoices.replaceChildren();
    liveMessage.textContent = '正在实时检索「' + query + '」…';
    lookup(query, termVersion, true, request).finally(() => { if (request === liveVersion) live.disabled = false; });
  }
  const live = btn(ctx, '联网查此药名', searchLive);
  live.disabled = raw.value.trim().length < 2;
  function schedule(allowAutomatic = true) {
    invalidate();
    const current = termVersion;
    catalogChoices.replaceChildren(); liveChoices.replaceChildren(); liveResults.hidden = true;
    candidate = null; selection();
    const query = raw.value.trim();
    live.disabled = query.length < 2;
    if (query.length < 2) { message.textContent = '输入两个字即可查询目录。'; return; }
    message.textContent = '正在查询医保目录…';
    catalogTimer = setTimeout(() => lookup(query, current), 300);
    if (allowAutomatic && automatic.checked) liveTimer = setTimeout(searchLive, 550);
  }
  automatic.onchange = () => {
    try { if (preference) sessionStorage.setItem(preference, automatic.checked ? 'on' : 'off'); } catch { /* In-memory switch still works. */ }
    clearTimeout(liveTimer); liveVersion++;
    liveResults.hidden = true; liveChoices.replaceChildren(); live.disabled = raw.value.trim().length < 2;
    if (automatic.checked && !live.disabled) liveTimer = setTimeout(searchLive, 550);
  };
  raw.addEventListener('compositionstart', invalidate);
  raw.addEventListener('input', event => { if (!event.isComposing) schedule(); });
  raw.addEventListener('compositionend', () => schedule());
  raw.addEventListener('keydown', event => {
    const first = catalogChoices.querySelector('button, a') || liveChoices.querySelector('button, a');
    if (event.key === 'ArrowDown' && first) { event.preventDefault(); first.focus(); }
  });
  form.append(node('p', 'fx-muted', '按长辈本人陈述填写。用药自报仅用于病史记录，给药仍须执行已复核医嘱。'),
    node('label', 'field', [node('span', '', '自报日期'), day]),
    node('label', 'field', [node('span', '', '本人填报的药名'), raw]),
    choose(live, node('label', 'access-check', [automatic, '联网自动补全'])),
    node('small', 'fx-muted', '手动联网或开启自动补全时，仅发送药名至 Wikidata。本标签页记住当前账号的选择。'),
    message, catalogChoices, liveResults, selected,
    node('label', 'field', [node('span', '', '本人陈述的用法'), regimen]), error, node('footer', 'dialog-actions', save));
  const dialog = ctx.detail((row ? '更正用药自报' : '填写体检用药自报') + ' · ' + target, form);
  dialog.dataset.roundsResidentId = residentId;
  dialog.addEventListener('close', invalidate, { once: true });
  raw.focus();
  if (row && !candidate && raw.value.trim().length >= 2) schedule(false);
  const requestId = crypto.randomUUID();
  form.onsubmit = async event => {
    event.preventDefault(); if (save.disabled) return;
    save.disabled = true; error.textContent = '';
    const payload = { residentId, day: day.value, rawName: raw.value.trim(), regimen: regimen.value.trim(),
      reference: candidate?.reference || '', reportId: row?.reportId || '', expectedVersion: row?.version || 0, confirmed: true, requestId };
    try {
      const review = await ctx.confirmChange({ title: row ? '确认更正用药自报' : '确认保存用药自报', target,
        allowComment: true, fields: [['本人填报', payload.rawName], ['药名核对', candidate?.name || '按原话保存，待核对'],
          ['陈述的用法', payload.regimen || '未填写'], ['日期', payload.day]] });
      if (!review || !dialog.open) return;
      const response = await fetch('/api/commands', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: me ? 'portal.reportMedication' : 'care.reportMedication', payload, revision, comment: review.comment || '' }) });
      const data = await response.json();
      if (response.status === 409) { await refresh(); throw new Error('档案刚有更新，请关闭此窗，核对最新记录后重新提交。'); }
      if (!response.ok) throw new Error(data.error || '用药自报保存失败');
      dialog.close(); await refresh(); ctx.toast('用药自报已保存');
    } catch (ex) { error.textContent = ex.message; }
    finally { save.disabled = false; }
  };
}

export function renderMedicationReports(ctx, residentId) {
  const panel = node('section', 'rounds-card medication-source-scope');
  const endpoint = '/api/residents/' + encodeURIComponent(residentId);
  async function refresh() {
    try {
      const data = await ctx.get(endpoint + '/reported-medications');
      const edit = row => reportForm(ctx, residentId, endpoint, data.revision, row, refresh);
      panel.replaceChildren(node('header', 'rounds-heading', [node('h3', '', '体检用药自报'),
        data.canWrite ? btn(ctx, '填写用药', () => edit(null)) : null]),
        ...(data.reports.length ? data.reports.map(row => node('div', 'fx-profile', [historyRow(ctx, row),
          choose(data.canWrite ? btn(ctx, row.name ? '更正记录' : '核对或更正药名', () => edit(row)) : null),
          row.history.length ? node('details', '', [node('summary', '', '查看历次填报（' + row.history.length + '）'),
            ...row.history.map(item => historyRow(ctx, item))]) : null])) : [node('p', 'fx-muted', '尚未填写本人的用药情况。')]));
    } catch (ex) { panel.replaceChildren(node('p', 'fx-muted', ex.message), btn(ctx, '重新读取用药自报', refresh)); }
  }
  refresh(); return panel;
}

export function openExamMedications(ctx) {
  const options = residentField(ctx).options;
  if (!options.length) { ctx.toast('当前没有可选的在住长辈'); return; }
  const select = node('select');
  select.add(new Option('请选择本次体检的长辈', ''));
  options.forEach(option => select.add(new Option(option.label, option.value)));
  const chart = node('div', 'fx-profile');
  select.onchange = () => chart.replaceChildren(...(select.value ? [renderMedicationReports(ctx, select.value)] : []));
  ctx.detail('体检用药自报', node('div', 'fx-profile', [node('label', 'field', [node('span', '', '体检长辈'), select]), chart]));
}
