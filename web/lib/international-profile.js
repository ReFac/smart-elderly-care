export function internationalDeployment() {
  const deployment = globalThis.NH_DEPLOYMENT;
  return deployment?.edition === 'international' || Boolean(deployment && !deployment.edition && deployment.language !== 'zh-CN');
}

const clean = value => String(value || '').normalize('NFC').trim().replace(/\s+/g, ' ');

function group(label) {
  const element = document.createElement('fieldset');
  element.className = 'dossier-form-group international-profile';
  const legend = document.createElement('legend');
  legend.textContent = label;
  const grid = document.createElement('div');
  grid.className = 'dossier-form-grid';
  element.append(legend, grid);
  return {element, grid};
}
function field(grid, label, control) {
  const row = document.createElement('label');
  row.className = 'field';
  const caption = document.createElement('span');
  caption.textContent = label;
  row.append(caption, control);
  grid.append(row);
  return row;
}
function input(grid, key, title, value, autocomplete, length) {
  const control = document.createElement('input');
  control.name = key;
  control.value = value || '';
  control.autocomplete = autocomplete;
  control.maxLength = length;
  return {control, row:field(grid, title, control)};
}

// Keep one canonical field for legacy commands, OCR, duplicate checks and confirmations.
export function nameEditor(display, initial, {optional=false}={}) {
  const {element, grid} = group(optional ? 'Name (optional)' : 'Name');
  const mode = document.createElement('select');
  mode.add(new Option('Given and family names', 'parts'));
  mode.add(new Option('Full or single name', 'single'));
  field(grid, 'Name format', mode);
  const parts = initial || (display.value ? {single:display.value} : {});
  mode.value = parts.single ? 'single' : 'parts';
  const fields = {};
  for (const [key, title, auto] of [
    ['given','Given name','given-name'], ['middle','Middle name (optional)','additional-name'],
    ['family','Family name','family-name'], ['single','Full or single name','name'],
  ]) fields[key] = input(grid, key, title, parts[key], auto, 60);
  display.type = 'hidden';
  display.required = false;
  element.append(display);
  const read = () => Object.fromEntries(Object.entries(fields)
    .filter(([, f]) => !f.control.disabled && clean(f.control.value))
    .map(([k, f]) => [k, clean(f.control.value)]));
  let syncing = false;
  function update() {
    for (const [k, f] of Object.entries(fields)) {
      f.row.hidden = (k === 'single') !== (mode.value === 'single');
      f.control.disabled = f.row.hidden;
    }
    const values = read();
    for (const [k, f] of Object.entries(fields)) {
      f.control.required = !f.control.disabled && k !== 'middle' && (!optional || Object.keys(values).length > 0);
    }
    display.value = Object.values(values).join(' ');
    const first = fields[mode.value === 'single' ? 'single' : 'given'].control;
    first.setCustomValidity([...display.value].length > 60 ? 'Display name must be 60 characters or fewer.' : '');
    syncing = true;
    display.dispatchEvent(new Event('input', {bubbles:true}));
    syncing = false;
  }
  display.addEventListener('input', () => {
    if (!syncing) {
      mode.value = 'single';
      fields.single.control.value = display.value;
      update();
    }
  });
  for (const {control} of Object.values(fields)) control.addEventListener('input', update);
  mode.addEventListener('change', update);
  update();
  return {element, read, reset() {
    for (const {control} of Object.values(fields)) control.value = '';
    mode.value = 'parts';
    update();
  }};
}

export function postalEditor(initial, legacy='', {prefilledText=false}={}) {
  const {element, grid} = group('Postal address');
  const raw = !Object.keys(initial || {}).length && legacy ? document.createElement('textarea') : null;
  let format;
  if (raw) {
    format = document.createElement('select');
    format.add(new Option('Address as supplied','raw'));
    format.add(new Option('Structured address','structured'));
    field(grid,'Address format',format);
    raw.maxLength = 300;
    raw.rows = 2;
    raw.value = legacy;
    field(grid,'Address as supplied',raw);
  }
  const fields = {};
  for (const [key, title, auto, length] of [
    ['street','Street address','address-line1',100], ['unit','Apartment, suite or unit','address-line2',60],
    ['locality','City or town','address-level2',60], ['region','State, province or region','address-level1',60],
    ['postalCode','Postal or ZIP code','postal-code',24], ['country','Country or territory','country-name',60],
  ]) fields[key] = input(grid, key, title, initial?.[key], auto, length);
  function changeFormat() {
    const rawMode = format?.value === 'raw';
    if (raw) raw.parentElement.hidden = raw.disabled = !rawMode;
    for (const f of Object.values(fields)) f.row.hidden = f.control.disabled = rawMode;
  }
  format?.addEventListener('change',changeFormat);
  changeFormat();
  const values = () => Object.fromEntries(Object.entries(fields).filter(([,f])=>clean(f.control.value))
    .map(([k,f])=>[k,clean(f.control.value)]));
  const original = JSON.stringify(values());
  return {element, read() {
    if (format?.value === 'raw' || (!format && JSON.stringify(values()) === original)) return undefined;
    return values();
  }, text() {
    return format?.value === 'raw' && (prefilledText || clean(raw.value) !== legacy) ? clean(raw.value) : undefined;
  }, label:()=>format?.value === 'raw' ? raw.value : Object.values(values()).join(', ')};

}

// Accent-insensitive spelling and formatting-insensitive dial strings for user-facing lookup.
export const profileSearchKey = value => String(value ?? '').trim().normalize('NFKD')
  .replace(/(\p{Script=Latin})\p{M}+/gu, '$1').toLocaleLowerCase()
  .replace(/[+\d][\d().\s-]{5,}\d/g, match => match.replace(/[().\s-]/g, ''));
