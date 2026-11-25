import {profileSearchKey as searchKey} from '../lib/international-profile.js';
import { bedCard, hasBedCard, printBedCards } from './bedcard.js';
import { isTrial, labelBedStay, statusLabel } from './admission.js';
import { residentLabel } from './people-labels.js';
import { materialForm } from './credential-form.js';
import { badge, btn, canAct, choose, hasGrant, named, node, today } from './shared.js';

const credentialKinds = {idFront:'身份证正面', idBack:'身份证反面', household:'户口本'};

const isArchived = p => ['已退住', '归档到期'].includes(p.status);
const states = [
  ['all', '全部档案', () => true],
  ['current', '在住', p => p.status === '在住'],
  ['pending', '待办理（含试住）', p => p.status === '未入住' || isTrial(p)],
  ['notAdmitted', '未入住', p => p.status === '未入住'],
  ['trials', '试住', p => isTrial(p)],
  ['trial-expired', '试住期满待确认', p => isTrial(p) && !p.bedId],
  ['in-house', '正式入住', p => p.status === '在住' && !isTrial(p)],
  ['archived', '退住归档', isArchived],
];

function indexByResident(records, dateOf) {
  const result = new Map();
  for (const item of records || []) {
    const previous = result.get(item.residentId);
    if (!previous || !dateOf || dateOf(item) >= dateOf(previous)) result.set(item.residentId, item);
  }
  return result;
}

function recordCount(records) {
  const counts = new Map();
  for (const row of records || []) counts.set(row.residentId, (counts.get(row.residentId) || 0) + 1);
  return counts;
}

export function rosterRows(ctx) {
  const data = ctx.state;
  const beds = new Map((data.beds || []).map(row => [row.id, row]));
  const profiles = indexByResident(data.dossierProfiles);
  const assessments = indexByResident((data.assessments || []).filter(a => !a.historyOnly), a => a.scale?.assessedOn || a.date || '');
  const admissions = indexByResident((data.bedMoves || []).filter(m => m.kind === '入住'), m => m.date || '');
  const releases = indexByResident((data.bedMoves || []).filter(m => m.kind === '退住'), m => m.date || '');
  const plans = indexByResident((data.plans || []).filter(p => p.status !== '已取消'), p => p.date || '');
  const bills = recordCount(data.bills);
  const documents = recordCount((data.medicalDocuments || []).filter(doc => doc.hasImage));
  const visits = recordCount((data.medicalVisits || []).filter(visit => !visit.parentVisitId));
  const risks = new Map();
  for (const entry of data.followups || []) {
    if (!entry.riskReport?.topic || !entry.riskReport.level) continue;
    const id = entry.residentId;
    if (!risks.has(id)) risks.set(id, new Map());
    const previous = risks.get(id).get(entry.riskReport.topic);
    if (!previous || (entry.date || '') >= (previous.date || '')) risks.get(id).set(entry.riskReport.topic, entry);
  }
  const originals = new Map();
  for (const visit of data.medicalVisits || []) {
    originals.set(visit.residentId, (originals.get(visit.residentId) || 0) + (visit.attachments?.length || 0));
  }
  return (data.residents || []).map(person => {
    const id = person.id;
    const bed = beds.get(person.bedId);
    const last = !bed && isArchived(person) ? beds.get(releases.get(id)?.beforeBedId) : null;
    const bedId = bed?.id || last?.id;
    const loc = data.bedDirectory?.[bedId] || {};
    const legacy = data.bedLocations?.[bedId] || [];
    const buildingName = loc.buildingName || legacy[1] || '';
    const campusName = loc.campusName || legacy[0] || '';
    const floorLabel = loc.floorLabel || legacy[2] || '';
    const building = loc.buildingId || [campusName, buildingName].filter(Boolean).join(' / ');
    const floor = loc.floorId || [building,floorLabel].filter(Boolean).join(' / ');
    const profile = profiles.get(id) || {};
    const admission = admissions.get(id);
    const location = [campusName, buildingName, floorLabel].filter(Boolean).join(' / ');
    const label = bed ? labelBedStay(bed.label, person) : last ? '原床位 ' + last.label : '未分配';
    const phone = profile.phone || '';
    return { id, person, profile, bed, location, label, building, floor:floorLabel ? floor : '',
      buildingLabel:[campusName,buildingName].filter(Boolean).join(' / '), floorLabel,
      assessment:assessments.get(id), plan:plans.get(id), risks:[...(risks.get(id)?.values() || [])], billCount:bills.get(id) || 0,
      visitCount:visits.get(id) || 0, fileCount:(documents.get(id) || 0) + (originals.get(id) || 0),
      number:admission?.id || '', search:searchKey([person.name, id, admission?.id, label, loc.roomNumber, phone].filter(Boolean).join(' ')),
    };
  });
}

function metrics(ctx, rows, isDossier) {
  const day = today(ctx);
  const beds = ctx.state.beds || [];
  const occupied = beds.filter(b => b.residentId).length;
  const month = day.slice(0, 7);
  const admissions = new Set(rows.filter(r => r.person.admittedAt?.startsWith(month)).map(r => r.id));
  // An existing ledger can also include earlier stays by the same resident.
  for (const m of ctx.state.bedMoves || []) if (m.kind === '入住' && m.date?.startsWith(month)) admissions.add(m.residentId);
  const values = isDossier ? [
    ['在住', rows.filter(r => r.person.status === '在住').length, '人'],
    ['试住中', rows.filter(r => isTrial(r.person) && r.bed).length, '人'],
    ['请假', new Set((ctx.state.leaves || []).filter(r => r.startDate <= day && day <= r.endDate).map(r => r.residentId)).size, '人', hasGrant(ctx,'intake','finance')],
    ['本月入住', admissions.size, '人'],
    ['本月退住', rows.filter(r => r.person.dischargedAt?.startsWith(month)).length, '人'],
    ['今日生日', rows.filter(r => r.person.status === '在住' && r.profile.birthDate?.slice(5) === day.slice(5)).length, '人', hasGrant(ctx,'intake','residents')],
  ] : [
    ['总床位', beds.length, '床'], ['已占用床位', occupied, '床'],
    ['空置可分配', beds.filter(b => b.status === '空闲' && !b.residentId).length, '床'],
    ['床位入住率', beds.length ? (100 * occupied / beds.length).toFixed(1) : '—', beds.length ? '%' : ''],
    ['本月新增入住', admissions.size, '人'],
  ];
  return node('dl', 'roster-metrics', values.filter(([, , , visible]) => visible !== false).map(([label,value,unit]) => node('div', '', [
    node('dt', '', label), node('dd', '', [node('strong','', String(value)), node('small','',unit)]),
  ])));
}

function selector(title, options, value) {
  const control = node('select', 'fx-input');
  control.setAttribute('aria-label', title);
  control.replaceChildren(...options.map(([id, label]) => new Option(label, id)));
  control.value = value;
  return {control, field:node('label','roster-field',[node('span','',title),control])};
}

function progress(ctx, row) {
  const p = row.person;
  const steps = [
    ['基础', hasGrant(ctx,'residents','intake','care'), Boolean(p.name && (p.age != null || row.profile.birthDate))],
    ['健康', hasGrant(ctx,'medical','clinical'), Boolean(p.chronicRegistration || p.allergies || p.risk || p.summary || row.visitCount)],
    ['床位', hasGrant(ctx,'intake','care','residents','clinical'), Boolean(row.bed)],
    ['评估', hasGrant(ctx,'care'), Boolean(row.assessment)],
    ['费用', hasGrant(ctx,'finance'), row.billCount > 0],
  ];
  return node('div', 'roster-progress', steps.filter(([,visible]) => visible).map(([text,,done]) => {
    const chip = node('span',done ? 'roster-done' : 'roster-pending',[node('i','',done ? '✓' : '·'),text]);
    chip.title = text + (done ? '已登记' : '待登记');
    chip.setAttribute('aria-label', chip.title);
    return chip;
  }));
}

function healthSummary(row) {
  const known = row.person.chronicRegistration;
  const chronic = known?.status === 'confirmed' ? known.names.join('、') : known?.status === 'none' ? '经核对无已知慢性病' : '未登记';
  return node('div','roster-notes', [node('span','', '过敏史 · ' + (row.person.allergies || '未登记')),
    node('span','', '慢性病 · ' + chronic)]);
}

export function credentialList(ctx, person) {
  const materials = person.credentialMaterials || {};
  const rows = Object.entries(credentialKinds).map(([kind, label]) => {
    const doc = materials[kind];
    if (!doc) return node('li','',[label,node('span','fx-muted','待归档')]);
    const open = node('a','resident-profile-link','查看留存原件');
    open.href = (hasGrant(ctx, 'intake') ? '/api/dossier/credentials/' : '/api/finance/subsidies/materials/') + encodeURIComponent(doc.id);
    open.target = '_blank';
    open.rel = 'noopener noreferrer';
    const info = doc.fields || {};
    const values = [info.name, info.birthDate, info.idNumber, info.authority, info.validity].filter(Boolean);
    return node('li','',[label,named(open,[doc.at?.slice(0,10), ...values].filter(Boolean).join(' · '))]);
  });
  const body = node('div','fx-profile',node('ul','roster-credential-list',rows));
  if (!isArchived(person) && canAct(ctx, 'dossier.credential'))
    body.append(btn(ctx, '维护证件', () => materialForm(ctx, person)));
  if (ctx.available?.('billing')) {
    const link = node('a','btn btn-secondary','办理民政补贴材料');
    link.href = '#billing?tab=subsidies';
    link.onclick = () => link.closest('dialog')?.close();
    body.append(link);
  }
  ctx.detail(residentLabel(ctx,person) + ' · 证件资料', body);
}

function riskTags(row) {
  return [...(row.person.risk ? [row.person.risk] : []), ...row.risks.map(item =>
    item.riskReport.topic + ' · ' + item.riskReport.level)];
}

export function residentRoster(ctx, options) {
  const dossier = options.mode === 'dossier';
  const allRows = rosterRows(ctx);
  const live = () => ctx.current?.() || ctx;
  const initial = states.some(([id]) => id === options.initialStatus) ? options.initialStatus : dossier ? 'current' : 'all';
  const memory = ctx.workspaceState || {};
  const state = memory.roster ||= {query:'', status:initial, building:'', floor:'', level:'', page:1, order:'recent', selected:[]};
  if (!dossier && initial !== memory.requestedStatus) { state.status = initial; state.page = 1; memory.requestedStatus = initial; }
  const selected = new Set(state.selected);
  const nameFor = row => residentLabel(ctx, row.person);
  const panel = node('section', 'fx-page resident-roster ' + (dossier ? 'roster-dossier' : 'roster-admission'));
  const accessible = hasGrant(ctx,'medical','clinical');
  const showBedCards = hasGrant(ctx,'care','intake');
  const buildingMap = new Map(allRows.filter(r => r.building).map(r => [r.building, r.buildingLabel]));
  const makeOptions = (map, all) => [['', all], ...[...map.entries()].sort((a,b) => a[1].localeCompare(b[1],'zh-CN',{numeric:true}))];
  const building = selector('楼栋',makeOptions(buildingMap,'全部楼栋'),state.building);
  const floor = selector('楼层',[],'');
  const status = selector('入住状态',states.map(([id,title]) => [id,title]),state.status);
  const levels = [...new Set(allRows.map(r => r.person.level).filter(Boolean))].sort();
  const level = selector('护理等级',[['','全部等级'],...levels.map(l=>[l,l])],state.level);
  const query = node('input','fx-input'); query.type='search'; query.maxLength=100;
  query.value=state.query; query.placeholder='姓名、房床号、档案号或手机号'; query.setAttribute('aria-label','检索全部档案');
  const clear = btn(ctx,'重置', () => {
    Object.assign(state,{query:'',building:'',floor:'',level:'',status:initial,page:1,order:'recent'});
    query.value=''; building.control.value=''; level.control.value=''; status.control.value=initial;
    draw();
  });
  const title = dossier ? '长辈档案' : '入住管理';
  const heading = node('header','roster-heading',[node('h1','',title), choose(
    options.create ? btn(ctx, '新建长辈档案',options.create,'primary') : null,
    options.admit ? btn(ctx, '办理入住',options.admit,options.create ? 'secondary' : 'primary') : null,
  )]);
  const submit = node('button','btn btn-primary',[ctx.ui.icon('search',14),'搜索']);
  submit.type = 'submit';
  const filterBar = node('form','roster-filters', [
    building.field, floor.field, status.field, level.field,
    node('label','roster-field roster-query',[node('span','','快捷检索'),query]), choose(submit, clear),
  ]);
  filterBar.setAttribute('role','search');
  filterBar.onsubmit = event => {
    event.preventDefault(); state.query=query.value; state.page=1; draw();
  };
  const list = node('section','roster-list');
  const caption = node('div','roster-list-caption');
  const grid = node('div','roster-table-wrap');
  const footer = node('div','roster-pagination');
  const all = btn(ctx,'查看全部档案',() => {state.status='all'; status.control.value='all'; state.page=1; draw();}, 'ghost');
  list.append(caption, grid, footer, all);
  panel.append(node('div', 'roster-mast', [heading, metrics(ctx,allRows,dossier)]),filterBar,list);
  const clipSelection = () => {
    const valid = new Set(allRows.filter(r => hasBedCard(ctx,r.person)).map(r=>r.id));
    for (const id of selected) if (!valid.has(id)) selected.delete(id);
    state.selected = [...selected];
  };
  if (dossier && showBedCards) clipSelection();
  function action(label, callback) { return btn(ctx,label,callback,'ghost'); }
  function linkName(row) {
    const a = node('a','resident-profile-link',nameFor(row));
    a.href = '#' + (ctx.available?.('dossier') ? 'dossier' : 'residents') + '?resident=' + encodeURIComponent(row.id);
    a.onclick = event => { if (!event.metaKey && !event.ctrlKey && !event.shiftKey && event.button === 0) { event.preventDefault(); options.detail(row.person); } };
    return named(a,[row.person.gender, row.person.age != null && row.person.age + ' 岁',
      dossier && row.profile.phone].filter(Boolean).join(' · ') || row.id);
  }
  function filters() {
    const needle = searchKey(state.query);
    const filterStatus = states.find(([id]) => id === state.status)?.[2] || (() => true);
    return allRows.filter(row => (needle ? row.search.includes(needle) : filterStatus(row.person)) &&
      (!state.building || state.building === row.building) && (!state.floor || state.floor === row.floor) &&
      (!state.level || state.level === row.person.level)).sort((a,b) => {
        const d = (b.person.admittedAt || b.person.registeredAt || '').localeCompare(a.person.admittedAt || a.person.registeredAt || '');
        return (state.order === 'oldest' ? -d : d) || a.id.localeCompare(b.id, 'zh-CN',{numeric:true});
      });
  }
  function draw() {
    if (!buildingMap.has(state.building)) state.building = '';
    building.control.value = state.building;
    const availableFloors = new Map(allRows.filter(r => r.floor && (!state.building || r.building === state.building))
      .map(r => [r.floor,state.building ? r.floorLabel : r.buildingLabel+' · '+r.floorLabel]));
    if (!availableFloors.has(state.floor)) state.floor='';
    floor.control.replaceChildren(...makeOptions(availableFloors,'全部楼层').map(([id,value])=>new Option(value,id)));
    floor.control.value=state.floor;
    status.control.disabled=Boolean(state.query.trim());
    const filtered = filters();
    const size = state.pageSize || 20;
    const pages = Math.max(1,Math.ceil(filtered.length / size));
    state.page=Math.min(pages,Math.max(1,state.page));
    const shown = filtered.slice((state.page-1)*size,state.page*size);
    const tools = choose();
    const controls = [];
    let pageCheck;
    function updateSelection() {
      state.selected = [...selected];
      if (!pageCheck) return;
      const available = controls.map(c=>c.value);
      pageCheck.checked = Boolean(available.length) && available.every(id=>selected.has(id));
      pageCheck.indeterminate = !pageCheck.checked && available.some(id=>selected.has(id));
      pageCheck.disabled = !available.length;
      printer.disabled = !selected.size;
      printer.textContent = selected.size ? '批量打印床头卡（'+selected.size+'）' : '批量打印床头卡';
      cancel.hidden = !selected.size;
    }
    let printer, cancel;
    if (dossier && showBedCards) {
      pageCheck = node('input'); pageCheck.type='checkbox'; pageCheck.setAttribute('aria-label','选择本页可打印的长辈');
      pageCheck.onchange = () => {for (const c of controls) { c.checked = pageCheck.checked;
        if (c.checked) selected.add(c.value); else selected.delete(c.value); } updateSelection();};
      printer = btn(ctx,'批量打印床头卡',()=>printBedCards(live(),selected));
      cancel = action('清除选择',()=>{ selected.clear(); draw(); }); tools.append(printer,cancel);
    }
    if (dossier && accessible) tools.append(action('生成风险标签', () => {
      const subset = selected.size ? allRows.filter(r => selected.has(r.id)) : filtered;
      const rows = subset.filter(r => riskTags(r).length);
      ctx.detail('按已登记资料生成风险标签', node('section','fx-profile', [
        node('p','fx-muted', (selected.size ? '已选择' : '当前筛选') + ' ' + subset.length + ' 人，有已登记风险信息 ' + rows.length + ' 人。'),
        rows.length ? node('ul','roster-risk-list',rows.map(row => node('li','', [
          named(nameFor(row), row.person.risk ? '已登记关注事项 · ' + row.person.risk : ''),
          ...row.risks.map(r => node('p','', r.riskReport.topic + ' · ' + r.riskReport.level + '（' +
            [r.date,r.riskReport.instrument,r.openedBy].filter(Boolean).join(' · ') + '）')),
        ]))) : node('p','fx-muted','未找到已登记的档案关注事项或专项评估。'),
      ]));
    }));
    caption.replaceChildren(node('h2','', dossier ? '档案列表' : '入住全景列表'),
      node('span','roster-count',filtered.length+' 份'), state.query.trim() ? node('small','fx-muted','跨入住状态搜索') : '',tools);
    if (dossier) {
      const scopes = node('div','roster-scopes');
      for (const [key,title] of [['current','在住档案'],['archived','已退住'],['all','全部档案']]) {
        const include = states.find(([id]) => id === key)[2];
        const count = allRows.filter(row => include(row.person)).length;
        const control = btn(ctx,title + ' ' + count, () => {
          query.value=''; state.query=''; state.status=key; status.control.value=key; state.page=1; draw();
        });
        control.setAttribute('aria-pressed',String(!state.query && state.status === key));
        scopes.append(control);
      }
      caption.insertBefore(scopes,tools);
    }
    const dateSort = action('入住日期 ' + (state.order === 'recent' ? '↓' : '↑'),()=>{
      state.order=state.order==='recent'?'oldest':'recent'; state.page=1; draw();
    });
    const cols = [];
    if (pageCheck) cols.push([pageCheck,row=>{
      const c=node('input'); c.type='checkbox'; c.value=row.id; c.disabled=!hasBedCard(ctx,row.person);
      c.checked=selected.has(row.id);
      c.setAttribute('aria-label','选择'+nameFor(row)+'的床头卡');
      if (!c.disabled) controls.push(c);
      c.onchange=()=>{ if(c.checked) selected.add(row.id); else selected.delete(row.id); updateSelection(); };
      return c;
    }]);
    if (!dossier) cols.push(['入住单 / 档案号',row=>named(row.number || '—',row.id)]);
    cols.push(['长辈信息',linkName]);
    if (!dossier) cols.push([dateSort,row=>row.person.admittedAt || '—']);
    cols.push(['床位信息',row=>named(row.label,[row.location,
      isTrial(row.person) && row.person.trialEndsAt ? '试住至 '+row.person.trialEndsAt : dossier && row.person.admittedAt ?
        row.person.admittedAt+' 入住' : ''].filter(Boolean).join(' · '))]);
    if (dossier) {
      cols.push(['护理与服务',row=>named(row.person.level || '未登记',
        row.plan ? [row.plan.title,row.plan.status].filter(Boolean).join(' · ') : '')]);
      if (accessible) cols.push(['基础档案摘要',healthSummary]);
      if (hasGrant(ctx,'finance','medical')) cols.push(['归档资料',row=>node('div','roster-documents',[
        hasGrant(ctx,'finance','intake') ? action('证件 '+Object.keys(row.person.credentialMaterials || {}).length+' / '+Object.keys(credentialKinds).length,
          ()=>credentialList(ctx,row.person)) : null,
        hasGrant(ctx,'medical') ? action(row.visitCount+' 次就诊 · '+row.fileCount+' 份原件',()=>options.medical(row.person)) : null,
      ])]);
      if (accessible) cols.push(['风险标签',row=>riskTags(row).length ?
        node('div','roster-risk-tags',riskTags(row).map(label=>node('span','roster-risk',label))) : '未登记']);
    } else {
      if (hasGrant(ctx,'care')) cols.push(['评估得分',row=>row.assessment?.scale?.total != null ? row.assessment.scale.total+' 分' : '—']);
      cols.push(['能力等级',row=>row.assessment?.scale?.gradeName || row.assessment?.level || '未评估']);
    }
    cols.push(['状态',row=>node('div','roster-notes',[
      badge(ctx,statusLabel(row.person)),
      row.person.admissionStatus === '欠费临时入住' ? badge(ctx,row.person.admissionStatus,'amber') : null,
    ])]);
    if (!dossier) cols.push(['模块进度',row=>progress(ctx,row)]);
    cols.push(['操作',row=>dossier ? choose(
      action('详情',()=>options.detail(row.person)),
      canAct(ctx,'dossier.profile') && !isArchived(row.person) ? action('编辑',()=>options.edit(row.person)) : null,
      hasBedCard(ctx,row.person) ? action('床头卡',()=>bedCard(live(),row.person)) : null
    ) : options.rowActions(row.person)]);
    const table = node('table','roster-table');
    table.append(node('thead','',node('tr','',cols.map(([label])=>{const th=node('th','',label); th.scope='col'; return th;}))),
      node('tbody','',shown.map(row=>node('tr','',cols.map(([,render])=>node('td','',render(row)))))));
    grid.replaceChildren(table);
    if (!shown.length) grid.append(node('p','roster-empty', '当前筛选下没有档案。'));
    const prev=btn(ctx,'上一页',()=>{state.page--; draw();}), next=btn(ctx,'下一页',()=>{state.page++; draw();});
    prev.disabled=state.page<=1; next.disabled=state.page>=pages;
    const sizePicker = node('select','desk-page-size');
    sizePicker.setAttribute('aria-label','每页档案数');
    for (const n of [12,20,50,100]) sizePicker.add(new Option(n + ' 条/页',n));
    sizePicker.value=size;
    sizePicker.onchange=()=>{state.pageSize=Number(sizePicker.value); state.page=1; draw();};
    const jump=node('input','desk-page-jump');
    jump.type='number'; jump.min=1; jump.max=pages; jump.value=state.page;
    jump.setAttribute('aria-label','前往档案页码');
    jump.onchange=()=>{state.page=Math.trunc(Number(jump.value))||1; draw();};
    footer.replaceChildren(node('span','fx-muted','共 '+filtered.length+' 份档案'),
      choose(sizePicker,prev,node('b','desk-page-number',state.page),next,node('label','desk-page-to',['前往',jump,'页'])));
    all.hidden=Boolean(state.query.trim()) || state.status==='all';
    updateSelection();
  }
  for (const [key,field] of Object.entries({building,floor,status,level})) field.control.onchange=()=>{
    state[key]=field.control.value; if(key==='building') state.floor=''; state.page=1; draw();
  };
  query.oninput = ()=>{state.query=query.value; state.page=1; draw();};
  draw();
  return panel;
}
