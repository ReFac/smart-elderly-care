import { fileControl } from '../lib/file-control.js';
import { asBase64 } from './document-original.js';
import { node } from './shared.js';

export const materialLabels = {idFront: '身份证正面', idBack: '身份证反面', household: '户口本', invoice: '发票'};
const fieldLabels = {name: '证件姓名', birthDate: '出生日期', idNumber: '公民身份号码',
  authority: '签发机关', validity: '有效期限', invoiceDate: '开票日期'};
const fieldsByKind = {idFront: ['name','birthDate','idNumber'], idBack: ['authority','validity'],
  household: ['name','birthDate','idNumber'], invoice: ['invoiceDate']};
export const privateFilename = name => name.replace(/(?:\d[ \t-]*){17}[\dXx]/g, '已遮盖证号');

function field(label, control) {
  return node('label', 'subsidy-field', [node('span', '', label), control]);
}

export function materialForm(ctx, person, {kind = 'idFront', file, material, filing} = {}) {
  const invoice = kind === 'invoice';
  const originalKind = kind;
  const chooser = node('select');
  const kinds = invoice ? ['invoice'] : ['idFront','idBack','household'];
  for (const value of kinds) chooser.add(new Option(materialLabels[value], value));
  chooser.value = kind;
  const month = node('select');
  for (const value of filing?.invoiceMonths || []) month.add(new Option(value, value));
  const invoiceMonth = material?.fields?.invoiceDate?.slice(0, 7);
  if (file && invoice && invoiceMonth && !filing?.invoiceMonths.includes(invoiceMonth))
    month.add(new Option('请选择申报所需的发票月份', ''), 0);
  if (file && invoice) month.value = invoiceMonth || '';
  const input = node('input');
  input.type = 'file'; input.accept = 'image/jpeg,image/png,application/pdf'; input.required = !file;
  const selected = () => input.files[0] || file;
  const attachment = fileControl(input, {selectedFiles: () => {
    const current = selected();
    return current ? [{name: privateFilename(current.name)}] : [];
  }});
  const details = node('div','subsidy-fields');
  let controls;
  function draw() {
    controls = new Map();
    details.replaceChildren();
    const source = file === selected() && chooser.value === originalKind ? material : null;
    for (const key of fieldsByKind[chooser.value]) {
      const control = node('input');
      control.name = key; control.autocomplete = 'off';
      control.type = key === 'birthDate' || key === 'invoiceDate' ? 'date' : key === 'idNumber' ? 'password' : 'text';
      control.maxLength = key === 'idNumber' ? 18 : 60;
      control.value = source?.fields?.[key] || '';
      controls.set(key, control);
      const group = field(fieldLabels[key], control);
      if (key === 'idNumber') {
        const show = node('button', 'btn btn-ghost', '显示号码');
        show.type = 'button';
        show.onclick = () => {
          control.type = control.type === 'password' ? 'text' : 'password';
          show.textContent = control.type === 'password' ? '显示号码' : '隐藏号码';
        };
        details.append(group, show);
      } else details.append(group);
    }
    const ambiguous = source?.ambiguous?.filter(key => controls.has(key));
    if (ambiguous?.length) details.append(node('p', 'form-error',
      '原件未能确认' + ambiguous.map(k => fieldLabels[k]).join('、') + '，请人工核对。'));
  }
  input.addEventListener('change', draw);
  chooser.onchange = draw;
  draw();
  const title = invoice ? '上传发票' : '维护证件';
  const dialog = ctx.dialog({
    title: title + ' · ' + person.name, fields: [], submitLabel: '核对并留存',
    content: node('div','subsidy-fields', [
      field('材料类型', chooser), invoice && field('发票所属月份', month),
      field('原件（PDF、PNG、JPEG，最大 8 MiB）', attachment),
      details,
    ]),
    onSubmit: async () => {
      const chosen = selected();
      if (!chosen?.size || chosen.size > 8 * 1024 * 1024) throw Error('请选择 8 MiB 以内的非空原件');
      if (invoice && !month.value) throw Error('请核对发票所属月份');
      const reviewedFields = {};
      for (const [key, control] of controls) if (control.value.trim()) reviewedFields[key] = control.value.trim();
      if (reviewedFields.name && reviewedFields.name !== person.name) throw Error('证件姓名与当前档案不符，请核对长辈及原件。');
      return ctx.command(filing ? 'ops.subsidyMaterial' : 'dossier.credential', {
        residentId: person.id, kind: chooser.value, fileName: privateFilename(chosen.name),
        imageBase64: await asBase64(chosen), reviewedFields,
        ...(filing ? {month: filing.month, invoiceMonth: invoice ? month.value : ''} : {}),
      }, {
        title, target: person.name, expectedRevision: filing?.revision ?? ctx.state.revision,
        fields: [['材料类型', materialLabels[chooser.value]], ['原件', privateFilename(chosen.name)],
          ...Object.entries(reviewedFields).map(([key, value]) =>
            [fieldLabels[key], key === 'idNumber' ? '已核对（末四位 ' + value.slice(-4) + '）' : value]),
          ...(invoice ? [['发票月份', month.value]] : [])],
      });
    },
  });
  input.form?.addEventListener('reset', () => queueMicrotask(draw));
  return dialog;
}
