const { ipcRenderer } = require('electron');

function medicineReference(href) {
  let url;
  try { url = new URL(href); } catch { return false; }
  if (url.username || url.password) return false;
  if (url.origin === 'https://www.wikidata.org')
    return /^\/wiki\/Q[1-9]\d*$/.test(url.pathname) && !url.search && !url.hash;
  if (url.origin === 'https://www.nhsa.gov.cn')
    return url.pathname === '/module/download/downfile.jsp' && /^#page=[1-9]\d{0,3}$/.test(url.hash) &&
      /^\?classid=0&filename=[a-f0-9]{32}\.pdf$/.test(url.search);
  return url.origin === 'https://pharm.ncmi.cn' && url.pathname === '/pharm/fullText/search.do' &&
    !url.hash && url.searchParams.size === 1 && Boolean(url.searchParams.get('keyWord'));
}

function hospitalMap(href) {
  let url;
  try { url = new URL(href); } catch { return false; }
  if (url.username || url.password || url.hash) return false;
  const query = url.searchParams;
  if (url.origin === 'https://www.google.com' && url.pathname === '/maps/search/') {
    const place = query.get('query_place_id');
    return Boolean(query.get('query')) && query.get('api') === '1'
      && query.size === (place ? 3 : 2) && (!place || /^[a-zA-Z0-9_-]{1,160}$/.test(place));
  }
  return url.origin === 'https://uri.amap.com' && url.pathname === '/search' && query.size === 2
    && Boolean(query.get('keyword')) && query.get('view') === 'map';
}

// Keep the IPC capability in the isolated world. Keyboard activation also emits a trusted click.
window.addEventListener('click', async (event) => {
  if (!event.isTrusted || event.button !== 0 || event.defaultPrevented) return;
  if (event.target.matches?.('a.merchant-checkout-link')) {
    const link = event.target;
    const dialog = link.closest('dialog[open][data-payment-order]');
    if (!dialog || !link.isConnected || !link.getClientRects().length) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    try {
      if (await ipcRenderer.invoke('payments:open-checkout', dialog.dataset.paymentOrder)) return;
    } catch { /* The institution window or the payment application may have been closed. */ }
    const message = dialog.querySelector('[role="status"]');
    if (message) message.textContent = '暂时无法打开支付应用，请核对订单状态或直接扫码。';
    return;
  }
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
  let link = event.target.closest?.('#assistant-chat:not([hidden]) a.assistant-source-link');
  let inMedicalRecord = false;
  if (!link) {
    link = event.target.closest?.('dialog[open] a.hospital-map-link');
    if (link && !hospitalMap(link.href)) return;
    inMedicalRecord = Boolean(link);
  }
  if (!link) {
    link = event.target.closest?.('.medication-source-scope a.medication-source-link');
    if (!link) return;
    if (!medicineReference(link.href)) return;
    inMedicalRecord = true;
  }
  if (!link || !link.isConnected || !link.getClientRects().length || link.origin === location.origin) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  try {
    if (await ipcRenderer.invoke('assistant:open-public-source', link.href)) return;
  } catch { /* The institution window may have been closed during the lookup. */ }
  const status = inMedicalRecord ? link.parentElement : link.closest('li');
  if (status?.isConnected && !status.querySelector('[role="status"]')) {
    const hint = document.createElement('small');
    hint.setAttribute('role', 'status');
    hint.textContent = '暂时无法打开此公开来源。';
    status.append(hint);
  }
}, true);
