import test from 'node:test';
import assert from 'node:assert/strict';

import {
  hostnameFromRequestUrl,
  httpFailure,
  networkFailure,
} from '../integrations/chrome/extension/failure-policy.js';

test('404 is never offered as a VPN routing problem', () => {
  assert.equal(httpFailure({ url: 'https://cdn.example.com/missing.png', statusCode: 404, type: 'image' }), null);
});

test('access blocks are attributed to the resource hostname', () => {
  assert.deepEqual(
    httpFailure({ url: 'https://media.example.com/picture.webp', statusCode: 403, type: 'image' }),
    { domain: 'media.example.com', reason: 'HTTP 403', statusCode: 403, resourceType: 'image' },
  );
  assert.equal(httpFailure({ url: 'https://example.com/', statusCode: 451, type: 'main_frame' }).reason, 'HTTP 451');
  assert.equal(httpFailure({ url: 'https://metrics.example.com/', statusCode: 403, type: 'ping' }), null);
});

test('DNS and connection failures are offered, noisy browser failures are not', () => {
  assert.equal(networkFailure({ url: 'https://api.example.com/', error: 'net::ERR_NAME_NOT_RESOLVED', type: 'xmlhttprequest' }).reason, 'Ошибка DNS');
  assert.equal(networkFailure({ url: 'https://cdn.example.com/', error: 'net::ERR_CONNECTION_TIMED_OUT', type: 'image' }).reason, 'Тайм-аут');
  assert.equal(networkFailure({ url: 'https://ads.example.com/', error: 'net::ERR_BLOCKED_BY_CLIENT', type: 'script' }), null);
  assert.equal(networkFailure({ url: 'https://example.com/', error: 'net::ERR_ABORTED', type: 'main_frame' }), null);
  assert.equal(networkFailure({ url: 'https://example.com/', error: 'net::ERR_CERT_DATE_INVALID', type: 'main_frame' }), null);
});

test('only public web hostnames are accepted', () => {
  assert.equal(hostnameFromRequestUrl('https://CDN.Example.COM/image.png'), 'cdn.example.com');
  assert.equal(hostnameFromRequestUrl('http://localhost:8080/'), null);
  assert.equal(hostnameFromRequestUrl('http://192.168.1.1/'), null);
  assert.equal(hostnameFromRequestUrl('chrome://extensions'), null);
});
