// Run with: node --test "skills/edgespeak-translate/scripts/*.test.mjs"
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), "check-translation.mjs");

const SOURCE = {
  task: "transcribe",
  language: "English",
  segments: [
    { id: 0, start: 0, end: 4, text: "I think it is nextgen because these things go crazy." },
    { id: 1, start: 4, end: 8, text: "We tested it on the new harness last week, and it held up." },
  ],
};

// Comfortably inside the zh ceiling of 9 chars/s over a 4s cue.
const CLEAN = {
  target_lang: "zh",
  segments: [
    { ...SOURCE.segments[0], translation: "我觉得那就是下一代打法，因为这些东西就是会疯传。" },
    { ...SOURCE.segments[1], translation: "我们上周在新执行框架上测过了，扛住了。" },
  ],
};

function workspace(translated, source = SOURCE) {
  const dir = mkdtempSync(join(tmpdir(), "check-translation-test-"));
  const sourcePath = join(dir, "source.json");
  const translatedPath = join(dir, "translated.json");
  writeFileSync(sourcePath, JSON.stringify(source), "utf8");
  writeFileSync(translatedPath, JSON.stringify(translated), "utf8");
  return { dir, sourcePath, translatedPath };
}

function check(translated, { source, lang = "zh", args = [] } = {}) {
  const { dir, sourcePath, translatedPath } = workspace(translated, source);
  try {
    const run = spawnSync(
      process.execPath,
      [SCRIPT, "--translated", translatedPath, "--source", sourcePath, "--lang", lang, ...args],
      { encoding: "utf8" },
    );
    return { code: run.status, out: `${run.stdout}${run.stderr}` };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

function mutate(index, patch) {
  return {
    ...CLEAN,
    segments: CLEAN.segments.map((seg, i) => (i === index ? { ...seg, ...patch } : seg)),
  };
}

test("a sound translation exits clean", () => {
  const { code, out } = check(CLEAN);
  assert.equal(code, 0, `expected exit 0, got ${code}:\n${out}`);
});

test("an empty translation is a FAIL", () => {
  const { code, out } = check(mutate(1, { translation: "   " }));
  assert.equal(code, 2, out);
  assert.match(out, /translation\.empty/);
});

test("a dropped segment is a FAIL", () => {
  const { code, out } = check({ ...CLEAN, segments: [CLEAN.segments[0]] });
  assert.equal(code, 2, out);
  assert.match(out, /count\.mismatch/);
});

test("a moved timestamp is a FAIL", () => {
  const { code, out } = check(mutate(0, { start: 0.4 }));
  assert.equal(code, 2, out);
  assert.match(out, /invariant\.start/);
});

test("a rewritten source text is a FAIL", () => {
  const { code, out } = check(mutate(0, { text: "I think it is next gen." }));
  assert.equal(code, 2, out);
  assert.match(out, /invariant\.text/);
});

test("a target_lang that contradicts --lang is a FAIL", () => {
  const { code, out } = check({ ...CLEAN, target_lang: "ja" });
  assert.equal(code, 2, out);
  assert.match(out, /lang\.mismatch/);
});

// The rule the source skill found broken in 16% of real segments.
test("an em-dash the source never had is a WARN", () => {
  const { code, out } = check(mutate(0, { translation: "我觉得那就是下一代打法——这些东西就是会疯传。" }));
  assert.equal(code, 1, out);
  assert.match(out, /punct\.dash/);
});

test("a parenthetical gloss the source never had is a WARN", () => {
  const { code, out } = check(mutate(1, { translation: "我们上周在新执行框架（harness）上测过了。" }));
  assert.equal(code, 1, out);
  assert.match(out, /punct\.paren/);
});

test("two candidate translations side by side is a WARN", () => {
  const { code, out } = check(mutate(1, { translation: "我们上周在新执行框架 / 新测试架上测过了。" }));
  assert.equal(code, 1, out);
  assert.match(out, /term\.alternatives/);
});

test("overrunning the spoken character budget is a WARN", () => {
  const overlong = "我觉得那个东西就是下一代的打法，因为这些内容真的会疯狂传播开来，完全停不下来。";
  const { code, out } = check(mutate(0, { translation: overlong }));
  assert.equal(code, 1, out);
  assert.match(out, /pace\.too_long/);
});

// Real false positive: a 2.17s cue whose Chinese ran 12 characters plus the brand
// name "Claude". Counting those 6 letters and 2 spaces as 8 Chinese characters ate
// 40% of the budget and flagged a line that speaks well inside its slot.
test("a brand name inside CJK text does not eat the budget like CJK characters", () => {
  const text = "So we wanted to test what Claude could do";
  const source = { segments: [{ id: 0, start: 0, end: 2.17, text }] };
  const translated = {
    target_lang: "zh",
    segments: [{ id: 0, start: 0, end: 2.17, text, translation: "所以我们想测试 Claude 还能做什么" }],
  };
  const { code, out } = check(translated, { source });
  assert.equal(code, 0, `12 CJK chars + one short brand name fits a 19-char budget:\n${out}`);
});

// The Latin-script ceilings were calibrated on text that includes its spaces, so
// the CJK discount must not leak into them and silently triple every budget.
test("a Latin-script target still counts every character", () => {
  const text = "But when we asked it something that needed a great deal more careful reasoning, it could not do it at all.";
  const source = { segments: [{ id: 0, start: 0, end: 2, text }] };
  const translated = {
    target_lang: "fr",
    segments: [{
      id: 0,
      start: 0,
      end: 2,
      text,
      translation: "Mais lorsque nous lui avons demandé quelque chose qui exigeait beaucoup plus de raisonnement, il en était tout simplement incapable.",
    }],
  };
  const { code, out } = check(translated, { source, lang: "fr" });
  assert.equal(code, 1, `130 characters over a 2s cue must break the 70-char fr budget:\n${out}`);
  assert.match(out, /pace\.too_long/);
});

const OVERLONG = {
  target_lang: "zh",
  segments: [{
    id: 0,
    start: 0,
    end: 2,
    text: "But when we asked it something that needed more careful reasoning, it could not do it.",
    translation: "这是一句被刻意写得非常非常长的译文用来测试字符预算检查到底有没有真正生效如果预算检查生效那么它一定会报超长",
  }],
};

const OVERLONG_SOURCE = {
  segments: [{ id: 0, start: 0, end: 2, text: OVERLONG.segments[0].text }],
};

// A user writing "zh-CN" or "ZH" means Chinese. Looking the code up raw missed the
// baseline, skipped the budget check, and still printed "Clean" — a silent pass on
// a check that never ran.
for (const code of ["zh-CN", "zh_CN", "ZH", " zh "]) {
  test(`--lang ${JSON.stringify(code)} resolves to the zh baseline`, () => {
    const translated = { ...OVERLONG, target_lang: code };
    const { code: exit, out } = check(translated, { source: OVERLONG_SOURCE, lang: code });
    assert.equal(exit, 1, `expected the zh budget to apply:\n${out}`);
    assert.match(out, /pace\.too_long/);
  });
}

// No calibrated ceiling exists for these. Skipping the check is fine; reporting
// "Clean" as though it ran is not.
test("an uncalibrated language says the budget check was skipped", () => {
  const translated = { ...OVERLONG, target_lang: "it" };
  const { code, out } = check(translated, { source: OVERLONG_SOURCE, lang: "it" });
  assert.equal(code, 0, out);
  assert.doesNotMatch(out, /^Clean\.$/m, "a bare 'Clean.' hides that a check never ran");
  assert.match(out, /skipped/i);
  assert.match(out, /\bit\b/, "name the language that has no baseline");
});

test("omitting --lang says the language-dependent checks were skipped", () => {
  const { dir, sourcePath, translatedPath } = workspace(OVERLONG, OVERLONG_SOURCE);
  try {
    const run = spawnSync(
      process.execPath,
      [SCRIPT, "--translated", translatedPath, "--source", sourcePath],
      { encoding: "utf8" },
    );
    const out = `${run.stdout}${run.stderr}`;
    assert.equal(run.status, 0, out);
    assert.doesNotMatch(out, /^Clean\.$/m);
    assert.match(out, /skipped/i);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

// A typo'd flag used to be swallowed: "--src file.json" left source undefined, the
// invariant checks quietly turned into a SKIP, and the run exited 0. Same silent-gap
// failure mode as an unknown language, one keystroke away.
test("a misspelled flag is rejected, not swallowed", () => {
  const { dir, sourcePath, translatedPath } = workspace(CLEAN);
  try {
    const run = spawnSync(
      process.execPath,
      [SCRIPT, "--translated", translatedPath, "--src", sourcePath, "--lang", "zh"],
      { encoding: "utf8" },
    );
    const out = `${run.stdout}${run.stderr}`;
    assert.equal(run.status, 2, `a typo'd flag must not pass as a clean run:\n${out}`);
    assert.match(out, /--src/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("a malformed segment reports which segment, not a JS internal error", () => {
  const translated = { target_lang: "zh", segments: [CLEAN.segments[0], null] };
  const { code, out } = check(translated, { source: SOURCE });
  assert.equal(code, 2, out);
  assert.match(out, /segment\.malformed/);
  assert.doesNotMatch(out, /Cannot read properties/, "raw TypeError text is not a diagnosis");
});

test("punctuation carried over from the source is not flagged", () => {
  const source = {
    segments: [{ id: 0, start: 0, end: 4, text: "The demux — or demultiplexer (as the spec calls it)." }],
  };
  const translated = {
    target_lang: "zh",
    segments: [{ id: 0, start: 0, end: 4, text: source.segments[0].text, translation: "解复用器——也就是（规范里说的）多路分配器。" }],
  };
  const { code, out } = check(translated, { source });
  assert.equal(code, 0, `source had both marks, so neither is drift:\n${out}`);
});

test("it runs without --source, checking only what one file can prove", () => {
  const { dir, translatedPath } = workspace(mutate(1, { translation: "" }));
  try {
    const run = spawnSync(process.execPath, [SCRIPT, "--translated", translatedPath], { encoding: "utf8" });
    assert.equal(run.status, 2, run.stdout + run.stderr);
    assert.match(run.stdout + run.stderr, /translation\.empty/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
