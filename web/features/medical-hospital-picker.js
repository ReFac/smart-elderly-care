import { node } from './shared.js';

export function hospitalOptions(ctx, input) {
  const list = node('ul', 'medical-hospital-options');
  list.id = 'hospital-options-' + crypto.randomUUID();
  list.hidden = true;
  list.setAttribute('role', 'listbox');
  list.setAttribute('aria-label', '医院名称建议');
  const status = node('small', 'fx-muted medical-hospital-status');
  status.setAttribute('role', 'status');
  input.autocomplete = 'off';
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-controls', list.id);
  input.setAttribute('aria-expanded', 'false');
  let sequence = 0, timer, choices = [], highlighted = -1;

  function hide() {
    sequence += 1;
    clearTimeout(timer);
    choices = [];
    highlighted = -1;
    list.hidden = true;
    list.replaceChildren();
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    status.textContent = '';
  }
  function choose(row) {
    input.value = row.name;
    hide();
    input.dispatchEvent(new Event('change', {bubbles: true}));
  }
  function highlight(index) {
    if (!choices.length) return;
    highlighted = (index + choices.length) % choices.length;
    Array.from(list.children).forEach((item, i) => item.setAttribute('aria-selected', String(i === highlighted)));
    const selected = list.children[highlighted];
    input.setAttribute('aria-activedescendant', selected.id);
    selected.scrollIntoView({block: 'nearest'});
  }
  async function fetchOptions(query, ticket) {
    try {
      const result = await ctx.get('/api/catalog/hospitals?' + new URLSearchParams({q: query}));
      if (ticket !== sequence || !input.isConnected || input.value.trim() !== query) return;
      choices = (result.options || []).filter(item => typeof item.name === 'string' && item.name);
      if (!choices.length) {
        status.textContent = '目录中暂未找到，可按原件填写。';
        return;
      }
      list.replaceChildren(...choices.map((option, index) => {
        const item = node('li', '', [
          node('strong', '', option.name),
          node('small', '', option.locality || [option.city, option.district].filter(Boolean).join(' · ')),
        ]);
        item.id = list.id + '-' + index;
        item.setAttribute('role', 'option');
        item.setAttribute('aria-selected', 'false');
        item.addEventListener('pointerdown', event => event.preventDefault());
        item.addEventListener('click', () => choose(option));
        return item;
      }));
      list.hidden = false;
      input.setAttribute('aria-expanded', 'true');
    } catch {
      if (ticket === sequence && input.isConnected)
        status.textContent = '医院目录暂未加载，可按原件填写。';
    }
  }
  function suggest() {
    hide();
    const query = input.value.trim();
    if (!query || query.length > 100) return;
    const ticket = sequence;
    timer = setTimeout(() => fetchOptions(query, ticket), 200);
  }
  input.addEventListener('input', event => { if (!event.isComposing) suggest(); });
  input.addEventListener('compositionend', suggest);
  input.addEventListener('focus', suggest);
  input.addEventListener('blur', hide);
  input.addEventListener('keydown', event => {
    if (event.isComposing || list.hidden) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      hide();
    } else if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault();
      highlight(highlighted === -1 && event.key === 'ArrowUp' ? choices.length - 1
        : highlighted + (event.key === 'ArrowDown' ? 1 : -1));
    } else if (event.key === 'Enter' && highlighted >= 0) {
      event.preventDefault();
      choose(choices[highlighted]);
    }
  });
  return [list, status];
}
