import { staffLabel } from './people-labels.js';
import { asBase64 } from './dossier.js';
import { btn, facts, node, section } from './shared.js';

function input(form, title, type, name, required = true) {
  const element = node('input');
  element.type = type;
  element.name = name;
  element.required = required;
  form.append(node('label', 'field', [node('span', '', title), element]));
  return element;
}

export function contractForm(ctx, person, draft = null) {
  const form = node('form', 'dialog-form');
  const number = input(form, '合同编号（选填）', 'text', 'number', false);
  number.maxLength = 100;
  number.value = draft?.fields.number || '';
  const signed = input(form, '签订日期', 'date', 'signedOn');
  signed.max = ctx.state.today;
  signed.value = draft ? draft.fields.signedOn || '' : ctx.state.today;
  const start = input(form, '合同起始日期', 'date', 'startsOn');
  start.value = draft ? draft.fields.startsOn || '' : ctx.state.today;
  const term = node('select');
  if (draft) term.add(new Option('请选择期限', ''));
  term.required = true;
  term.add(new Option('无固定期限', 'open'));
  term.add(new Option('固定期限', 'fixed'));
  form.append(node('label', 'field', [node('span', '', '合同期限'), term]));
  const end = input(form, '合同结束日期', 'date', 'endsOn', false);
  if (draft?.fields.endsOn) {
    term.value = 'fixed';
    end.value = draft.fields.endsOn;
  }
  function range() {
    end.disabled = term.value !== 'fixed';
    end.required = !end.disabled;
    end.closest('label').hidden = end.disabled;
    end.min = start.value;
  }
  term.onchange = start.onchange = range;
  range();
  const upload = input(form, '合同原件（PDF、JPEG 或 PNG，最多 8 MiB）', 'file', 'original');
  if (draft) {
    upload.required = false;
    upload.closest('label').hidden = true;
    form.append(node('p', 'fx-muted', '已带入原件「' + draft.file.name + '」。请核对员工、合同编号及各项日期。'));
  }
  upload.accept = 'application/pdf,image/jpeg,image/png,.pdf,.jpg,.jpeg,.png';
  const error = node('p', 'form-error');
  error.setAttribute('role', 'alert');
  const save = node('button', 'btn btn-primary', '留存此版本');
  save.type = 'submit';
  form.append(error, node('div', 'dialog-actions', save));
  form.onsubmit = async (event) => {
    event.preventDefault();
    if (save.disabled) return;
    save.disabled = true;
    error.textContent = '';
    try {
      const file = draft?.file || upload.files[0];
      if (!file || !file.size || file.size > 8 * 1024 * 1024) throw new Error('请选择不超过 8 MiB 的有效原件。');
      const mime = file.type || (/\.pdf$/i.test(file.name) ? 'application/pdf' : /\.png$/i.test(file.name) ? 'image/png' : 'image/jpeg');
      const payload = {id: person.id, number: number.value.trim(), signedOn:signed.value,
        startsOn:start.value, endsOn:end.disabled ? '' : end.value, filename:file.name,
        mime, imageBase64: await asBase64(file)};
      const saved = await ctx.command('access.staffContract', payload, {
        title:'留存劳动合同原件', target:staffLabel(ctx, person),
        fields:[['签订日期',payload.signedOn], ['合同期限', payload.startsOn + ' 至 ' + (payload.endsOn || '无固定期限')], ['原件',file.name]],
      });
      if (saved) await openEmployment(ctx, person);
    } catch (e) {
      error.textContent = e.message;
    } finally {
      save.disabled = false;
    }
  };
  ctx.detail('留存劳动合同 · ' + staffLabel(ctx, person), form).dataset.managedAccountId = person.id;
}

export async function openEmployment(ctx, person) {
  const path = '/api/staff/' + encodeURIComponent(person.id) + '/employment';
  const content = node('div', 'fx-profile', node('p', 'fx-muted', '正在读取员工资料…'));
  const dialog = ctx.detail(staffLabel(ctx, person) + ' · 劳动合同与工资日', content);
  if (person.id !== ctx.state.user.id) dialog.dataset.managedAccountId = person.id;
  let profile;
  try {
    profile = await ctx.get(path);
  } catch (e) {
    if (!dialog.open) return;
    dialog.close();
    ctx.toast(e.message);
    return;
  }
  if (!dialog.open) return;
  const payroll = node('div', 'fx-profile', [
    facts([['约定工资日',profile.payday ? '每月 ' + profile.payday + ' 日' : '待登记'],
      ['下次工资日',profile.nextPayday || '待登记']]),
  ]);
  if (profile.canEdit) {
    payroll.append(btn(ctx, '设置工资日', () => ctx.dialog({
      title:'设置工资日 · ' + staffLabel(ctx, person),
      description:'当月没有约定日期时，工资日按当月最后一天显示。',
      fields:[{name:'payday', label:'每月工资日', type:'select', required:true, value:profile.payday ? String(profile.payday) : '',
        options:[{value:'',label:'选择日期'},...Array.from({length:31},(_,i)=>({value:String(i+1),label:'每月 '+(i+1)+' 日'}))]}],
      submitLabel:'保存工资日',
      onSubmit: async ({payday}) => {
        const saved = await ctx.command('access.staffPayday',{id:person.id,payday:Number(payday)}, {
          title:'保存工资日', target:staffLabel(ctx, person), fields:[['每月工资日',payday+' 日']],
        });
        if (saved) await openEmployment(ctx, person);
        return saved;
      },
    })));
  }
  const versions = node('div', 'fx-profile');
  if (profile.canEdit) versions.append(btn(ctx, '留存合同新版本', () => contractForm(ctx, person), 'primary'));
  if (!profile.contracts.length) versions.append(ctx.ui.empty('尚未留存劳动合同'));
  for (const contract of profile.contracts) {
    const original = node('a', 'btn btn-secondary', '查看原件');
    original.href = path + '/' + encodeURIComponent(contract.id) + '/original';
    original.target = '_blank';
    original.rel = 'noopener noreferrer';
    versions.append(section('第 ' + contract.version + ' 版 · ' + contract.signedOn + ' 签订', [
      facts([['合同编号',contract.number || '未登记'], ['合同期限',contract.endsOn ? contract.startsOn + ' 至 ' + contract.endsOn : contract.startsOn + ' 起 · 无固定期限'],
        ['留存人',staffLabel(ctx, contract.recordedBy)], ['原件名称',contract.filename]]), original,
    ]));
  }
  content.replaceChildren(section('工资日',payroll),section('劳动合同',versions));
}
