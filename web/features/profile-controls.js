import { node } from './shared.js';

let catalogs;
const villageRequests = new Map();
function loadCityVillages(regions, city) {
  if (!villageRequests.has(city)) {
    villageRequests.set(
      city,
      fetch('/assets/henan-villages/' + city + '.json')
        .then(async (response) => {
          if (!response.ok) throw Error('村居目录暂时无法读取');
          Object.assign(regions, await response.json());
        })
        .catch((error) => {
          villageRequests.delete(city);
          throw error;
        }),
    );
  }
  return villageRequests.get(city);
}
export function loadProfileChoices() {
  if (!catalogs) {
    catalogs = Promise.all(
      ['dossier-choices', 'address-regions'].map(async (name) => {
        const response = await fetch('/assets/' + name + '.json');
        if (!response.ok) throw new Error('档案选项目录未能加载，请重试。');
        return response.json();
      }),
    )
      .then(([choices, regions]) => ({ choices, regions }))
      .catch((e) => {
        catalogs = null;
        throw e;
      });
  }
  return catalogs;
}

export function picker(label, values, current = '', required = false) {
  const control = node('select');
  control.add(new Option(required ? '请选择' : '未登记', ''));
  for (const value of values) control.add(new Option(value, value));
  if (current && !values.includes(current))
    control.add(new Option(current + '（原记录）', current));
  control.value = current || '';
  control.required = required;
  return { control, element: node('label', 'field', [node('span', '', label), control]) };
}

export function textControl(label, value = '', type = 'text', config = {}) {
  const control = node(type === 'textarea' ? 'textarea' : 'input');
  if (type !== 'textarea') control.type = type;
  Object.assign(control, config, { value: value ?? '' });
  return { control, element: node('label', 'field', [node('span', '', label), control]) };
}
export const group = (title, fields) =>
  node('fieldset', 'dossier-form-group', [
    node('legend', '', title),
    node('div', 'dossier-form-grid', fields),
  ]);

export function regionPicker(regions, label, stored, legacy = '', birth = false) {
  const previous = stored?.codes || [];
  const controls = [];
  const grid = node('div', 'dossier-form-grid');
  const status = node('small', 'fx-muted');
  const box = node('fieldset', 'dossier-form-group', [
    node('legend', '', label),
    legacy && !previous.length
      ? node('p', 'fx-muted', '原登记：' + legacy + '。选择新区划后更新。')
      : null,
    grid,
    status,
    !birth
      ? node(
          'small',
          'fx-muted',
          '省市区使用离线目录。河南可选至村居，门牌或其他地区街巷在详址补充。地名有调整时可选择「目录未收录」。',
        )
      : null,
  ]);
  const names = ['省份', '城市或地区', '区县', '乡镇或街道', '村或社区'].slice(0, birth ? 3 : 5);
  const detail = birth
    ? null
    : textControl('街巷、门牌与楼室', stored?.detail || '', 'text', { maxLength: 120 });
  const missing = textControl(
    '未收录的区划名称（按有效证件填写）',
    stored?.unlisted || '',
    'text',
    { maxLength: 100 },
  );
  let changed = false;
  async function moreVillages() {
    const city = controls[1].control.value;
    status.replaceChildren();
    if (birth || !/^41[0-9]{2}$/.test(city) || city === '4104') return;
    status.textContent = '正在读取本地村居目录…';
    try {
      await loadCityVillages(regions, city);
      if (controls[1].control.value !== city) return;
      status.replaceChildren();
      fill(4, false);
      if (previous[3] && previous[3] === controls[3].control.value) {
        controls[4].control.value = previous[4] || (stored?.unlisted ? 'unlisted' : '');
        fill(5, false);
      }
    } catch {
      if (controls[1].control.value !== city) return;
      const retry = node('button', 'btn btn-ghost', '重新读取村居');
      retry.type = 'button';
      retry.onclick = moreVillages;
      status.replaceChildren('本地村居目录读取失败。', retry);
    }
  }
  for (const name of names) {
    const item = picker(name, []);
    controls.push(item);
    grid.append(item.element);
  }
  function fill(start, initial = false) {
    for (let n = start; n < controls.length; n++) {
      const parent = n ? controls[n - 1].control.value : 'CN';
      const entries = Object.entries(regions[parent] || {});
      if (n === 0) entries.sort(([a], [b]) => Number(b === '41') - Number(a === '41'));
      const { element, control } = controls[n];
      control.replaceChildren(new Option(n === 0 ? '未登记，选择省份' : '请选择' + names[n], ''));
      for (const [code, name] of entries) control.add(new Option(name, code));
      if (n > 0 && entries.length) control.add(new Option('目录未收录', 'unlisted'));
      if (initial)
        control.value =
          previous[n] || (stored?.unlisted && n === previous.length ? 'unlisted' : '');
      element.hidden = n > 0 && !entries.length;
      control.disabled = element.hidden;
      control.required = n > 0 && n < (birth ? 2 : 3) && Boolean(controls[0].control.value);
    }
    if (detail) {
      detail.control.disabled = !controls[0].control.value;
    }
    missing.element.hidden = !controls.some((x) => x.control.value === 'unlisted');
    missing.control.disabled = missing.element.hidden;
    missing.control.required = !missing.element.hidden;
  }
  controls.forEach(({ control }, i) =>
    control.addEventListener('change', () => {
      changed = true;
      fill(i + 1);
      if (i <= 1) moreVillages();
    }),
  );
  if (detail) {
    grid.append(detail.element);
    detail.control.addEventListener('input', () => {
      changed = true;
    });
  }
  grid.append(missing.element);
  missing.control.oninput = () => {
    changed = true;
  };
  fill(0, true);
  moreVillages();
  return {
    element: box,
    read() {
      if (!changed) return undefined;
      const codes = controls
        .filter((x) => !x.control.disabled && x.control.value && x.control.value !== 'unlisted')
        .map((x) => x.control.value);
      if (
        codes.length === 4 &&
        codes[3] === previous[3] &&
        !regions[codes[3]] &&
        (previous[4] || stored?.unlisted)
      ) {
        return { ...stored, detail: detail?.control.value.trim() || '' };
      }
      return {
        codes,
        detail: codes.length ? detail?.control.value.trim() || '' : '',
        ...(!missing.control.disabled ? { unlisted: missing.control.value.trim() } : {}),
      };
    },
    label() {
      return controls
        .filter((x) => x.control.value)
        .map((x) =>
          x.control.value === 'unlisted'
            ? missing.control.value
            : x.control.selectedOptions[0].text,
        )
        .join(' · ');
    },
  };
}

export function moneyChoice(choices, label, source, bandKey, amountKey) {
  const band = picker(label, choices.amountBands, source[bandKey]);
  const amount = textControl('精确金额（元/月）', source[amountKey], 'number', {
    min: 0,
    max: 99999999.99,
    step: '0.01',
  });
  const sync = () => {
    amount.element.hidden = band.control.value !== '精确金额';
    amount.control.disabled = amount.element.hidden;
    amount.control.required = !amount.control.disabled;
  };
  sync();
  band.control.onchange = sync;
  return {
    element: node('div', 'dossier-form-grid', [band.element, amount.element]),
    band: band.control,
    read: () => ({
      [bandKey]: band.control.value,
      [amountKey]: amount.control.disabled ? '' : amount.control.value,
    }),
  };
}
export function displayAmount(band, amount) {
  return band === '精确金额'
    ? Number(amount).toLocaleString('zh-CN', { minimumFractionDigits: 2 }) + ' 元/月'
    : band || '未登记';
}
