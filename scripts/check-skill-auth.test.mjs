import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import test from "node:test";

const root = fileURLToPath(new URL("../", import.meta.url));
const skillNames = (await readdir(join(root, "skills"), { withFileTypes: true }))
  .filter((entry) => entry.isDirectory())
  .map((entry) => entry.name);
const paths = [
  "README.md",
  "README.zh-CN.md",
  "skills/README.md",
  "skills/README.zh-CN.md",
  "directory-listing/README.md",
  "directory-listing/README.zh-CN.md",
  "directory-listing/plugin.json",
  ...skillNames.map((name) => `skills/${name}/SKILL.md`),
];

function retiredActivationClaims(source) {
  return [
    /edgespeak-cli\s+trial(?:\b|-device)/i,
    /\b(?:7[- ]day|seven[- ]day)\s+(?:free\s+)?trial/i,
    /(?:7\s*天|七天)[^\n。]{0,20}试用/,
  ].some((pattern) => pattern.test(source));
}

test("public instructions do not route users to retired trial activation", async () => {
  for (const path of paths) {
    const source = await readFile(join(root, path), "utf8");
    assert.equal(retiredActivationClaims(source), false, path);
  }
});

test("activation catalogs explain account approval without a purchase prerequisite", async () => {
  const en = await readFile(join(root, "skills/README.md"), "utf8");
  const zh = await readFile(join(root, "skills/README.zh-CN.md"), "utf8");
  for (const source of [en, zh]) {
    assert.match(source, /edgespeak-cli login --no-browser/);
    assert.match(source, /Free/);
    assert.match(source, /410/);
  }
  assert.match(en, /Free does not require a purchase/);
  assert.match(en, /approve this device/);
  assert.match(en, /different Key is rejected/);
  assert.match(zh, /Free 无需先购买/);
  assert.match(zh, /官网并批准本机/);
  assert.match(zh, /不同 Key 会被拒绝/);
});

test("activation guidance in task skills preserves buyout rights", async () => {
  for (const name of ["transcribe", "align", "segment", "broadcast", "video-voice"]) {
    const path = `skills/edgespeak-${name}/SKILL.md`;
    const source = await readFile(join(root, path), "utf8");
    assert.match(source, /edgespeak-cli login/, path);
    assert.match(source, /Free/, path);
    assert.match(source, /subscription/, path);
    assert.match(source, /approve this device/, path);
    assert.match(source, /different Key is rejected/, path);
  }
});

test("claim guard catches deleted English and Chinese onboarding text", () => {
  for (const source of [
    "edgespeak-cli trial",
    "edgespeak-cli trial-device",
    "new accounts start a free 7-day trial automatically",
    "new devices get a 7-day trial",
    "新设备有 7 天试用",
    "新账号自动获得 7 天免费试用",
    "立即开通匿名七天试用",
  ]) {
    assert.equal(retiredActivationClaims(source), true, source);
  }
  assert.equal(retiredActivationClaims("Old credentials can still report a trial; sign in to sync the real account."), false);
});
