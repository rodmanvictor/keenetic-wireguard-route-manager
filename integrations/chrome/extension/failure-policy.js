/**
 * Decide which failed requests are useful for VPN routing.
 *
 * The filter is deliberately conservative: adding a domain to WireGuard cannot
 * repair a missing page (404), an ad blocker decision or a broken certificate.
 * Keeping this policy in a pure module also lets Node test it without Chrome.
 */

const ROUTING_HTTP_STATUSES = new Set([
  403,
  451,
  502,
  503,
  504,
  520,
  521,
  522,
  523,
  524,
  525,
]);

const PAGE_RESOURCE_TYPES = new Set([
  'main_frame',
  'sub_frame',
  'stylesheet',
  'script',
  'image',
  'font',
  'xmlhttprequest',
  'media',
]);

const IGNORED_NETWORK_ERRORS = [
  'ERR_ABORTED',
  'ERR_BLOCKED_BY_CLIENT',
  'ERR_BLOCKED_BY_RESPONSE',
  'ERR_BLOCKED_BY_CSP',
  'ERR_BLOCKED_BY_ORB',
  'ERR_CERT_',
  'ERR_SSL_',
];

const ROUTING_NETWORK_ERRORS = [
  'ERR_NAME_NOT_RESOLVED',
  'ERR_DNS_',
  'ERR_CONNECTION_',
  'ERR_ADDRESS_',
  'ERR_NETWORK_',
  'ERR_INTERNET_',
  'ERR_PROXY_',
  'ERR_TUNNEL_',
  'ERR_TIMED_OUT',
  'ERR_EMPTY_RESPONSE',
  'ERR_QUIC_',
  'ERR_HTTP2_',
  'ERR_HTTP3_',
];

/** Return a routable hostname, or null for local/IP/non-web addresses. */
export function hostnameFromRequestUrl(value) {
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol)) return null;
    const host = url.hostname.toLowerCase().replace(/\.$/, '');
    if (!host || host === 'localhost' || host.endsWith('.local')) return null;
    if (host.includes(':') || /^\d{1,3}(?:\.\d{1,3}){3}$/.test(host)) return null;
    if (!host.includes('.')) return null;
    return host;
  } catch {
    return null;
  }
}

/** Return structured data for an HTTP response worth routing, or null. */
export function httpFailure(details) {
  const statusCode = Number(details?.statusCode || 0);
  if (!ROUTING_HTTP_STATUSES.has(statusCode)) return null;
  if (!PAGE_RESOURCE_TYPES.has(details?.type || 'other')) return null;
  const domain = hostnameFromRequestUrl(details?.url || '');
  if (!domain) return null;
  return {
    domain,
    reason: `HTTP ${statusCode}`,
    statusCode,
    resourceType: details?.type || 'other',
  };
}

/** Return structured data for a network failure worth routing, or null. */
export function networkFailure(details) {
  const error = String(details?.error || '').toUpperCase();
  if (!error || IGNORED_NETWORK_ERRORS.some((fragment) => error.includes(fragment))) return null;
  if (!ROUTING_NETWORK_ERRORS.some((fragment) => error.includes(fragment))) return null;
  if (!PAGE_RESOURCE_TYPES.has(details?.type || 'other')) return null;
  const domain = hostnameFromRequestUrl(details?.url || '');
  if (!domain) return null;
  return {
    domain,
    reason: readableNetworkError(error),
    error,
    resourceType: details?.type || 'other',
  };
}

/** Translate Chromium's technical error into a compact Russian label. */
export function readableNetworkError(error) {
  if (error.includes('NAME_NOT_RESOLVED') || error.includes('DNS_')) return 'Ошибка DNS';
  if (error.includes('TIMED_OUT')) return 'Тайм-аут';
  if (error.includes('PROXY_') || error.includes('TUNNEL_')) return 'Ошибка VPN';
  if (error.includes('ADDRESS_')) return 'Адрес недоступен';
  if (error.includes('CONNECTION_')) return 'Нет соединения';
  if (error.includes('EMPTY_RESPONSE')) return 'Пустой ответ';
  return 'Ошибка сети';
}
