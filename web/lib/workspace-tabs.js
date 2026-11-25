import { el, icon } from './ui.js';

export const TAB_LIMIT = 10;

export class WorkspaceTabs {
  pages = new Map();
  active = null;
  sequence = 0;

  clear() { this.pages.clear(); this.active = null; this.sequence = 0; }

  activate(key) {
    this.active = key;
    this.pages.get(key).lastUsed = ++this.sequence;
  }

  oldestClosable() {
    let candidate;
    for (const page of this.pages.values()) {
      if (!page.pinned && !page.state.unsaved && (!candidate || page.lastUsed < candidate.lastUsed)) candidate = page;
    }
    return candidate;
  }

  canOpen(key) {
    return this.pages.has(key) || this.pages.size < TAB_LIMIT || Boolean(this.oldestClosable());
  }

  invalidate() {
    for (const page of this.pages.values()) {
      if (!page.state.unsaved) page.node = null;
    }
  }

  ensure(spec) {
    let page = this.pages.get(spec.key);
    if (!page) {
      if (this.pages.size >= TAB_LIMIT) {
        const oldest = this.oldestClosable();
        if (!oldest) return null;
        this.pages.delete(oldest.key);
      }
      page = { ...spec, state: {}, scroll: 0, node: null, pendingReads: 0, lastUsed: ++this.sequence };
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

  strip({ activate, close, refresh, manage, pin }) {
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
      pair.classList.toggle('pinned', Boolean(page.pinned));
      const tab = el('button', 'desk-tab-name', page.title);
      if (page.pinned) tab.setAttribute('aria-label', page.title + '（已固定）');
      if (page.home && page.pinned) tab.prepend(icon('pin', 12));
      tab.type = 'button';
      tab.setAttribute('role', 'tab'); tab.setAttribute('aria-selected', String(selected));
      tab.setAttribute('aria-controls', 'content');
      tab.tabIndex = selected ? 0 : -1;
      tab.title = page.title + (page.pinned ? '（已固定）' : '');
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
      if (!page.home && (page.pinned || selected)) {
        const b = tool((page.pinned ? '取消固定' : '固定') + page.title, 'pin', () => pin(key));
        b.className = 'desk-tab-pin'; b.setAttribute('aria-pressed',String(Boolean(page.pinned)));
        pair.append(b);
      }
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
