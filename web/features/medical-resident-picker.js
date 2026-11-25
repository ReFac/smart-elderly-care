import { residentLabel } from './people-labels.js';
import { btn, node } from './shared.js';

function searchable(text) {
  return (text || '').normalize('NFKC').toLocaleLowerCase().replace(/(\d)(?:号房|病房|号室|房间|房|室|号)(?=\s|$)/g, '$1');
}

export function medicalResidentPicker(ctx, candidates, selectedId, onSelection, limit = Infinity) {
  const beds = new Map((ctx.state.beds || []).map(bed => [bed.id, bed]));
  const nameCounts = new Map();
  for (const person of candidates) nameCounts.set(person.name, (nameCounts.get(person.name) || 0) + 1);
  const entries = candidates.map(person => {
    const bed = beds.get(person.bedId);
    const room = ctx.state.residentRooms?.[person.id] || bed?.label?.match(/^(.+)-[^-]+$/)?.[1];
    const location = [...(ctx.state.bedLocations?.[person.bedId] || []),
      room ? room + ' 房' : '', bed?.label ? bed.label + ' 床' : ''].filter(Boolean).join(' / ');
    return {
      person,
      location: location || (nameCounts.get(person.name) > 1 ? '未分房 · 档案 ' + person.id : '未分房'),
      search: [person.name, room, bed?.label, location].map(searchable),
    };
  }).sort((a, b) => a.person.name.localeCompare(b.person.name, 'zh-CN') ||
    a.location.localeCompare(b.location, 'zh-CN', {numeric: true}));

  const list = node('ul', 'medical-resident-options');
  list.id = 'visit-residents-' + crypto.randomUUID();
  list.setAttribute('role', 'listbox');
  list.setAttribute('aria-label', '长辈候选名单');
  const input = node('input');
  input.dataset.visitAutofocus = '';
  input.placeholder = '输入姓名、姓氏或房号';
  input.autocomplete = 'off';
  input.maxLength = 64;
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-controls', list.id);
  const status = node('p', 'medical-resident-status fx-muted');
  status.id = list.id + '-status';
  status.setAttribute('role', 'status');
  input.setAttribute('aria-describedby', status.id);
  const clear = btn(ctx, '清空', () => {
    input.value = '';
    updateQuery();
    input.focus();
  }, 'ghost');
  let selected = entries.find(entry => entry.person.id === selectedId);
  let choices = [], highlighted = -1;

  function showOptions() {
    const words = searchable(input.value.trim()).split(/\s+/).filter(Boolean);
    const matches = selected ? [] : entries.filter(entry => words.every(word => entry.search.some(value => value.includes(word))));
    choices = matches.slice(0, limit);
    highlighted = -1;
    input.removeAttribute('aria-activedescendant');
    list.hidden = choices.length === 0;
    input.setAttribute('aria-expanded', String(!list.hidden));
    clear.hidden = !input.value;
    list.replaceChildren(...choices.map((entry, index) => {
      const choice = node('li', '', [node('strong', '', entry.person.name), node('small', '', entry.location)]);
      choice.id = list.id + '-' + index;
      choice.setAttribute('role', 'option');
      choice.setAttribute('aria-selected', 'false');
      choice.addEventListener('pointerdown', event => event.preventDefault());
      choice.addEventListener('click', () => choose(entry));
      return choice;
    }));
    status.textContent = selected ? '已选 ' + selected.location
      : !entries.length ? '当前没有可办理的长辈。'
        : !choices.length ? '未找到匹配的长辈，请换用姓名或房号搜索。'
          : matches.length > limit ? `已显示前 ${limit} 位，请输入姓名或房号缩小范围。`
          : `${choices.length} 位可选。请选择名单中的长辈。`;
  }

  function choose(entry) {
    selected = entry;
    input.value = residentLabel(ctx, entry.person);
    showOptions();
    onSelection(entry.person);
  }

  function updateQuery(event) {
    selected = undefined;
    onSelection(null);
    if (!event?.isComposing) showOptions();
  }

  input.addEventListener('input', updateQuery);
  input.addEventListener('compositionend', updateQuery);
  input.addEventListener('keydown', event => {
    if (event.isComposing || event.keyCode === 229) return;
    if (event.key === 'Escape' && !list.hidden) {
      event.preventDefault();
      list.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (list.hidden && !selected) showOptions();
      if (!choices.length) return;
      event.preventDefault();
      const direction = event.key === 'ArrowDown' ? 1 : -1;
      highlighted = highlighted < 0 && direction < 0 ? choices.length - 1
        : (highlighted + direction + choices.length) % choices.length;
      Array.from(list.children).forEach((choice, index) =>
        choice.setAttribute('aria-selected', String(index === highlighted)));
      const choice = list.children[highlighted];
      input.setAttribute('aria-activedescendant', choice.id);
      choice.scrollIntoView({block: 'nearest'});
      return;
    }
    if (event.key === 'Enter' && !list.hidden && (highlighted >= 0 || choices.length === 1)) {
      event.preventDefault();
      choose(choices[highlighted < 0 ? 0 : highlighted]);
    }
  });
  if (selected) choose(selected);
  else showOptions();

  return node('div', 'medical-resident-picker', [
    node('div', 'medical-resident-search', [node('label', 'field', [node('span', '', '长辈姓名或房号'), input]), clear]),
    status,
    list,
  ]);
}
