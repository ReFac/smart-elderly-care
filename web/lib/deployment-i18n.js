// Loaded only for international deployments. The catalogue contains shipped interface
// messages. Clinical text, uploads, field values and chat are never sent to a translator.
(() => {
  const deployment = window.NH_DEPLOYMENT;
  if (!deployment || deployment.edition === 'china' || deployment.language === 'zh-CN') return;
  const han = /[\u3400-\u9fff]/u;
  const skip = 'script,style,textarea,code,pre,[translate="no"],[contenteditable="true"],.resident-profile-link,.assistant-message-text,.medical-visit-text > p,.medical-visit-evidence li,.medical-visit-originals img';
  const attributes = ['aria-label', 'aria-description', 'aria-valuetext', 'placeholder', 'title', 'alt', 'data-label'];
  const workspaceChrome = '.sidebar,.desk-tabbar,.desk-view-switcher,.desk-home-actions,.site-nav,.site-footer,th,dt';
  const personal = /^(?:name|fullName|displayName|realName|username|institutionName|brandName|subject|title|note|notes|remark|remarks|message|description|summary|address|diagnosis|allergies|medicationName|original|originalText|filename|fileName|signature|question|answer|instructions|findings|history|feedback|conclusion|content|comment|opinion)$/i;
  const displayed = new WeakMap();
  const displayedAttributes = new WeakMap();
  const freeDataColumn = /姓名|经办人|执行人|负责人|操作人|摘要|备注|过敏|病史|病情|描述|原文|反馈|签名|结果|药品名称|项目名称|长辈信息|联系人|住址|地址/;
  let lexicon = Object.create(null);
  const overlayLabels = new Set();
  let loaded = false;
  let privateValues = new Set();
  let pendingState;

  function setWorkspace(state) {
    privateValues.clear();
    pendingState = state;
    if (!state || !loaded) return;
    // Keep only collisions with known UI text, for the lifetime of this scope.
    // Most names, notes and other data cannot occur in the exact-match catalogue.
    const visit = (value, key) => {
      if (typeof value === 'string') {
        if (personal.test(key) && Object.hasOwn(lexicon, value.trim())) privateValues.add(value.trim());
      } else if (value && typeof value === 'object') {
        if (Array.isArray(value)) value.forEach(item => visit(item, key));
        else for (const [child, item] of Object.entries(value)) visit(item, child);
      }
    };
    visit(state, '');
    pendingState = undefined;
  }

  const fixed = s => Object.hasOwn(lexicon, s) ? lexicon[s] : s;
  const navActions = {
    取消固定:'Unpin ', 固定:'Pin ', 关闭:'Close ', 已固定:'Pinned: ', 打开:'Open ',
    已取消固定:'Unpinned: ', 已打开:'Opened: ', 查看:'View ',
  };
  function message(source) {
    if (typeof source !== 'string' || (!han.test(source) && !overlayLabels.has(source.trim()))) return source;
    const s = source.trim();
    if (!s) return source;
    let t = fixed(s);
    if (t === s) {
      let m;
      if ((m = /^共\s*(\d+)\s*条$/.exec(s))) t = m[1] + (m[1] === '1' ? ' record' : ' records');
      else if ((m = /^(\d+)\s*条(?:\s*\/\s*页)?$/.exec(s))) t = m[1] + (s.includes('/') ? ' per page' : ' records');
      else if ((m = /^共\s*(\d+)\s*页$/.exec(s))) t = m[1] + ' pages';
      else if ((m = /^第\s*(\d+)\s*页\s*\/\s*共\s*(\d+)\s*页$/.exec(s))) t = 'Page ' + m[1] + ' of ' + m[2];
      else if ((m = /^证件\s*(\d+)\s*\/\s*(\d+)$/.exec(s))) t = 'Documents ' + m[1] + ' / ' + m[2];
      else if ((m = /^(\d+)\s*次就诊\s*·\s*(\d+)\s*份原件$/.exec(s))) t = m[1] + ' visits · ' + m[2] + ' originals';
      else if ((m = /^缺少\s*([\d,\-、\s]+)$/.exec(s))) t = 'Missing: ' + m[1];
      else if ((m = /^(在住档案|已退住|全部档案)\s*(\d+)$/.exec(s))) t = fixed(m[1]) + ' ' + m[2];
      else if ((m = /^(\d+)\s*(项提醒|张账单|个待出账期|个账户|笔本月到账|笔核销|个支付订单|笔支出|张待缴账单)$/.exec(s))) t = m[1] + ' ' + fixed(m[2]);
      else if ((m = /^(.+?)\s+([↓↑])$/.exec(s)) && fixed(m[1]) !== m[1]) t = fixed(m[1]) + ' ' + m[2];
      else if ((m = /^登记床位共\s*(\d+)\s*床$/.exec(s))) t = m[1] + ' registered beds';
      else if ((m = /^本月新入住\s*(\d+)\s*人$/.exec(s))) t = m[1] + ' admitted this month';
      else if ((m = /^已完成\s*(\d+)\s*单$/.exec(s))) t = m[1] + ' completed';
      else if ((m = /^本月流水\s*([¥￥\d,.\sA-Z]+)$/.exec(s))) t = 'This month: ' + m[1];
      else if ((m = /^每月\s*(\d+)\s*日(?:（(.+)）)?$/.exec(s))) t = 'Day ' + m[1] + (m[2] ? ' (' + fixed(m[2]) + ')' : '');
      else if ((m = /^(\d+(?:\.\d+)?)[ \t]*(人|笔|床|个|项|天|元|次|岁|分钟|秒)$/.exec(s)) && fixed(m[2]) !== m[2]) t = m[1] + ' ' + fixed(m[2]);
      else if ((m = /^(取消固定|已取消固定|已固定|固定|关闭|已打开|打开|查看)\s*(.+)$/.exec(s)) && fixed(m[2]) !== m[2]) t = navActions[m[1]] + fixed(m[2]);
      else if (s.startsWith('/ ') && fixed(s.slice(2)) !== s.slice(2)) t = '/ ' + fixed(s.slice(2));
    }
    return t === s ? source : source.slice(0, source.indexOf(s)) + t + source.slice(source.indexOf(s) + s.length);
  }
  let ready = false;
  window.NH_I18N = { text: message, setWorkspace, get ready() { return ready; } };

  function renderText(node) {
    const owner = node.parentElement;
    if (!owner || displayed.get(node) === node.data || (!han.test(node.data) && !overlayLabels.has(node.data.trim())) || owner.closest(skip)) return;
    const s = node.data.trim();
    if (owner.tagName === 'TITLE') {
      const parts = s.split(' · ');
      // The suffix may be the institution's own name.
      if (parts.length > 1 && fixed(parts[0]) !== parts[0] && fixed(s) === s) {
        node.data = [fixed(parts[0]), ...parts.slice(1)].join(' · '); return;
      }
    }
    const control = owner.closest('button,.badge,[role="tab"],label,option');
    const cell = owner.closest('td');
    if (cell && freeDataColumn.test(cell.dataset.label || '') && !control) return;
    if (privateValues.has(s) && !owner.closest(workspaceChrome) && !owner.closest('.badge,[role="tab"],label > span:first-child')) return;
    const translated = message(node.data);
    if (translated === node.data) return;
    // HTML uses the displayed text as an option's default value when no
    // explicit value exists. Keep the original value for commands and form data.
    if (owner.tagName === 'OPTION' && !owner.hasAttribute('value')) owner.value = owner.value;
    displayed.set(node, translated);
    node.data = translated;
  }
  function renderAttribute(element, name) {
    if (element.closest(skip)) return;
    const old = element.getAttribute(name);
    const next = message(old);
    if (name === 'data-label') {
      if (next) element.dataset.displayLabel = next;
      return;
    }
    if (next && next !== old && !privateValues.has(old)) {
      const changed = displayedAttributes.get(element) || {};
      if (changed[name] === old) return;
      changed[name] = next;
      displayedAttributes.set(element,changed);
      element.setAttribute(name,next);
    }
  }
  function renderTree(root) {
    if (root.nodeType === Node.TEXT_NODE) { renderText(root); return; }
    if (root.nodeType !== Node.ELEMENT_NODE || root.closest(skip)) return;
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        return node.nodeType === Node.ELEMENT_NODE && node.matches(skip) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
      }
    });
    let node = root;
    do {
      if (node.nodeType === Node.TEXT_NODE) renderText(node);
      else for (const name of attributes) if (node.hasAttribute(name)) renderAttribute(node, name);
    } while ((node = walk.nextNode()));
  }

  async function localeMessages() {
    const {default: english} = await import('/assets/workspace-en.js');
    if (!deployment.messagesOverlay) return english;
    // Overlay files use Chinese source strings as stable keys. Ignore invalid
    // entries and keep English for missing terms or an unavailable locale pack.
    try {
      const url = new URL(deployment.messagesOverlay, location.href);
      if (url.origin !== location.origin) return english;
      const response = await fetch(url, {credentials:'same-origin',redirect:'error'});
      if (!response.ok) return english;
      const overlay = await response.json();
      const messages = {...english};
      for (const [key, text] of Object.entries(overlay)) {
        if (typeof text !== 'string' || !text.trim() || ['__proto__','constructor','prototype'].includes(key)) continue;
        messages[key] = text;
        overlayLabels.add(key);
      }
      return messages;
    } catch { return english; }
  }
  localeMessages().then(messages => {
    lexicon = messages;
    loaded = true;
    if (pendingState) setWorkspace(pendingState);
    renderTree(document.documentElement);
    const observer = new MutationObserver(records => {
      const added = new Set();
      for (const record of records) {
        if (record.type === 'childList') for (const node of record.addedNodes) added.add(node);
        else if (record.type === 'attributes') renderAttribute(record.target, record.attributeName);
        else if (record.type === 'characterData') renderText(record.target);
      }
      for (const node of added) if (node.isConnected && !added.has(node.parentNode)) renderTree(node);
    });
    observer.observe(document.documentElement, {subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:attributes});
    ready = true;
    window.dispatchEvent(new Event('nh-interface-language-ready'));
  }).catch(() => { /* The original controls remain usable if an asset is unavailable. */ });
})();
