import { node, today, hasGrant } from './shared.js';
import {
  loadProfileChoices,
  picker,
  textControl,
  regionPicker,
  moneyChoice,
  group,
} from './profile-controls.js';

export async function editResident(ctx, resident, profile) {
  try {
    const { choices, regions } = await loadProfileChoices();
    const value = { ...resident, ...profile };
    const form = node('div', 'dossier-form');
    const name = textControl('姓名', value.name, 'text', { required: true, maxLength: 60 });
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
    form.append(
      group('个人资料', [
        name.element,
        birth.element,
        age.element,
        ...Object.values(selected).map((x) => x.element),
      ]),
    );
    function ageMode() {
      age.control.disabled = Boolean(birth.control.value);
    }
    birth.control.onchange = ageMode;
    ageMode();
    const locations = {};
    for (const [key, label, old, isBirth] of [
      ['birthRegion', '出生地', 'birthplace', true],
      ['nativeRegion', '籍贯', 'nativePlace', true],
      ['addressRegion', '现居住址', 'address', false],
    ]) {
      locations[key] = regionPicker(regions, label, value[key], value[old], isBirth);
      form.append(locations[key].element);
    }
    let sources, pension;
    const notes = {};
    if (hasGrant(ctx, 'relatives')) {
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
      form.append(
        group('家庭情况', [
          selected.livingArrangement.element,
          ...Object.values(notes).map((x) => x.element),
        ]),
      );
      const checks = node('div', 'family-contact-tags');
      sources = choices.fundingSources.map((src) => {
        const c = node('input');
        c.type = 'checkbox';
        c.value = src;
        c.checked = (value.fundingSources || []).includes(src);
        checks.append(node('label', 'access-check', [c, src]));
        return c;
      });
      form.append(group('费用来源（可多选）', [checks]));
      pension = moneyChoice(choices, '养老金月收入', value, 'pensionBand', 'pensionAmount');
      form.append(group('长者养老金收入', [pension.element]));
    }
    ctx.dialog({
      title: '编辑长者登记资料',
      fields: [],
      content: form,
      onSubmit: () => {
        const payload = {
          residentId: resident.id,
          name: name.control.value.trim(),
          birthDate: birth.control.value,
          age: age.control.value,
        };
        for (const [k, item] of Object.entries({ ...selected, ...notes }))
          payload[k] = item.control.value;
        for (const [k, item] of Object.entries(locations)) {
          const data = item.read();
          if (data !== undefined) payload[k] = data;
        }
        if (sources) {
          payload.fundingSources = sources.filter((c) => c.checked).map((c) => c.value);
          Object.assign(payload, pension.read());
        }
        const details = [];
        const names = {
          name: '姓名',
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
          if (key === 'residentId') continue;
          const previous = value[key] ?? (Array.isArray(v) ? [] : '');
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
        if (!details.length) {
          ctx.toast('登记内容没有变化');
          return true;
        }
        return ctx.command('dossier.profile', payload, { target: resident.name, fields: details });
      },
    });
  } catch (err) {
    ctx.toast(err.message);
  }
}
