// Run with: node --test skills/edgespeak-karaoke/scripts/
import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  buildAss,
  detectScriptLang,
  loadTranscript,
  resolveStyle,
  resolveTranslationFont,
  resolveWindowsTranslationFont,
} from "./karaoke-ass.mjs";

const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), "karaoke-ass.mjs");

const TRANSCRIPT = {
  segments: [
    {
      start: 0.5,
      end: 2.0,
      text: "hello world",
      words: [
        { word: "hello", start: 0.5, end: 1.2 },
        { word: "world", start: 1.3, end: 2.0 },
      ],
    },
  ],
};

const TRANSLATED = {
  segments: TRANSCRIPT.segments.map((segment) => ({ ...segment, translation: "你好世界" })),
};

// The font checks below need a real fontconfig; skip rather than fail on a box without it.
function hasFontconfig() {
  try {
    execFileSync("fc-match", ["--version"], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

function workspace(payload = TRANSCRIPT) {
  const dir = mkdtempSync(join(tmpdir(), "karaoke-ass-test-"));
  const transcript = join(dir, "transcript.json");
  writeFileSync(transcript, JSON.stringify(payload), "utf8");
  return { dir, transcript, output: join(dir, "out.ass") };
}

// Regression guard: the plain, non-symlinked invocation must keep working.
test("generates ASS when invoked via the real script path", () => {
  const { dir, transcript, output } = workspace();
  try {
    execFileSync(process.execPath, [SCRIPT, transcript, "-o", output], { stdio: "pipe" });
    assert.ok(existsSync(output), "expected ASS output from a direct invocation");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

// The bug: SKILL.md documents the `.claude/skills/...` symlink path. Node resolves
// import.meta.url through symlinks but leaves process.argv[1] as typed, so the old
// entry-point guard compared two different strings, skipped main(), and exited 0
// without writing anything -- a silent no-op that looks like success.
test("generates ASS when invoked through a symlinked script path", () => {
  const { dir, transcript, output } = workspace();
  try {
    const linkDir = join(dir, "linked");
    mkdirSync(linkDir);
    const link = join(linkDir, "karaoke-ass.mjs");
    symlinkSync(SCRIPT, link);

    execFileSync(process.execPath, [link, transcript, "-o", output], { stdio: "pipe" });
    assert.ok(existsSync(output), "expected ASS output when invoked through a symlink");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

// The guard still has to earn its keep: this module exports helpers, so importing
// it must not run the CLI.
test("importing the module does not execute the CLI", async () => {
  const module = await import(`${pathToFileURL(SCRIPT).href}?probe=1`);
  assert.equal(typeof module.buildAss, "function");
  assert.equal(typeof module.loadTranscript, "function");
});

test("kana and hangul win over the Han characters mixed in with them", () => {
  assert.equal(detectScriptLang("これは日本語です"), "ja");
  assert.equal(detectScriptLang("한국어 漢字"), "ko");
  assert.equal(detectScriptLang("这是中文"), "zh-cn");
  assert.equal(detectScriptLang("Это по-русски"), "ru");
  assert.equal(detectScriptLang("plain latin text"), null);
});

// The bug this guards: libass renders uncovered codepoints as blank boxes without any
// error, so a Latin font on a CJK translation produces a whole burned video of tofu.
test("a translation font that cannot cover the script is refused", { skip: !hasFontconfig() }, () => {
  assert.throws(
    () => resolveTranslationFont("你好世界", { requested: "Arial", fallback: "Arial" }),
    /does not cover zh-cn/,
  );
});

test("a CJK translation auto-selects a font that covers it", { skip: !hasFontconfig() }, () => {
  const resolved = resolveTranslationFont("你好世界", { fallback: "Arial" });
  assert.equal(resolved.lang, "zh-cn");
  assert.equal(resolved.verified, true);
  // ASS delimits style fields with commas, so an alias list would corrupt the style row.
  assert.ok(!resolved.font.includes(","), `font must be a single alias, got "${resolved.font}"`);
});

test("a Latin translation keeps the preset font without consulting fontconfig", () => {
  const resolved = resolveTranslationFont("bonjour le monde", { fallback: "Arial" });
  assert.deepEqual(resolved, { font: "Arial", lang: null, verified: true });
});

test("Windows auto-selects a known installed font without fontconfig", () => {
  const dir = mkdtempSync(join(tmpdir(), "karaoke-font-test-"));
  try {
    const fonts = join(dir, "Fonts");
    mkdirSync(fonts);
    writeFileSync(join(fonts, "msyh.ttc"), "");
    assert.equal(resolveWindowsTranslationFont("zh-cn", dir), "Microsoft YaHei");
    assert.equal(resolveWindowsTranslationFont("ja", dir), null);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("translations in the transcript turn on bilingual output by default", () => {
  const { dir, transcript, output } = workspace(TRANSLATED);
  try {
    execFileSync(process.execPath, [SCRIPT, transcript, "-o", output], { stdio: "pipe" });
    const ass = readFileSync(output, "utf8");
    assert.match(ass, /^Style: Translation,/m);
    assert.match(ass, /\{\\rTranslation\}你好世界/);
    // One event carrying both lines, not two events fighting over the same margin.
    assert.equal(ass.match(/^Dialogue:/gm).length, 1);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("--layout source-only ignores the translations", () => {
  const { dir, transcript, output } = workspace(TRANSLATED);
  try {
    execFileSync(process.execPath, [SCRIPT, transcript, "-o", output, "--layout", "source-only"], { stdio: "pipe" });
    const ass = readFileSync(output, "utf8");
    assert.doesNotMatch(ass, /Translation/);
    assert.doesNotMatch(ass, /你好世界/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("the layout decides which line is full size", () => {
  const style = resolveStyle("classic");
  const options = { title: "t", style, translationFont: "Arial" };
  const topIsTranslation = buildAss(TRANSLATED.segments, { ...options, layout: "translation-top" });
  const topIsSource = buildAss(TRANSLATED.segments, { ...options, layout: "source-top" });

  assert.match(topIsTranslation, new RegExp(`^Style: Translation,Arial,${style.fontSize},`, "m"));
  assert.match(topIsSource, new RegExp(`^Style: Karaoke,${style.font},${style.fontSize},`, "m"));
  // The translation leads the event text in one and trails it in the other.
  assert.ok(topIsTranslation.includes("karaoke,{\\rTranslation}"));
  assert.ok(topIsSource.includes("karaoke,{\\rKaraoke}"));
});

// A half-translated transcript means the translate step stopped early. Silently emitting
// source-only cues for the rest would pass that off as a complete bilingual file.
test("a partly translated transcript is rejected", () => {
  const { dir, transcript } = workspace({
    segments: [
      { ...TRANSCRIPT.segments[0], translation: "你好世界" },
      { start: 3.0, end: 4.0, text: "again", words: [{ word: "again", start: 3.0, end: 4.0 }] },
    ],
  });
  try {
    assert.throws(() => loadTranscript(transcript), /only 1 of 2 segments carry a translation/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("a bilingual layout on an untranslated transcript fails loudly", () => {
  const { dir, transcript, output } = workspace();
  try {
    assert.throws(
      () => execFileSync(process.execPath, [SCRIPT, transcript, "-o", output, "--layout", "source-top"], { stdio: "pipe" }),
      /needs segments\[\]\.translation/,
    );
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

// 词间分隔符必须来自 segment.text 本身。逐词插一个空格会改写原文：CJK 词之间本来
// 没有空格，而 forced alignment 把 "high-performance" 拆成两个词（连字符不在任何 word 里）。
const SOURCE_ONLY = { title: "t", style: resolveStyle("classic"), translationFont: "Arial", layout: "source-only" };

function visibleText(ass) {
  const line = ass.split("\n").find((l) => l.startsWith("Dialogue:"));
  let comma = -1;
  for (let i = 0; i < 9; i += 1) comma = line.indexOf(",", comma + 1);
  return line.slice(comma + 1).replaceAll(/\{[^}]*\}/g, "");
}

test("CJK cues keep the original spacing instead of one space per word", () => {
  const segments = [
    {
      start: 0,
      end: 2,
      text: "它完全在本地运行，确保安全。",
      words: [
        { word: "它", start: 0, end: 0.3 },
        { word: "完全", start: 0.3, end: 0.7 },
        { word: "在", start: 0.7, end: 0.9 },
        { word: "本地", start: 0.9, end: 1.3 },
        { word: "运行，", start: 1.3, end: 1.6 },
        { word: "确保", start: 1.6, end: 1.8 },
        { word: "安全。", start: 1.8, end: 2 },
      ],
    },
  ];
  assert.equal(visibleText(buildAss(segments, SOURCE_ONLY)), "它完全在本地运行，确保安全。");
});

test("a hyphenated word stays hyphenated in the rendered line", () => {
  const segments = [
    {
      start: 0,
      end: 2,
      text: "a high-performance engine",
      words: [
        { word: "a", start: 0, end: 0.3 },
        { word: "high", start: 0.3, end: 0.8 },
        { word: "performance", start: 0.8, end: 1.5 },
        { word: "engine", start: 1.5, end: 2 },
      ],
    },
  ];
  assert.equal(visibleText(buildAss(segments, SOURCE_ONLY)), "a high-performance engine");
});

// libass does not fall back per glyph, so a CJK source line in a Latin preset font burns
// as blank boxes -- silently, all the way through the render. The source line needs the
// same script-aware font resolution the translation line already gets.
const CJK_SOURCE = {
  segments: [
    {
      start: 0,
      end: 1,
      text: "本地转录",
      words: [
        { word: "本地", start: 0, end: 0.5 },
        { word: "转录", start: 0.5, end: 1 },
      ],
    },
  ],
};

function karaokeStyleRow(ass) {
  return ass.split("\n").find((line) => line.startsWith("Style: Karaoke,"));
}

test("a CJK source line auto-selects a font that covers it", { skip: !hasFontconfig() }, () => {
  const { dir, transcript, output } = workspace(CJK_SOURCE);
  try {
    execFileSync(process.execPath, [SCRIPT, transcript, "-o", output], { stdio: "pipe" });
    const row = karaokeStyleRow(readFileSync(output, "utf8"));
    assert.doesNotMatch(row, /^Style: Karaoke,Arial,/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("a Latin source line keeps the preset font", () => {
  const ass = buildAss(TRANSCRIPT.segments, SOURCE_ONLY);
  assert.match(karaokeStyleRow(ass), /^Style: Karaoke,Arial,/);
});

test("a --font that cannot cover the source script is refused", { skip: !hasFontconfig() }, () => {
  const { dir, transcript, output } = workspace(CJK_SOURCE);
  try {
    assert.throws(
      () => execFileSync(process.execPath, [SCRIPT, transcript, "-o", output, "--font", "Arial"], { stdio: "pipe" }),
      /does not cover zh-cn/,
    );
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("words that do not match the segment text fall back to single spaces", () => {
  // 对不上就不猜：回到旧行为，而不是产出错位的分隔符。
  const segments = [
    {
      start: 0,
      end: 1,
      text: "totally different text",
      words: [
        { word: "alpha", start: 0, end: 0.5 },
        { word: "beta", start: 0.5, end: 1 },
      ],
    },
  ];
  assert.equal(visibleText(buildAss(segments, SOURCE_ONLY)), "alpha beta");
});
