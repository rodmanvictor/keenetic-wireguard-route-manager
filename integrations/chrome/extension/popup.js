const HOST_NAME = 'com.keenetic.router.host';

let activeTab = null;
let domain = null;
let relatedFailures = [];

function hostnameFromUrl(value) {
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol)) return null;
    const host = url.hostname.toLowerCase().replace(/\.$/, '');
    if (!host || ['localhost', '127.0.0.1', '::1'].includes(host)) return null;
    return host;
  } catch {
    return null;
  }
}

async function sendNative(message) {
  return chrome.runtime.sendNativeMessage(HOST_NAME, message);
}

function renderStatus(text, tone = 'neutral') {
  const status = document.getElementById('status');
  status.className = `status ${tone}`;
  document.getElementById('status-text').textContent = text;
  const dot = document.getElementById('connection-dot');
  dot.className = `connection-dot ${tone === 'bad' ? 'error' : tone === 'good' ? 'ok' : 'pending'}`;
}

function setBusy(busy) {
  const button = document.getElementById('add');
  button.disabled = busy || !domain;
  document.getElementById('button-label').textContent = busy
    ? 'Добавляю маршруты…'
    : buttonLabel();
}

function selectedDomains() {
  const selected = [...document.querySelectorAll('.related-row input:checked')]
    .map((input) => input.dataset.domain)
    .filter(Boolean);
  return [...new Set([domain, ...selected].filter(Boolean))];
}

function buttonLabel() {
  const count = selectedDomains().length;
  return count > 1 ? `Добавить через VPN · ${count}` : 'Добавить сайт через VPN';
}

function renderFavicon() {
  const image = document.getElementById('favicon-image');
  const fallback = document.getElementById('favicon-fallback');
  if (!activeTab?.favIconUrl) return;
  image.addEventListener('load', () => {
    image.hidden = false;
    fallback.hidden = true;
  }, { once: true });
  image.addEventListener('error', () => {
    image.hidden = true;
    fallback.hidden = false;
  }, { once: true });
  image.src = activeTab.favIconUrl;
}

function resourceLabel(resourceTypes = [], count = 1) {
  const labels = {
    image: 'картинка', script: 'скрипт', stylesheet: 'стили',
    xmlhttprequest: 'API', media: 'медиа', font: 'шрифт',
    sub_frame: 'встроенная страница', main_frame: 'страница',
  };
  const kinds = resourceTypes.map((type) => labels[type] || 'ресурс');
  return `${[...new Set(kinds)].slice(0, 2).join(', ')}${count > 1 ? ` · ${count} ошибок` : ''}`;
}

function renderRelated(failures) {
  relatedFailures = failures.filter((item) => item?.domain && item.domain !== domain);
  const section = document.getElementById('related');
  const empty = document.getElementById('no-failures');
  const list = document.getElementById('related-list');
  list.replaceChildren();
  section.hidden = relatedFailures.length === 0;
  empty.hidden = relatedFailures.length !== 0;
  document.getElementById('related-count').textContent = String(relatedFailures.length);

  for (const failure of relatedFailures) {
    const row = document.createElement('label');
    row.className = 'related-row';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = true;
    checkbox.dataset.domain = failure.domain;
    checkbox.addEventListener('change', syncSelection);
    const copy = document.createElement('span');
    copy.className = 'related-copy';
    const host = document.createElement('strong');
    host.className = 'related-domain';
    host.textContent = failure.domain;
    const meta = document.createElement('small');
    meta.className = 'related-meta';
    meta.textContent = resourceLabel(failure.resourceTypes, failure.count);
    copy.append(host, meta);
    const reason = document.createElement('span');
    reason.className = 'reason';
    reason.textContent = failure.reason;
    row.append(checkbox, copy, reason);
    list.append(row);
  }
  syncSelection();
}

function syncSelection() {
  const checkboxes = [...document.querySelectorAll('.related-row input')];
  const selected = checkboxes.filter((input) => input.checked).length;
  const selectAll = document.getElementById('select-all');
  selectAll.checked = checkboxes.length > 0 && selected === checkboxes.length;
  selectAll.indeterminate = selected > 0 && selected < checkboxes.length;
  document.getElementById('button-label').textContent = buttonLabel();
}

function showDetails(response) {
  document.getElementById('details').hidden = false;
  document.getElementById('ip-count').textContent = String(response.ips?.length || response.summary?.ips_total || 0);
}

async function load() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  activeTab = tabs[0] || null;
  domain = hostnameFromUrl(activeTab?.url || '');
  document.getElementById('domain').textContent = domain || 'Эту вкладку добавить нельзя';
  renderFavicon();

  if (!domain) {
    renderStatus('Открой обычную страницу http или https', 'bad');
    return;
  }

  try {
    const failuresResponse = await chrome.runtime.sendMessage({
      action: 'get_tab_failures',
      tabId: activeTab.id,
    });
    renderRelated(failuresResponse?.ok ? failuresResponse.failures || [] : []);

    const response = await sendNative({ action: 'get_domain_status', domain });
    if (!response?.ok) throw new Error(response?.error || 'Native host недоступен');
    if (response.tracked) {
      const fromChrome = (response.sources || []).includes('chrome');
      renderStatus(fromChrome ? 'Уже добавлен через Chrome' : 'Уже есть в постоянном списке', 'good');
      showDetails(response);
    } else {
      renderStatus('Готов добавить текущий домен', 'neutral');
    }
    setBusy(false);
  } catch (error) {
    renderStatus(error.message || String(error), 'bad');
  }
}

async function addCurrentSite() {
  if (!domain) return;
  setBusy(true);
  renderStatus('Связываюсь с Keenetic по SSH', 'neutral');
  try {
    const response = await sendNative({
      action: 'add_routes_for_domains',
      domains: selectedDomains(),
    });
    if (!response?.ok) throw new Error(response?.error || 'Не удалось добавить сайт');
    renderStatus('Готово. Перезагружаю страницу', 'good');
    showDetails(response);
    window.setTimeout(() => chrome.tabs.reload(activeTab.id), 450);
  } catch (error) {
    renderStatus(error.message || String(error), 'bad');
    setBusy(false);
  }
}

document.getElementById('add').addEventListener('click', addCurrentSite);
document.getElementById('select-all').addEventListener('change', (event) => {
  document.querySelectorAll('.related-row input').forEach((input) => {
    input.checked = event.currentTarget.checked;
  });
  syncSelection();
});
load().catch((error) => renderStatus(error.message || String(error), 'bad'));
