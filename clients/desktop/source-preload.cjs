const { ipcRenderer } = require('electron');

// Keep the IPC capability in the isolated world. Keyboard activation also emits a trusted click.
window.addEventListener('click', async (event) => {
  if (!event.isTrusted || event.button !== 0 || event.defaultPrevented) return;
  const link = event.target.closest?.('#assistant-chat:not([hidden]) a.assistant-source-link');
  if (!link || !link.isConnected || !link.getClientRects().length || link.origin === location.origin) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  try {
    if (await ipcRenderer.invoke('assistant:open-public-source', link.href)) return;
  } catch { /* The institution window may have been closed during the lookup. */ }
  const status = link.closest('li');
  if (status?.isConnected && !status.querySelector('[role="status"]')) {
    const hint = document.createElement('small');
    hint.setAttribute('role', 'status');
    hint.textContent = '暂时无法打开此公开来源。';
    status.append(hint);
  }
}, true);
