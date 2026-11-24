const { ipcRenderer } = require('electron');

// Keep the IPC capability in the isolated world. Keyboard activation also emits a trusted click.
window.addEventListener('click', async (event) => {
  if (!event.isTrusted || event.button !== 0 || event.defaultPrevented) return;
  if (location.hash === '#leads') {
    const phone = event.target.closest?.('dialog[open] .lead-detail-head a.lead-phone');
    if (phone?.isConnected && phone.getClientRects().length && phone.protocol === 'tel:') {
      event.preventDefault();
      event.stopImmediatePropagation();
      try {
        if (await ipcRenderer.invoke('leads:call-customer', phone.href)) return;
      } catch { /* The desktop dialer may be unavailable. */ }
      const header = phone.closest('header');
      if (header?.isConnected && !header.querySelector('[role="status"]')) {
        const message = document.createElement('small');
        message.setAttribute('role', 'status');
        message.textContent = '未能打开电话程序，可使用上方号码手动拨打。';
        header.append(message);
      }
      return;
    }
  }
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
