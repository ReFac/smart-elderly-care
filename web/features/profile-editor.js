import {internationalDeployment, nameEditor, postalEditor} from '../lib/international-profile.js';
import { residentLabel } from './people-labels.js';
import { node, today, hasGrant } from './shared.js';
import { registrationContacts } from './family-contacts.js';
import { registrationOptions } from './registration-options.js';
import { openVisitEditor } from './medical-visit-intake.js';
import {
  loadProfileChoices,
  picker,
  textControl,
  regionPicker,
  moneyChoice,
  group,
} from './profile-controls.js';

const draftLabels = {
  name: '姓名', gender: '性别', phone: '本人手机号', birthDate: '出生日期', language: '常用语言',
  maritalStatus: '婚姻情况', education: '文化程度', occupation: '原职业',
  birthplace:'Place of birth', nativePlace:'Place of origin', address:'Postal address',
  birthRegion: '出生地', nativeRegion: '籍贯', addressRegion: '现居住址', idNumber: '证件号',
};

export async function openResidentProfileDraft(ctx, person, draft) {
  const {openDossier} = await import('./dossier.js');
  const live = ctx.current?.() || ctx;
  const target = live.state.residents?.find(r => r.id === person?.id && !['归档到期','已退住'].includes(r.status));
  if (!target || !live.state.allowedActions?.includes('dossier.profile') ||
      !(live.available('dossier') || live.available('residents'))) return live.toast('该档案当前不可编辑。');
  if ((draft?.fields?.name && draft.fields.name !== target.name) || ambiguousIdentity(draft))
    return live.toast('原件的身份信息与所选长辈不符或有多种结果，请先核对原件。');
  const profile = (live.state.dossierProfiles || []).find(p => p.residentId === target.id) || {};
  if (openDossier(live, target, null, 'registration') !== false)
    return editResident(live, target, profile, null, { ...draft, revision: live.state.revision });
}

function ambiguousIdentity(draft) {
  return draft?.ambiguous?.some(k => k === 'name' || k === 'idNumber');
}

export function openNewResidentDraft(ctx, draft) {
  if (draft?.fields?.name && ctx.state.residents.some(p => p.name === draft.fields.name && p.status !== '归档到期'))
    return ctx.toast('已有同名档案，请核对档案号与床位后选择。如果确为不同的人，可在入住管理中单独新建。');
  return newResidentForm(ctx, null, draft);
}

export function newResidentForm(ctx, inquiry, draft) {
  if (!ctx.state.allowedActions?.includes('care.register')) return ctx.toast('当前账号没有建档权限。');
  if (ambiguousIdentity(draft)) return ctx.toast('资料包含多种身份，请分别上传每位长辈的原件。');
  return editResident(ctx, {}, {}, null, draft, {inquiry, revision:ctx.state.revision});
}

function fold(title, children) {
  return node('details', 'profile-disclosure', [node('summary', '', title), ...children]);
}

function showField(value, regions) {
  if (value && Array.isArray(value.codes)) {
    let parent = 'CN';
    return [...value.codes.map(code => {
      const label = regions[parent]?.[code] || code;
      parent = code;
      return label;
    }),value.unlisted,value.detail].filter(Boolean).join(' ');
  }
  return value || '未登记';
}

export async function editResident(ctx, resident, profile, delegated, draft, creation) {
  try {
    const { choices, regions } = await loadProfileChoices({needsRegions:!internationalDeployment()});
    const original = { ...resident, ...profile };
    const value = {...original};
    if (creation?.inquiry) value.name = creation.inquiry.name;
    const form = node('div', 'dossier-form');
    if (draft) {
      const summary = node('section', 'fx-profile');
      summary.append(node('h3', '', '原件预填 · 请核对'));
      for (const [key, candidate] of Object.entries(draft.fields || {})) {
        if (['address','birthplace','nativePlace'].includes(key) && !internationalDeployment()) continue;
        if (!(key in draftLabels) || key === 'idNumber' || candidate == null || candidate === '') continue;
        if (key.endsWith('Region') && !Array.isArray(candidate.codes)) continue;
        if (choices[key] && !choices[key].includes(candidate)) continue;
        if (JSON.stringify(original[key]) !== JSON.stringify(candidate))
          summary.append(node('p', '', [draftLabels[key] + '：', showField(original[key], regions),
            ' → ', node('strong', '', showField(candidate, regions))]));
        value[key] = candidate;
      }
      const uncertain = (draft.ambiguous || []).map(k => draftLabels[k]).filter(Boolean);
      if (uncertain.length) summary.append(node('p','form-error','需人工核对：' + uncertain.join('、')));
      if (summary.children.length === 1) summary.append(node('p','','未识别到可更新的字段，可以手工补充。'));
      form.append(summary);
    }
    if (!creation && !delegated && ctx.state.allowedActions?.includes('dossier.confirmVisit')) {
      form.append(group('病例与过往就诊', [
        ctx.ui.button('手动录入病例', () => openVisitEditor(ctx.current?.() || ctx, resident, 'manual')),
        ctx.ui.button('上传一组就诊资料', () => openVisitEditor(ctx.current?.() || ctx, resident, 'ai')),
      ]));
    }
    const name = textControl('姓名', value.name, 'text', { required: true, maxLength: 60 });
    name.control.name = 'name';
    const international = internationalDeployment();
    const splitName = international && nameEditor(name.control, value.name === original.name ? value.nameParts : null);
    const admission = creation && registrationOptions(ctx, name.control, creation.inquiry);
    const gender = picker('性别', ['女','男'], value.gender === '未登记' ? '' : value.gender);
    const phone = textControl('长辈本人手机号（选填）', value.phone, 'tel', {
      maxLength: 40,
      autocomplete: 'off',
    });
    const birth = textControl('出生日期', value.birthDate, 'date', { max: today(ctx) });
    const ages = Array.from({ length: 126 }, (_, i) => String(i));
    const age = picker(
      '登记年龄（出生日期未知时）',
      ages,
      value.age == null ? '' : String(value.age),
    );
    const selected = {};
    for (const [key, label] of [
      ['language', '常用语言或方言'],
      ['maritalStatus', '婚姻情况'],
      ['education', '文化程度'],
      ['occupation', '原职业'],
    ])
      selected[key] = picker(label, choices[key], value[key]);
    form.append(group('基本信息', [splitName?.element || name.element, !delegated && gender.element, birth.element, age.element, phone.element]));
    if (admission) form.append(admission.element);
    const additional = Object.values(selected).map(x => x.element);
    form.append(fold('其他个人资料', [group('语言、婚姻与职业', additional)]));
    function ageMode() {
      age.control.disabled = Boolean(birth.control.value);
    }
    birth.control.onchange = ageMode;
    ageMode();
    const locations = {};
    if (international) {
      for (const [key, title] of [['birthplace','Place of birth'], ['nativePlace','Place of origin']]) {
        selected[key] = textControl(title, value[key], 'text', {maxLength:120});
      }
      const prefilledText = typeof draft?.fields?.address === 'string' && value.address !== original.address;
      locations.internationalAddress = postalEditor(prefilledText ? null : value.internationalAddress, value.address, {prefilledText});
      form.append(fold('Birthplace and address', [selected.birthplace.element, selected.nativePlace.element, locations.internationalAddress.element]));
    } else {
      for (const [key, label, old, isBirth] of [
        ['birthRegion', '出生地', 'birthplace', true],
        ['nativeRegion', '籍贯', 'nativePlace', true],
        ['addressRegion', '现居住址', 'address', false],
      ]) {
        locations[key] = regionPicker(regions, label, value[key], value[old], isBirth, JSON.stringify(value[key]) !== JSON.stringify(original[key]));
      }
      form.append(fold('出生地、籍贯与现居住址', Object.values(locations).map(x=>x.element)));
    }
    let sources, pension, contacts;
    const notes = {};
    if (!delegated && hasGrant(ctx, 'relatives')) {
      selected.livingArrangement = picker(
        '原居住与照料安排',
        choices.livingArrangement,
        value.livingArrangement,
      );
      for (const [key, label] of [
        ['siblings', '兄弟姐妹及支持情况'],
        ['children', '子女照护分工补充'],
        ['economicNotes', '其他经济情况'],
      ])
        notes[key] = textControl(label, value[key], 'textarea', { maxLength: 500, rows: 2 });
      if (creation) {
        contacts = registrationContacts(ctx, name.control);
        form.append(fold('配偶、子女与紧急联系人', [contacts.element]));
      }
      const household = group('家庭情况', [
          selected.livingArrangement.element,
          ...Object.values(notes).map((x) => x.element),
        ]);
      const checks = node('div', 'family-contact-tags');
      sources = choices.fundingSources.map((src) => {
        const c = node('input');
        c.type = 'checkbox';
        c.value = src;
        c.checked = (value.fundingSources || []).includes(src);
        checks.append(node('label', 'access-check', [c, src]));
        return c;
      });
      pension = moneyChoice(choices, '养老金月收入', value, 'pensionBand', 'pensionAmount');
      form.append(fold('家庭情况与经济支持', [household, group('费用来源（可多选）',[checks]), group('长辈养老金收入', [pension.element])]));
    }
    let clinical;
    if (creation && ctx.state.allowedActions.includes('care.archive')) {
      clinical = {
        summary: textControl('经核实的健康情况', '', 'textarea', {maxLength:1000, rows:2}),
        allergies: textControl('已知过敏信息', '', 'text', {maxLength:1000}),
        risk: textControl('重点关注事项', '', 'textarea', {maxLength:1000, rows:2}),
      };
      form.append(fold('人工核对健康摘要', [group('首次健康摘要（选填）', Object.values(clinical).map(item=>item.element))]));
    }
    const dialog = ctx.dialog({
      title: creation ? '新建长辈档案' : '编辑长辈登记资料',
      submitLabel: creation ? '核对并建立档案' : '核对并保存',
      description: delegated?.description,
      fields: [],
      content: form,
      onSubmit: () => {
        const identity = creation ? {} : delegated ? { requestId: delegated.requestId } : { residentId: resident.id };
        const payload = {
          ...identity,
          name: name.control.value.trim(),
          ...(splitName && {nameParts:splitName.read()}),
          ...(!delegated && {gender: gender.control.value || '未登记'}),
          phone: phone.control.value.trim(),
          birthDate: birth.control.value,
          age: age.control.value,
        };
        for (const [k, item] of Object.entries({ ...selected, ...notes }))
          payload[k] = item.control.value;
        for (const [k, item] of Object.entries(locations)) {
          const data = item.read();
          if (data !== undefined) payload[k] = data;
        }
        const addressText = locations.internationalAddress?.text();
        if (addressText !== undefined) payload.address = addressText;
        if (sources) {
          payload.fundingSources = sources.filter((c) => c.checked).map((c) => c.value);
          Object.assign(payload, pension.read());
        }
        const details = [];
        const names = {
          name: '姓名', nameParts:'Name fields', internationalAddress:'Postal address', address:'Postal address', gender:'性别',
          phone: '长辈本人手机号',
          birthDate: '出生日期',
          age: '登记年龄',
          birthRegion: '出生地',
          nativeRegion: '籍贯',
          addressRegion: '现居住址',
          fundingSources: '费用来源',
          pensionBand: '养老金月收入',
          pensionAmount: '养老金精确金额（元/月）',
        };
        for (const [key, item] of Object.entries({ ...selected, ...notes }))
          names[key] = item.element.querySelector('span').textContent;
        for (const [key, v] of Object.entries(payload)) {
          if (key in identity) continue;
          if (key === 'nameParts') {
            if (Object.entries(v).every(([k,val]) => original.nameParts?.[k] === val) &&
                Object.keys(v).length === Object.keys(original.nameParts || {}).length) delete payload[key];
            else details.push([names[key], Object.values(v).join(' ')]);
            continue;
          }
          const previous = original[key] ?? (Array.isArray(v) ? [] : '');
          if (
            Array.isArray(v)
              ? JSON.stringify(v) === JSON.stringify(previous)
              : typeof v !== 'object' && String(v) === String(previous)
          ) {
            if (key !== 'name') delete payload[key];
            continue;
          }
          const shown = locations[key]
            ? [locations[key].label(), v.detail].filter(Boolean).join(' · ')
            : Array.isArray(v)
              ? v.join('、')
              : v;
          details.push([names[key] || key, shown || '清空']);
        }
        if (creation) {
          const {name, age, gender, ...profile} = payload;
          if (contacts?.members.length) {
            profile.familyContacts = contacts.members;
            details.push(['家庭成员与联系人', contacts.members.map(m=>m.name + ' · ' + m.kind).join('、')]);
          }
          const admissionData = admission.values();
          if (clinical) {
            const health = Object.fromEntries(Object.entries(clinical).map(([k,item])=>[k,item.control.value.trim()]));
            if (Object.values(health).some(Boolean)) {
              if (admissionData.payload.kind === 'archive') throw Error('归档档案只保管历史资料。请清空待签认的健康摘要，或选择待入住。');
              if (!health.summary) throw Error('请填写经核实的健康情况，再签认首次健康摘要。');
              profile.initialHealth = health;
              details.push(['签认首次健康摘要',health.summary], ['已知过敏信息',health.allergies || '未填写'], ['重点关注事项',health.risk || '未填写']);
            }
          }
          return ctx.command('care.register', {...admissionData.payload, name, age, gender, profile}, {
            title: '建立长辈档案', target:name, fields:[...admissionData.details, ...details],
            expectedRevision:creation.revision,
          });
        }
        if (!details.length) {
          ctx.toast('登记内容没有变化');
          return true;
        }
        return ctx.command(delegated ? 'permissionRequest.editProfile' : 'dossier.profile', payload, {
          target: delegated?.target || residentLabel(ctx, resident), fields: details,
          expectedRevision: delegated?.revision ?? draft?.revision,
        });
      },
    });
    if (creation) (splitName?.element.querySelector('input:not([type="hidden"]):not(:disabled)') || name.control).focus();
    return dialog;
  } catch (err) {
    ctx.toast(err.message);
  }
}
