import { httpFailure, networkFailure } from './failure-policy.js';

const STORAGE_PREFIX = 'failed-resources:';
const MAX_DOMAINS_PER_TAB = 40;
const writeQueues = new Map();

function storageKey(tabId) {
  return `${STORAGE_PREFIX}${tabId}`;
}

/** Serialize writes per tab so simultaneous failed resources cannot overwrite each other. */
function enqueueTabWrite(tabId, operation) {
  const previous = writeQueues.get(tabId) || Promise.resolve();
  const next = previous.catch(() => undefined).then(operation);
  writeQueues.set(tabId, next);
  void next.then(() => {
    if (writeQueues.get(tabId) === next) writeQueues.delete(tabId);
  }, () => {
    if (writeQueues.get(tabId) === next) writeQueues.delete(tabId);
  });
  return next;
}

async function readFailures(tabId) {
  const key = storageKey(tabId);
  const stored = await chrome.storage.session.get(key);
  return Array.isArray(stored[key]) ? stored[key] : [];
}

async function updateBadge(tabId, count) {
  await chrome.action.setBadgeBackgroundColor({ tabId, color: '#b8f34a' });
  await chrome.action.setBadgeTextColor?.({ tabId, color: '#10140d' });
  await chrome.action.setBadgeText({ tabId, text: count ? String(count) : '' });
}

async function rememberFailure(tabId, failure) {
  if (tabId < 0 || !failure) return;
  await enqueueTabWrite(tabId, async () => {
    const existing = await readFailures(tabId);
    const now = Date.now();
    const current = existing.find((item) => item.domain === failure.domain);
    let failures;
    if (current) {
      failures = existing.map((item) => item.domain === failure.domain ? {
        ...item,
        reason: failure.reason,
        statusCode: failure.statusCode || item.statusCode || null,
        error: failure.error || item.error || null,
        resourceTypes: [...new Set([...(item.resourceTypes || []), failure.resourceType])],
        count: (item.count || 1) + 1,
        lastSeen: now,
      } : item);
    } else {
      failures = [...existing, {
        domain: failure.domain,
        reason: failure.reason,
        statusCode: failure.statusCode || null,
        error: failure.error || null,
        resourceTypes: [failure.resourceType],
        count: 1,
        lastSeen: now,
      }].slice(-MAX_DOMAINS_PER_TAB);
    }
    await chrome.storage.session.set({ [storageKey(tabId)]: failures });
    await updateBadge(tabId, failures.length);
  });
}

async function clearFailures(tabId) {
  if (tabId < 0) return;
  await enqueueTabWrite(tabId, async () => {
    await chrome.storage.session.remove(storageKey(tabId));
    await updateBadge(tabId, 0);
  });
}

chrome.webRequest.onBeforeRequest.addListener((details) => {
  if (details.type === 'main_frame') void clearFailures(details.tabId);
}, { urls: ['<all_urls>'], types: ['main_frame'] });

chrome.webRequest.onCompleted.addListener((details) => {
  void rememberFailure(details.tabId, httpFailure(details));
}, { urls: ['<all_urls>'] });

chrome.webRequest.onErrorOccurred.addListener((details) => {
  void rememberFailure(details.tabId, networkFailure(details));
}, { urls: ['<all_urls>'] });

chrome.tabs.onRemoved.addListener((tabId) => {
  void chrome.storage.session.remove(storageKey(tabId));
  writeQueues.delete(tabId);
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.action !== 'get_tab_failures') return false;
  readFailures(Number(message.tabId))
    .then((failures) => sendResponse({ ok: true, failures }))
    .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
  return true;
});
