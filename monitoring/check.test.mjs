import test from 'node:test';
import assert from 'node:assert/strict';
import { checkOnce, checkWithRetry, validatePricing, nextState } from './check.mjs';
const catalog = { currency: 'usd', plans: { free: {periodTokens:40000}, subscription: { basic:{periodTokens:2000000}, pro:{periodTokens:10000000} }, buyout:{periodTokens:20000000} } };
const html = '<html>EdgeSpeak ' + ['40K','2M','10M','20M'].map(v => `<span class="plan-allowance-tokens">${v} tokens per month</span>`).join('') + '</html>';
const fetcher = async url => new Response(url.endsWith('/catalog') ? JSON.stringify(catalog) : html);
test('healthy pages and matching live allowances pass', async () => assert.deepEqual(await checkOnce(fetcher), []));
test('HTTP 500 is caught even with a healthy catalog', async () => {
  const failures = await checkOnce(url => url.endsWith('/zh') ? new Response('Internal Server Error',{status:500}) : fetcher(url));
  assert.equal(failures.length, 1); assert.equal(failures[0].error, 'HTTP 500');
});
test('HTTP 200 error page is not healthy', async () => {
  assert.equal((await checkOnce(async () => new Response('Internal Server Error'))).length, 5);
});
test('old frontend quota with new backend reproduces the outage', () => assert.throws(() => validatePricing(html.replace('2M','1M'), catalog), /differ/));
test('malformed catalog cannot silently pass', () => assert.throws(() => validatePricing(html, {}), /invalid/));
test('transient failure retries once and recovers', async () => {
  let calls = 0; let waits = 0;
  assert.deepEqual(await checkWithRetry(async () => ++calls === 1 ? ['timeout'] : [], async () => waits++), []);
  assert.equal(calls, 2); assert.equal(waits, 1);
});
test('confirmed failure remains down', async () => assert.deepEqual(await checkWithRetry(async () => ['500'], async () => {}), ['500']));
test('persistent failure does not republish; recovery does', () => {
  const down = nextState({status:'up'}, [{error:'500'}], 'first', 'run');
  assert.equal(down.status, 'down'); assert.equal(nextState(down, [{error:'timeout'}], 'second', 'run2'), down);
  const up = nextState(down, [], 'third', 'run3'); assert.equal(up.status, 'up'); assert.equal(up.changed_at, 'third');
  assert.equal(nextState(up, [], 'fourth', 'run4'), up);
});
