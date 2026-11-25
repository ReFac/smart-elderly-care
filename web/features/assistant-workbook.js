import { btn, node } from './shared.js';
import { medicalResidentPicker } from './medical-resident-picker.js';

const mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
const columnNames = {name:'姓名',birthDate:'出生日期',phone:'联系电话',language:'常用语言',
  maritalStatus:'婚姻状况',education:'文化程度',occupation:'原职业',addressRegion:'现住址',birthRegion:'出生地',nativeRegion:'籍贯'};
const internationalColumns = {name:'Full name',birthDate:'Date of birth',phone:'Phone number',language:'Preferred language',
  maritalStatus:'Marital status',education:'Education',occupation:'Occupation',address:'Postal address',birthplace:'Place of birth',nativePlace:'Place of origin'};
const columns = () => window.NH_DEPLOYMENT?.edition === 'international' ? internationalColumns : columnNames;
const permitted = ctx => ctx.state.allowedActions?.includes('dossier.profile') &&
  (ctx.available('residents') || ctx.available('dossier'));

export function isWorkbook(file) {
  return /\.xlsx?$/i.test(file.name) || [mime,'application/vnd.ms-excel'].includes(file.type);
}

async function response(path, options) {
  const result = await fetch('/api/assistant/workbooks/' + path, {method:'POST', ...options});
  if (!result.ok) throw Error((await result.json()).error || '工作表处理失败，请重试。');
  return result;
}

export async function previewWorkbook(file, signal) {
  return (await response('preview', {body:file, signal})).json();
}

export function workbookButton(ctx, fields = {}) {
  const included = Object.fromEntries(Object.entries(fields).filter(([key, value]) => key in columns() && value && (typeof value === 'string' || key.endsWith('Region') && value.codes?.length)));
  const button = btn(ctx, Object.keys(included).length ? '下载预填工作表' : '下载登记表模板', async () => {
    button.disabled = true;
    try {
      const res = await response('export', {headers:{'Content-Type':'application/json'},body:JSON.stringify({fields:included})});
      const url = URL.createObjectURL(await res.blob());
      const link = document.createElement('a');
      link.href = url; link.download = window.NH_DEPLOYMENT?.edition === 'international' ? 'Resident registration.xlsx' : '长辈登记.xlsx'; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (err) { ctx.toast(err.message); }
    finally { button.disabled = false; }
  });
  button.disabled = !permitted(ctx);
  return button;
}

export function workbookActions({ctx, row, getContext, active, accompany}) {
  const records = row.result?.records || [];
  if (!permitted(ctx) || !records.length) return node('p','assistant-document-hint',
    records.length ? '当前账号缺少登记资料编辑权限。' : '工作表中还没有资料，请填写后重新上传。');
  const root = node('div','assistant-material-target');
  const select = node('select');
  select.setAttribute('aria-label','选择工作表中的长辈');
  for (const item of records) select.add(new Option('第 ' + item.row + ' 行　' + (item.fields.name || '姓名待核对'), String(item.row)));
  const target = node('div');
  const candidates = () => getContext().state.residents.filter(person => !['归档到期','已退住'].includes(person.status));
  function draw() {
    const record = records[select.selectedIndex];
    const name = record.fields.name, people = candidates(), matches = name ? people.filter(p => p.name === name) : [];
    let person = null;
    const info = node('p','assistant-document-hint', Object.entries(record.fields).map(([key,value]) => (columns()[key] || key) + ' ' + (record.labels?.[key] || value)).join('　'));
    const warning = node('p','assistant-document-hint');
    const open = btn(ctx,'预填已有档案',async () => {
      const {openResidentProfileDraft} = await import('./profile-editor.js');
      const live = getContext(), match = candidates().find(p => p.id === person?.id);
      if (!active() || !permitted(live) || !match || open.disabled) return;
      accompany(); await openResidentProfileDraft(live,match,record);
    },'primary');
    const picker = medicalResidentPicker(ctx, people, matches.length === 1 ? matches[0].id : '', picked => {
      person = picked;
      open.disabled = !picked || record.ambiguous.includes('name') || Boolean(name && picked.name !== name);
      warning.textContent = picked && name && picked.name !== name ? '登记表中的姓名与所选档案不同，请核对归属。' :
        record.ambiguous.length ? '请核对这些字段：' + record.ambiguous.map(key=>columns()[key]).join('、') :
        matches.length > 1 ? '有同名长辈，请按房间与床位确认。' : '请核对资料归属，再打开表单。';
    }, 20);
    if (!person) open.disabled = true;
    const controls = [info, picker, warning, open];
    if (getContext().state.allowedActions?.includes('care.register')) {
      const create = btn(ctx,'用此行新建档案',async () => {
        const {openNewResidentDraft} = await import('./profile-editor.js');
        const live = getContext();
        if (!active() || !permitted(live) || !live.state.allowedActions?.includes('care.register')) return;
        accompany(); await openNewResidentDraft(live, record);
      });
      create.disabled = record.ambiguous.includes('name');
      controls.push(create);
    }
    target.replaceChildren(...controls);
  }
  select.onchange = draw;
  root.append(node('label','field',[node('span','','工作表记录'),select]),target);
  draw();
  return root;
}
