import { field, select } from './shared.js';

export function trialLength(days) {
  return days + ' 天 ' + (Number(days) - 1) + ' 夜';
}

export function trialLastDay(firstDay, days) {
  const end = new Date(firstDay + 'T00:00:00Z');
  end.setUTCDate(end.getUTCDate() + Number(days) - 1);
  return end.toISOString().slice(0, 10);
}

export function trialTermFields(settings, { defaults = false } = {}) {
  return [
    select('trialDays', defaults ? '默认试住时长' : '试住时长',
      Array.from({ length: 365 }, (_, i) => ({ value: String(i + 1), label: trialLength(i + 1) })),
      { value: String(settings?.days || 3) }),
    field('trialPrice', defaults ? '默认一次性试住费（元）' : '一次性试住费（元）', {
      type: 'number', min: 0, max: 99999999, step: '0.01',
      value: settings?.fee ?? '', required: !defaults,
      placeholder: defaults ? '留空，由经办人在入住时填写' : '填写约定总额，免费请填 0',
    }),
  ];
}
