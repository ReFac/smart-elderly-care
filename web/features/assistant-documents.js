import { previewOriginal } from './assistant-original.js';
import { staffLabel } from './people-labels.js';
import { node } from './shared.js';
import { openVisitEditor } from './medical-visit-intake.js';
import { materialDestinations, materialKinds } from './assistant-materials.js';
import { privateFilename } from './credential-form.js';

const resume = '员工简历';
const contract = '劳动合同';
const medicalTypes = ['就诊记录', 'CT影像', '检查报告', '处方', '医嘱'];
const clinical = row => medicalTypes.includes(row.category);
const types = [resume, contract, ...Object.keys(materialKinds), ...medicalTypes, '其他'];
const formats = { pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg' };
const mib = 1024 * 1024;

export function documentFiles(files) {
  if (!files.length || files.length > 12 || files.reduce((n, f) => n + f.size, 0) > 24 * mib)
    throw Error('每组可选 1–12 份图片或 PDF，合计上限 24 MiB。');
  return files.map(file => {
    const mime = file.type || formats[file.name.split('.').pop().toLowerCase()];
    if (!Object.values(formats).includes(mime) || !file.size || file.size > 8 * mib)
      throw Error('请检查「' + file.name + '」，每份须为 8 MiB 以内的 JPEG、PNG 或 PDF。');
    return { file, mime, category: '其他', checked: true };
  });
}

export const canReadDocuments = ctx => ['owner', 'staff'].includes(ctx.state?.user?.kind) &&
  (ctx.state.user.kind === 'owner' || ctx.state.user.permissions?.includes('assistants'));

const canOpenStaff = ctx => ctx.available('access') && ctx.state.allowedActions?.includes('access.create');
const canOpenVisit = ctx => ctx.state.allowedActions?.includes('dossier.confirmVisit');

function action(label, fn, primary = false) {
  const button = node('button', 'btn ' + (primary ? 'btn-primary' : 'btn-ghost'), label);
  button.type = 'button';
  button.addEventListener('click', fn);
  return button;
}

export function documentIntake(getContext, changed, hide) {
  const card = node('section', 'assistant-document-card');
  card.setAttribute('aria-label', '健康助理文件整理');
  let rows = [], stage = '', active, originalDialog, progress = '';

  function stop() {
    if (active) {
      active.abort();
      active = null;
      stage = 'choose';
      progress = '识别已暂停，可以继续处理本组剩余文件。';
      render();
    }
  }
  function discard() {
    stop();
    originalDialog?.close();
    originalDialog = null;
    rows = [];
    stage = progress = '';
    render();
  }
  function start(files) {
    if (!canReadDocuments(getContext())) throw Error('当前账号没有文件整理权限。');
    if (rows.length) throw Error('请先处理或关闭当前这组文件。');
    rows = documentFiles(files);
    stage = 'choose';
    render();
  }
  async function recognize() {
    if (active || !canReadDocuments(getContext())) return;
    const request = new AbortController();
    active = request;
    stage = 'reading';
    try {
      for (const [index, row] of rows.entries()) {
        if (row.result) continue;
        progress = '正在阅读第 ' + (index + 1) + ' / ' + rows.length + ' 份 · ' + privateFilename(row.file.name);
        render();
        try {
          const response = await fetch('/api/assistant/documents/preview', {
            method: 'POST', headers: { 'Content-Type': row.mime }, body: row.file, signal: request.signal,
          });
          const result = await response.json();
          if (request.signal.aborted) return;
          if ([401, 403].includes(response.status)) {
            await getContext().refreshWorkspace();
            if (request.signal.aborted || active !== request) return;
            discard();
            return getContext().toast(result.error || '当前账号无法识别文件。');
          }
          if (!response.ok) throw Error(result.error || '文件识别服务暂不可用。');
          row.result = result;
          row.category = types.includes(result.category) ? result.category : '其他';
          row.error = '';
        } catch (error) {
          if (request.signal.aborted) return;
          row.error = error.message || '文件读取失败。';
        }
      }
      if (!request.signal.aborted) {
        stage = 'review';
        progress = '';
      }
    } finally {
      if (active === request) { active = null; render(); }
    }
  }
  async function staff(row) {
    if (!canOpenStaff(getContext())) return getContext().toast('当前账号没有新增员工的权限。');
    if (document.querySelector('dialog[open]')) return getContext().toast('请先关闭当前业务窗口。');
    const { openStaffResumeReview } = await import('./access.js');
    if (!rows.includes(row) || stage !== 'confirmed' || card.closest('[hidden], [inert]') ||
        !canOpenStaff(getContext())) return;
    const draft = {filename: row.file.name, result: row.result?.resume || {fields: {}, ambiguous: []}};
    hide();
    getContext().go('access', null, () => openStaffResumeReview(getContext(), draft));
  }
  function contractFields(row) {
    const ctx = getContext();
    if (!ctx.state.allowedActions?.includes('access.staffContract'))
      return node('small', '', '需要员工合同管理权限');
    const select = node('select');
    select.setAttribute('aria-label', privateFilename(row.file.name) + '所属员工');
    select.add(new Option('选择合同所属员工', ''));
    const staff = (ctx.state.accounts || []).filter(a => a.kind === 'staff');
    for (const account of staff) select.add(new Option(staffLabel(ctx, account) + ' · ' + account.username, account.id));
    const open = action('核对劳动合同', async () => {
      if (document.querySelector('dialog[open]')) return ctx.toast('请先关闭当前业务窗口。');
      const {contractForm} = await import('./staff-employment.js');
      const live = getContext();
      const target = live.state.accounts?.find(a => a.kind === 'staff' && a.id === select.value);
      if (!rows.includes(row) || stage !== 'confirmed' || card.closest('[hidden], [inert]') ||
          !target || !live.state.allowedActions?.includes('access.staffContract')) return;
      hide();
      live.go('access', null, () => contractForm(live, target, {file: row.file, fields: row.result?.contract || {}}));
    });
    open.disabled = true;
    select.onchange = () => {open.disabled = !select.value;};
    return [select, open];
  }
  function visits(mode = 'ai') {
    const chosen = rows.filter(row => row.checked && clinical(row));
    if (!chosen.length) return;
    if (!canOpenVisit(getContext())) return getContext().toast('当前账号没有核对就诊记录的权限。');
    if (document.querySelector('dialog[open]')) return getContext().toast('请先关闭当前业务窗口。');
    hide();
    openVisitEditor(getContext(), null, mode, '', chosen.map(({ file, mime, category }) => ({file, mime, category})));
  }
  function fileRow(row) {
    const title = node('strong', '', privateFilename(row.file.name));
    const parts = [title];
    if (row.result?.pageCount) parts.push(node('small', '', row.result.pageCount + ' 页'));
    if (stage === 'choose' || stage === 'review') {
      parts.push(action('移除', () => {
        rows = rows.filter(item => item !== row);
        if (!rows.length) return discard();
        render();
      }));
    }
    if (stage === 'review') {
      const select = node('select');
      select.setAttribute('aria-label', privateFilename(row.file.name) + '的文件类型');
      for (const type of types) select.add(new Option(type, type));
      select.value = row.category;
      select.onchange = () => {row.category = select.value; delete row.personId;};
      parts.push(select);
    }
    if (stage === 'confirmed') {
      parts.push(node('small', '', row.category));
      if (row.category === resume) {
        parts.push(canOpenStaff(getContext()) ? action('打开新增员工表单', () => staff(row)) :
          node('small', '', '需要新增员工权限'));
      } else if (row.category === contract) {
        parts.push(contractFields(row));
      } else if (materialKinds[row.category]) {
        const category = row.category;
        parts.push(materialDestinations(row, getContext,
          () => rows.includes(row) && row.category === category && stage === 'confirmed' &&
            !card.closest('[hidden], [inert]'), hide));
      } else if (clinical(row) && canOpenVisit(getContext())) {
        const check = node('input');
        check.type = 'checkbox';
        check.checked = row.checked;
        check.onchange = () => {row.checked = check.checked; render();};
        parts.push(node('label', 'assistant-document-check', [check, '归入本次就诊']));
      }
    }
    if (stage === 'review' && (row.error || row.result?.note))
      parts.push(node('p', 'assistant-document-hint', row.error || row.result.note));
    if (stage === 'review' || stage === 'confirmed') {
      parts.push(action('查看原件', () => {
        if (canReadDocuments(getContext())) originalDialog = previewOriginal(getContext(), row);
      }));
    }
    if ((stage === 'review' || stage === 'confirmed') && row.result?.excerpt)
      parts.push(node('details', 'assistant-document-excerpt', [node('summary', '', '识别文字节选'),
        node('p', '', row.result.excerpt)]));
    return node('li', '', parts);
  }
  function render() {
    card.replaceChildren();
    if (rows.length) {
      const heading = stage === 'review' ? '这些文件的分类正确吗？' :
        stage === 'confirmed' ? '已确认分类' : '阅读上传资料';
      const hint = stage === 'review' ? (rows.length === 1 && rows[0].category === resume
        ? '这看起来是一份简历。确认后可打开新增员工表单，核对姓名和手机号，并手动选择岗位、权限。'
        : '请逐份核对，可以在列表里改正分类。') :
        stage === 'confirmed' ? '请选择要打开的业务表单。资料经核对并保存后才写入记录。' :
        '确认后由机构 OCR 读取文字，云端模型建议分类。无可读文字的照片可提交机构视觉模型辨认类型。';
      const footer = node('div', 'assistant-document-actions');
      if (stage === 'choose') footer.append(action('识别并分类', recognize, true));
      if (stage === 'review') {
        footer.append(action('确认分类', () => {stage = 'confirmed'; render();}, true));
        if (rows.some(r => r.error)) footer.append(action('重试未识别文件', recognize));
      }
      if (stage === 'confirmed') {
        const medical = rows.filter(clinical);
        if (medical.length && canOpenVisit(getContext())) {
          const open = action('整理所选就诊资料', () => visits(), true);
          open.disabled = !medical.some(r => r.checked);
          footer.append(open);
          if (medical.some(r => r.checked && r.error))
            footer.append(action('手动核对并归档', () => visits('manual')));
        }
        footer.append(action('修改分类', () => {stage = 'review'; render();}));
      }
      footer.append(action('关闭本组', discard));
      card.append(node('h3', '', heading), node('p', '', hint),
        node('ul', '', rows.map(fileRow)));
      if (stage === 'confirmed' && rows.some(clinical))
        card.append(node('p', '', canOpenVisit(getContext())
          ? '同一位长辈、同一次就诊的原件可一起勾选。下一步选择长辈和就诊记录。'
          : '整理就诊资料需要病历核对权限。'));
      if (stage === 'confirmed' && rows.some(r => r.category === '其他'))
        card.append(node('p', '', '其他文件可查看识别文字，目前没有对应的预填表单。'));
      if (progress) card.append(node('p', 'assistant-document-hint', progress));
      card.append(footer);
    }
    changed();
  }
  return {card, start, stop, discard, get present() {return Boolean(rows.length);}, get busy() {return Boolean(active);}};
}
