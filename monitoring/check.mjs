import { pathToFileURL } from 'node:url';
import { writeFile } from 'node:fs/promises';

export const pages = ['/', '/zh', '/pricing', '/zh/pricing'];
const web = 'https://edgespeak.com';
const catalogUrl = 'https://api.edgespeak.com/api/billing/catalog';
const statePath = 'monitoring/status.json';

function catalogAllowances(catalog) {
  const p = catalog?.plans;
  const values = [p?.free?.periodTokens, p?.subscription?.basic?.periodTokens,
    p?.subscription?.pro?.periodTokens, p?.buyout?.periodTokens];
  if (catalog?.currency !== 'usd' || values.some(v => !Number.isSafeInteger(v) || v <= 0)) {
    throw new Error('Billing catalog has an invalid currency or allowance');
  }
  return values;
}

export function validatePricing(html, catalog) {
  const amounts = [...html.matchAll(/class="plan-allowance-tokens">([\d,.]+)([KM]?) tokens per month<\/span>/g)]
    .map(([, value, suffix]) => Number(value.replaceAll(',', '')) * ({ K: 1000, M: 1000000 }[suffix] ?? 1));
  const expected = catalogAllowances(catalog);
  if (amounts.length !== expected.length || amounts.some((v, i) => v !== expected[i])) {
    throw new Error('Rendered pricing allowances differ from the live billing catalog');
  }
}

export async function checkOnce(fetcher = fetch) {
  const results = await Promise.all([...pages.map(p => web + p), catalogUrl].map(async url => {
    try {
      const response = await fetcher(url, { signal: AbortSignal.timeout(15000), cache: 'no-store',
        headers: { 'User-Agent': 'EdgeSpeak-Availability-Monitor/1.0', 'Cache-Control': 'no-cache' } });
      if (response.status !== 200) throw new Error(`HTTP ${response.status}`);
      const body = await response.text();
      if (url !== catalogUrl && (!/<html[\s>]/i.test(body) || !body.includes('EdgeSpeak') || body.includes('Internal Server Error'))) {
        throw new Error('Expected EdgeSpeak HTML content is missing or an error page was returned');
      }
      return { url, body };
    } catch (error) {
      // Never publish response bodies, cookies, request headers, or credentials.
      return { url, error: error.name === 'TimeoutError' ? 'Request timed out' : error.message };
    }
  }));
  const failures = results.filter(r => r.error).map(({ url, error }) => ({ url, error }));
  const pricing = results.find(r => r.url === web + '/pricing');
  const catalog = results.find(r => r.url === catalogUrl);
  if (!catalog.error) {
    try {
      const parsed = JSON.parse(catalog.body);
      catalogAllowances(parsed);
      if (!pricing.error) validatePricing(pricing.body, parsed);
    }
    catch (error) { failures.push({ url: catalogUrl, error: error instanceof SyntaxError ? 'Invalid catalog JSON' : error.message }); }
  }
  return failures;
}

export async function checkWithRetry(check = checkOnce, sleep = ms => new Promise(r => setTimeout(r, ms))) {
  let failures = await check();
  if (failures.length) { await sleep(15000); failures = await check(); }
  return failures;
}

export function nextState(previous, failures, now, runUrl) {
  const status = failures.length ? 'down' : 'up';
  // State changes only: do not create a commit or repeat an email every five minutes.
  if (previous?.status === status) return previous;
  return { status, changed_at: now, checked_urls: [...pages.map(p => web + p), catalogUrl], failures, run_url: runUrl };
}

async function githubState(method = 'GET', body) {
  const response = await fetch(`https://api.github.com/repos/${process.env.GITHUB_REPOSITORY}/contents/${statePath}`, {
    method, headers: { Authorization: `Bearer ${process.env.GITHUB_TOKEN}`, Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) throw new Error(`GitHub state ${method} failed: HTTP ${response.status}`);
  return response.json();
}

async function main() {
  const publish = process.argv.includes('--publish');
  if (publish && (!process.env.GITHUB_TOKEN || process.env.GITHUB_REPOSITORY !== 'lattifai/EdgeSpeak')) {
    throw new Error('Publishing requires the repository-scoped Actions token for lattifai/EdgeSpeak');
  }
  const failures = await checkWithRetry();
  console.log(JSON.stringify({ status: failures.length ? 'down' : 'up', failures }, null, 2));
  if (publish) {
    const current = await githubState();
    const previous = JSON.parse(Buffer.from(current.content, 'base64').toString());
    const next = nextState(previous, failures, new Date().toISOString(),
      `https://github.com/${process.env.GITHUB_REPOSITORY}/actions/runs/${process.env.GITHUB_RUN_ID}`);
    if (next !== previous) {
      await githubState('PUT', { message: `chore: website availability ${next.status}`, sha: current.sha,
        content: Buffer.from(JSON.stringify(next, null, 2) + '\n').toString('base64'), branch: 'main' });
      console.log(`Published availability transition: ${previous.status} -> ${next.status}`);
    }
  } else if (process.argv.includes('--initialize')) {
    const state = nextState(null, failures, new Date().toISOString(), null);
    await writeFile(statePath, JSON.stringify(state, null, 2) + '\n');
  }
  if (process.env.GITHUB_STEP_SUMMARY) {
    await writeFile(process.env.GITHUB_STEP_SUMMARY,
      `## Website availability: ${failures.length ? 'DOWN' : 'UP'}\n\n` +
      (failures.length ? failures.map(f => `- ${f.url}: ${f.error}`).join('\n') : 'All four pages and the live billing catalog passed.'));
  }
  if (failures.length) process.exitCode = 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(error => { console.error(error.message); process.exitCode = 1; });
}
