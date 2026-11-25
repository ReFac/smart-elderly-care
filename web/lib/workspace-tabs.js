import { el, icon } from './ui.js';

export class WorkspaceTabs {
  pages = new Map();
  active = null;

  clear() { this.pages.clear(); this.active = null; }

  invalidate() {
    for (const page of this.pages.values()) page.node = null;
  }

  ensure(spec) {
    let page = this.pages.get(spec.key);
    if (!page) {
      page = { ...spec, state: {}, scroll: 0, node: null, pendingReads: 0 };
      this.pages.set(spec.key, page);
    }
    return page;
  }

  remove(key) {
    const keys = [...this.pages.keys()];
    const index = keys.indexOf(key);
    if (index < 0 || this.pages.get(key).pinned) return;
    this.pages.delete(key);
    if (this.active === key) return keys[index - 1] || keys[index + 1];
  }

  strip({ activate, close, refresh, manage }) {
    const bar = el('div', 'desk-tabbar');
    const list = el('div', 'desk-tabs');
    list.setAttribute('role', 'tablist');
    list.setAttribute('aria-label', '已打开的工作页签');
    const scroll = (by) => list.scrollBy({ left: by * Math.max(150, list.clientWidth * .7), behavior: 'smooth' });
    function tool(label, glyph, fn, visibleLabel = '') {
      const b = el('button', 'desk-tab-tool');
      b.type = 'button'; b.title = label; b.setAttribute('aria-label', label);
      b.append(icon(glyph, 14), visibleLabel);
      b.addEventListener('click', fn);
      return b;
    }
    let current;
    for (const [key, page] of this.pages) {
      const selected = key === this.active;
      const pair = el('div', 'desk-tab' + (selected ? ' selected' : ''));
      const tab = el('button', 'desk-tab-name', page.title);
      tab.type = 'button';
      tab.setAttribute('role', 'tab'); tab.setAttribute('aria-selected', String(selected));
      tab.setAttribute('aria-controls', 'content');
      tab.tabIndex = selected ? 0 : -1;
      tab.title = page.title;
      tab.onclick = () => activate(key);
      tab.onkeydown = (event) => {
        const keys = [...this.pages.keys()], pos = keys.indexOf(key);
        const next = { ArrowLeft: (pos + keys.length - 1) % keys.length,
          ArrowRight: (pos + 1) % keys.length, Home: 0, End: keys.length - 1 }[event.key];
        if (event.key === 'Delete' && !page.pinned) { event.preventDefault(); close(key); }
        if (next !== undefined) {
          event.preventDefault(); activate(keys[next]);
          document.querySelector('.desk-tab.selected [role="tab"]')?.focus();
        }
      };
      pair.append(tab);
      if (!page.pinned) {
        const x = tool('关闭' + page.title, 'close', () => close(key));
        x.className = 'desk-tab-close';
        pair.append(x);
      }
      list.append(pair);
      if (selected) current = pair;
    }
    bar.append(tool('向左查看页签','left',()=>scroll(-1)), list,
      tool('向右查看页签','chevron',()=>scroll(1)), tool('管理页签','down',manage),
      tool('刷新当前页签','refresh',refresh,'刷新'));
    requestAnimationFrame(() => {
      if (current?.isConnected) list.scrollLeft = Math.max(0,current.offsetLeft + current.offsetWidth - list.clientWidth + 8);
    });
    return bar;
  }
}
