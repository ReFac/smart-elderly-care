import { node } from './shared.js';

const labels = { displayName: '姓名', phone: '手机号' };
const extensions = { pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg' };
export const staffResumeTypes = 'application/pdf,image/png,image/jpeg';

export async function recognizeStaffResume(file, signal) {
  const mime = extensions[file.name.split('.').pop().toLowerCase()];
  if (typeof mime !== 'string' || !file.size || file.size > 8 * 1024 * 1024)
    throw Error('请选择 8 MiB 以内的 PDF、PNG 或 JPEG 简历。');
  const response = await fetch('/api/staff/resume/preview', {
    method: 'POST', headers: { 'Content-Type': mime }, body: file, signal,
  });
  const result = await response.json();
  if (!response.ok) throw Object.assign(Error(result.error || '简历识别失败'), { status: response.status });
  return result;
}

export function staffResumeEvidence({ filename, result }) {
  const sources = Object.entries(result.fields).map(([key, field]) =>
    node('li', '', labels[key] + ' · 第 ' + field.page + ' 页第 ' + field.line + ' 行'),
  );
  const ambiguous = result.ambiguous.map((key) => labels[key]).join('、');
  return node('section', 'access-resume-evidence', [
    node('strong', '', '简历原件 · ' + filename),
    node('p', 'fx-muted', sources.length ? '请对照原件核对已预填的字段，并选择岗位和权限。'
      : '未识别到可以预填的字段，请对照原件手工填写。'),
    sources.length ? node('ul', '', sources) : null,
    ambiguous ? node('p', 'fx-muted', ambiguous + '有多个识别值，请手工填写。') : null,
  ]);
}

export function staffResumeFields(name, phone) {
  const upload = node('input');
  upload.type = 'file';
  upload.accept = staffResumeTypes;
  upload.hidden = true;
  const choose = node('button', 'btn btn-ghost', '选择简历');
  choose.type = 'button';
  choose.addEventListener('click', () => upload.click());
  const selected = node('span', 'fx-muted');
  const scan = node('button', 'btn btn-ghost', '识别简历');
  scan.type = 'button';
  scan.disabled = true;
  const status = node('p', 'fx-muted');
  status.setAttribute('role', 'status');
  const review = node('div', 'fx-profile');
  upload.addEventListener('change', () => {
    review.replaceChildren();
    status.textContent = '';
    scan.disabled = !upload.files.length;
    selected.textContent = upload.files[0]?.name || '';
  });
  scan.addEventListener('click', async () => {
    const [file] = upload.files;
    if (!file) return;
    upload.disabled = true;
    choose.disabled = true;
    scan.disabled = true;
    review.replaceChildren();
    status.textContent = '正在识别简历…';
    try {
      const result = await recognizeStaffResume(file);
      const fields = Object.entries(result.fields);
      const set = { displayName: name, phone };
      status.textContent = fields.length ? '核对识别结果后，选择要填入的项目。' : '没有识别到可直接填入的字段，请按原件手工填写。';
      review.append(...result.ambiguous.map((key) => node('p', 'fx-muted', labels[key] + '有多个识别值，请手工填写。')));
      if (!fields.length) return;
      const checks = fields.map(([key, field]) => {
        const check = node('input');
        check.type = 'checkbox';
        check.checked = !set[key].value;
        review.append(node('label', 'access-check', [check, labels[key] + ' · ' + field.value + '（第 ' + field.page + ' 页）']));
        return { check, field, target: set[key] };
      });
      const apply = node('button', 'btn btn-primary', '填入所选字段');
      apply.type = 'button';
      apply.addEventListener('click', () => {
        for (const { check, field, target } of checks) if (check.checked) {
          target.value = field.value;
          target.dispatchEvent(new Event('input', {bubbles:true}));
        }
        review.replaceChildren();
        status.textContent = '请核对表单并确认创建账号。';
      });
      review.append(apply);
    } catch (error) {
      status.textContent = error.message;
    } finally {
      upload.disabled = false;
      choose.disabled = false;
      scan.disabled = false;
    }
  });
  return node('details', 'access-resume', [
    node('summary', '', '从简历预填'),
    node('p', 'fx-muted', '可识别姓名、手机号。选择获准用于员工登记的简历，确认后发送给机构配置的 OCR 服务。'),
    node('div', 'access-resume-actions', [upload, choose, selected, scan]), status, review,
  ]);
}
