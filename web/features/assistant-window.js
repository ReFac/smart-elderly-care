// Keep only the large window's position. Drafts and patient data never enter preferences.
export function floatingWindow(panel, header, account) {
  const storageKey = 'nh-assistant-position:' + account;
  let large, small, drag;
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey));
    if (Number.isFinite(saved?.x) && Number.isFinite(saved?.y)) large = saved;
  } catch {}
  const compact = () => panel.classList.contains('assistant-compact');
  function position(point) {
    const x = Math.max(0, Math.min(point.x, innerWidth - panel.offsetWidth));
    const y = Math.max(0, Math.min(point.y, innerHeight - panel.offsetHeight));
    panel.style.setProperty('--assistant-x', x + 'px');
    panel.style.setProperty('--assistant-y', y + 'px');
  }
  function restore() {
    if (panel.hidden || panel.closest('.assistant-page')) return;
    panel.style.removeProperty('--assistant-x');
    panel.style.removeProperty('--assistant-y');
    const point = compact() ? small : large;
    if (point) position(point);
  }
  function save(x, y) {
    if (compact()) small = {x, y};
    else {
      large = {x, y};
      try { localStorage.setItem(storageKey, JSON.stringify(large)); } catch {}
    }
  }
  header.tabIndex = 0;
  header.title = '拖动窗口，或用方向键移动';
  header.addEventListener('pointerdown', e => {
    if (e.button !== 0 || e.target.closest('button, a') || panel.closest('.assistant-page')) return;
    e.preventDefault();
    const rect = panel.getBoundingClientRect();
    drag = {id:e.pointerId, dx:e.clientX-rect.left, dy:e.clientY-rect.top};
    header.setPointerCapture(e.pointerId);
  });
  const move = e => {
    if (drag?.id === e.pointerId) position({x:e.clientX-drag.dx, y:e.clientY-drag.dy});
  };
  const end = e => {
    if (drag?.id !== e.pointerId) return;
    drag = null;
    const {left, top} = panel.getBoundingClientRect(); save(left, top);
  };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', end);
  window.addEventListener('pointercancel', end);
  header.addEventListener('keydown', e => {
    if (e.target !== header || panel.closest('.assistant-page')) return;
    const delta = {ArrowLeft:[-16,0],ArrowRight:[16,0],ArrowUp:[0,-16],ArrowDown:[0,16]}[e.key];
    if (!delta) return;
    e.preventDefault();
    const rect = panel.getBoundingClientRect();
    position({x:rect.left+delta[0], y:rect.top+delta[1]});
    const moved = panel.getBoundingClientRect(); save(moved.left, moved.top);
  });

  // A native modal makes its siblings inert. Host the companion in the active
  // dialog while a form is open, then return it to the document on close.
  let accompanying = false;
  function followDialog() {
    if (!accompanying || panel.hidden || panel.closest('.assistant-page')) return;
    const host = [...document.querySelectorAll('dialog[open]')].at(-1) || document.body;
    if (host === panel.parentElement) return;
    panel.removeAttribute('popover');
    host.append(panel);
    if (host instanceof HTMLDialogElement && panel.showPopover) {
      // A dialog's scrolling box clips a normal fixed descendant. A manual
      // popover paints above that box while retaining the active modal as its owner.
      panel.popover = 'manual';
      panel.showPopover();
    }
    restore();
  }
  const dialogs = new MutationObserver(followDialog);
  window.addEventListener('resize', restore);
  return {
    restore,
    accompany() {
      accompanying = true;
      document.body.append(panel);
      panel.setAttribute('role', 'dialog');
      panel.classList.add('assistant-compact');
      dialogs.observe(document.body, {subtree:true, attributes:true, attributeFilter:['open'], childList:true});
      followDialog();
      restore();
    },
    expand() {
      panel.classList.remove('assistant-compact');
      restore();
    },
    stop() {
      accompanying = false;
      dialogs.disconnect();
      panel.removeAttribute('popover');
      panel.classList.remove('assistant-compact');
      if (panel.closest('dialog')) document.body.append(panel);
    },
    destroy() {
      dialogs.disconnect();
      panel.removeAttribute('popover');
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', end);
      window.removeEventListener('pointercancel', end);
      window.removeEventListener('resize', restore);
    }
  };
}
