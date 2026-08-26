#!/usr/bin/env node
// Verify a translated EdgeSpeak transcript against the invariants in SKILL.md.
// Zero dependencies, Node 18+. Exit 0 = clean, 1 = WARN, 2 = FAIL.

import { readFileSync, realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";

// Hard ceilings in characters per second — beyond these, synthesized speech
// compresses audibly. Same table as SKILL.md.
const CPS = Object.freeze({
  zh: 9, ja: 20, ko: 17, en: 22, fr: 35, es: 31, pt: 34, de: 43, nl: 33, ru: 37, hi: 27,
});

// Below these the cue is too short for the budget to mean anything.
const MIN_DURATION = 1.5;
const MIN_SOURCE_CHARS = 20;

// Marks that change how a line is delivered, and must not appear unless the
// source had one of the same class. Latin and CJK forms are interchangeable.
const PUNCT_CLASSES = [
  { code: "punct.dash", label: "an em-dash", pattern: /——|—|–|--/ },
  { code: "punct.paren", label: "parentheses", pattern: /[（(]/ },
  { code: "punct.bracket", label: "brackets", pattern: /[[【]/ },
];

const USAGE = `Usage: check-translation.mjs --translated <file.json> [--source <file.json>] [--lang <code>]

  --translated  Required. Transcript JSON carrying a "translation" per segment.
  --source      Optional. The pre-translation transcript. Enables the invariant
                checks (segment count, id, text, start/end, words).
  --lang        Optional. Expected target language code; also selects the
                character-budget ceiling.`;

const FLAGS = new Set(["translated", "source", "lang"]);

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i];
    if (flag === "-h" || flag === "--help") return { help: true };
    if (!flag.startsWith("--")) throw new Error(`unexpected argument: ${flag}`);
    const name = flag.slice(2);
    // Swallowing an unknown flag turns "--src file" into "no --source given", which
    // downgrades the invariant checks to a SKIP and still exits 0 — a typo silently
    // buying a clean bill of health.
    if (!FLAGS.has(name)) {
      throw new Error(`unknown flag: ${flag} (accepted: ${[...FLAGS].map((f) => `--${f}`).join(", ")})`);
    }
    const value = argv[i + 1];
    if (value === undefined || value.startsWith("--")) throw new Error(`${flag} needs a value`);
    args[name] = value;
    i += 1;
  }
  return args;
}

function readTranscript(path, label) {
  let parsed;
  try {
    parsed = JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    throw new Error(`cannot read ${label} (${path}): ${error.message}`);
  }
  const segments = parsed?.segments;
  if (!Array.isArray(segments) || segments.length === 0) {
    throw new Error(`${label} (${path}) has no non-empty "segments" array`);
  }
  return parsed;
}

// Count codepoints, not UTF-16 units: a surrogate pair is one spoken character.
const chars = (text) => [...String(text ?? "")].length;

const LOGOGRAPHIC = new Set(["zh", "ja", "ko"]);

// "zh-CN", "zh_CN", "ZH", " zh " all mean zh. Looking the raw string up in CPS
// misses the baseline and skips the budget check on a language that has one.
const normalizeLang = (lang) => String(lang ?? "").trim().toLowerCase().split(/[-_]/)[0];

// How long a line takes to speak, in units of one CJK character.
//
// The CJK ceilings assume one character is one spoken syllable-ish unit, which
// breaks on the brand names and acronyms that survive translation untranslated:
// "Claude" is 6 letters but speaks in about the time of 2 Chinese characters, and
// the spaces around it are not spoken at all. Counting them raw made a well-fitting
// line look 40% over budget. Latin-script targets keep the raw count — their
// ceilings were calibrated on text that includes its own letters and spaces.
function spokenLength(text, lang) {
  const raw = String(text ?? "");
  if (!LOGOGRAPHIC.has(lang)) return chars(raw);
  let latin = 0;
  const remainder = raw
    .replace(/[A-Za-z]+/g, (word) => {
      latin += Math.max(1, Math.ceil(word.length / 3));
      return "";
    })
    .replace(/ /g, "");
  return latin + chars(remainder);
}

// Timestamps survive a JSON round-trip exactly; this only absorbs float noise
// from a rewrite that recomputed them.
const sameTime = (a, b) => Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) < 1e-6;

function checkInvariants(source, target, index, fail) {
  const at = (code, message) => fail(code, index, message);
  if (source.text !== target.text) at("invariant.text", "source text was modified — it must survive verbatim");
  if (!sameTime(source.start, target.start)) at("invariant.start", `start moved ${source.start} → ${target.start}`);
  if (!sameTime(source.end, target.end)) at("invariant.end", `end moved ${source.end} → ${target.end}`);
  if (source.id !== undefined && source.id !== target.id) {
    at("invariant.id", `id changed ${JSON.stringify(source.id)} → ${JSON.stringify(target.id)}`);
  }
  if (!Array.isArray(source.words)) return;
  if (!Array.isArray(target.words) || target.words.length !== source.words.length) {
    at("invariant.words", `words[] must be preserved verbatim (${source.words.length} in source)`);
    return;
  }
  const drifted = source.words.findIndex((word, i) => {
    const other = target.words[i];
    return word.word !== other?.word || !sameTime(word.start, other?.start) || !sameTime(word.end, other?.end);
  });
  if (drifted !== -1) at("invariant.words", `words[${drifted}] was altered — word timings describe the source audio`);
}

function checkPunctuation(sourceText, translation, index, warn) {
  for (const { code, label, pattern } of PUNCT_CLASSES) {
    if (pattern.test(translation) && !pattern.test(sourceText)) {
      warn(code, index, `translation adds ${label}; the source has none — rewrite the connector instead`);
    }
  }
  // "A / B" shipping two candidate renderings of one term: TTS reads the slash aloud.
  if (/\S\s*[/]\s*\S/.test(translation) && !translation.includes("://") && !sourceText.includes("/")) {
    warn("term.alternatives", index, 'translation offers alternatives with "/" — pick one rendering and reuse it');
  }
}

function checkBudget(segment, translation, lang, index, warn) {
  const ceiling = CPS[lang];
  if (!ceiling) return;
  const duration = segment.end - segment.start;
  if (!Number.isFinite(duration) || duration < MIN_DURATION) return;
  if (chars(segment.text) < MIN_SOURCE_CHARS) return;
  const budget = Math.floor(duration * ceiling);
  const actual = spokenLength(translation, lang);
  if (actual > budget) {
    warn(
      "pace.too_long",
      index,
      `${actual} spoken chars over a ${duration.toFixed(2)}s cue exceeds the ${lang} budget of ${budget} — compress the phrasing`,
    );
  }
}

export function check({ translated, source, lang }) {
  const fails = [];
  const warns = [];
  const skipped = [];
  const fail = (code, index, message) => fails.push({ code, index, message });
  const warn = (code, index, message) => warns.push({ code, index, message });

  const segments = translated.segments;
  const sourceSegments = source?.segments;
  const code = normalizeLang(lang);

  // Say what did not run. A check that silently disappears reads as a check that passed.
  if (!code) {
    skipped.push("character budget and target_lang — no --lang given");
  } else if (!CPS[code]) {
    skipped.push(`character budget — no calibrated speaking rate for "${code}" (have: ${Object.keys(CPS).join(", ")})`);
  }
  if (!source) skipped.push("segment count and the id / text / start / end / words invariants — no --source given");

  if (sourceSegments && sourceSegments.length !== segments.length) {
    fail("count.mismatch", null, `${segments.length} translated segments vs ${sourceSegments.length} in source — the 1:1 mapping is broken`);
  }
  if (code && translated.target_lang && normalizeLang(translated.target_lang) !== code) {
    fail("lang.mismatch", null, `target_lang is "${translated.target_lang}" but --lang says "${lang}"`);
  }

  let totalSource = 0;
  let totalTranslated = 0;

  segments.forEach((segment, index) => {
    // Name the bad segment rather than letting a TypeError surface as the diagnosis.
    if (!segment || typeof segment !== "object" || Array.isArray(segment)) {
      fail("segment.malformed", index, `expected an object, got ${segment === null ? "null" : typeof segment}`);
      return;
    }
    const translation = segment.translation;
    if (typeof translation !== "string" || translation.trim() === "") {
      fail("translation.empty", index, "missing or empty translation");
      return;
    }
    if (/\bTODO\b|\?\?\?|\[[A-Z]{2}\]/.test(translation)) {
      warn("translation.marker", index, "translation still carries a placeholder or debug marker");
    }

    const sourceSegment = sourceSegments?.[index];
    if (sourceSegment) checkInvariants(sourceSegment, segment, index, fail);

    const sourceText = sourceSegment?.text ?? segment.text ?? "";
    checkPunctuation(sourceText, translation, index, warn);
    checkBudget({ ...segment, text: sourceText }, translation, code, index, warn);

    totalSource += chars(sourceText);
    totalTranslated += chars(translation);
  });

  const ratio = totalSource > 0 ? (totalTranslated / totalSource).toFixed(2) : "n/a";
  return { fails, warns, skipped, info: { segments: segments.length, ratio } };
}

function main() {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(`${error.message}\n\n${USAGE}`);
    process.exit(2);
  }
  if (args.help || !args.translated) {
    console.log(USAGE);
    process.exit(args.help ? 0 : 2);
  }

  let result;
  try {
    result = check({
      translated: readTranscript(args.translated, "translated transcript"),
      source: args.source ? readTranscript(args.source, "source transcript") : undefined,
      lang: args.lang,
    });
  } catch (error) {
    console.error(`FAIL  ${error.message}`);
    process.exit(2);
  }

  const where = (index) => (index === null ? "        " : `seg ${String(index).padEnd(4)}`);
  for (const { code, index, message } of result.fails) console.log(`FAIL  ${where(index)}  ${code.padEnd(20)}  ${message}`);
  for (const { code, index, message } of result.warns) console.log(`WARN  ${where(index)}  ${code.padEnd(20)}  ${message}`);
  for (const note of result.skipped) console.log(`SKIP  ${"".padEnd(8)}  ${"not checked".padEnd(20)}  ${note}`);
  console.log(`INFO  ${result.info.segments} segments · translated/source char ratio ${result.info.ratio}`);

  // Never let a check that did not run read as a check that passed.
  const caveat = result.skipped.length > 0 ? ` (${result.skipped.length} check(s) skipped — see SKIP above)` : "";

  if (result.fails.length > 0) {
    console.log(`\n${result.fails.length} FAIL, ${result.warns.length} WARN${caveat} — the output does not match the audio. Fix the segments above.`);
    process.exit(2);
  }
  if (result.warns.length > 0) {
    console.log(`\n0 FAIL, ${result.warns.length} WARN${caveat} — structurally sound. Review each warning, then fix it or say why it stands.`);
    process.exit(1);
  }
  console.log(result.skipped.length > 0 ? `\nNo findings, but not fully checked${caveat}.` : "\nClean.");
}

// Compare real paths: Node resolves import.meta.url through symlinks but leaves
// process.argv[1] as typed, so a symlinked invocation (the `.claude/skills/...`
// path) would otherwise skip main() and exit 0.
function isDirectRun() {
  const entry = process.argv[1];
  if (!entry) return false;
  try {
    return realpathSync(fileURLToPath(import.meta.url)) === realpathSync(entry);
  } catch {
    return false;
  }
}

if (isDirectRun()) main();
