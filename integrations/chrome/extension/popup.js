const HOST_NAME = 'com.keenetic.router.host';
const DEFAULT_TUNNEL = 'wg1';

let activeTab = null;
let domain = null;

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
    : 'Добавить через VPN';
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

  if (!domain) {
    renderStatus('Открой обычную страницу http или https', 'bad');
    return;
  }

  try {
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
      tunnel: DEFAULT_TUNNEL,
      domains: [domain],
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
load().catch((error) => renderStatus(error.message || String(error), 'bad'));
