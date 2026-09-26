#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { basename, dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const STYLES = Object.freeze({
  classic: {
    description: "Balanced white text with a warm gold sweep; safe for most landscape videos.",
    font: "Arial",
    fontSize: 54,
    primary: "&H0000D7FF",
    secondary: "&H00FFFFFF",
    outline: "&H00101010",
    back: "&H80000000",
    borderStyle: 1,
    outlineWidth: 3,
    shadow: 0,
    marginV: 76,
  },
  minimal: {
    description: "Quieter typography with a cyan sweep for clean or dark footage.",
    font: "Arial",
    fontSize: 50,
    primary: "&H00FFD66E",
    secondary: "&H00FFFFFF",
    outline: "&H00181818",
    back: "&H50000000",
    borderStyle: 1,
    outlineWidth: 2,
    shadow: 0,
    marginV: 70,
  },
  boxed: {
    description: "Translucent dark box for busy, bright, or presentation footage.",
    font: "Arial",
    fontSize: 50,
    primary: "&H0000D7FF",
    secondary: "&H00FFFFFF",
    outline: "&H00101010",
    back: "&H78000000",
    borderStyle: 3,
    outlineWidth: 8,
    shadow: 0,
    marginV: 72,
  },
  "high-contrast": {
    description: "Large yellow sweep and heavy outline for vertical, mobile, or difficult footage.",
    font: "Arial",
    fontSize: 60,
    primary: "&H0000FFFF",
    secondary: "&H00FFFFFF",
    outline: "&H00000000",
    back: "&H90000000",
    borderStyle: 1,
    outlineWidth: 4,
    shadow: 0,
    marginV: 86,
  },
});

// Bilingual layout: the top line renders at the preset size and the line beneath it at
// SECONDARY_SCALE, so the eye lands on the top line first whichever language sits there.
const SECONDARY_SCALE = 0.72;

// libass does not substitute fonts per glyph the way a browser does: a codepoint the
// style's font lacks renders as tofu, silently, all the way through a burn. So a
// translation written in one of these scripts has to be matched to a font that actually
// claims the language rather than inheriting the preset's Latin font.
const SCRIPTS = Object.freeze([
  { lang: "ja", test: /[぀-ヿ]/ },              // kana disambiguates Japanese from Han
  { lang: "ko", test: /[가-힯ᄀ-ᇿ]/ },
  { lang: "zh-cn", test: /[㐀-䶿一-鿿豈-﫿]/ },
  { lang: "ru", test: /[Ѐ-ӿ]/ },
  { lang: "el", test: /[Ͱ-Ͽ]/ },
  { lang: "he", test: /[֐-׿]/ },
  { lang: "ar", test: /[؀-ۿ]/ },
  { lang: "hi", test: /[ऀ-ॿ]/ },
  { lang: "th", test: /[฀-๿]/ },
]);

const WINDOWS_FONT_CANDIDATES = Object.freeze({
  ja: [
    { family: "Yu Gothic", files: ["YuGothM.ttc", "YuGothR.ttc"] },
    { family: "Meiryo", files: ["meiryo.ttc"] },
  ],
  ko: [{ family: "Malgun Gothic", files: ["malgun.ttf"] }],
  "zh-cn": [
    { family: "Microsoft YaHei", files: ["msyh.ttc"] },
    { family: "SimSun", files: ["simsun.ttc"] },
  ],
  ru: [{ family: "Arial", files: ["arial.ttf"] }],
  el: [{ family: "Arial", files: ["arial.ttf"] }],
  he: [{ family: "Arial", files: ["arial.ttf"] }],
  ar: [{ family: "Arial", files: ["arial.ttf"] }],
  hi: [{ family: "Nirmala UI", files: ["Nirmala.ttf"] }],
  th: [
    { family: "Leelawadee UI", files: ["LeelawUI.ttf"] },
    { family: "Tahoma", files: ["tahoma.ttf"] },
  ],
});

function fail(message) {
  console.error(message);
  process.exitCode = 1;
}

// Returns the fontconfig language tag the translation needs, or null when it is Latin
// enough for the preset font. Order matters: kana and hangul are checked before Han
// because Japanese and Korean text mixes in Han characters.
export function detectScriptLang(text) {
  return SCRIPTS.find((script) => script.test.test(text))?.lang ?? null;
}

function fontconfig(command, args) {
  try {
    return execFileSync(command, args, { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
  } catch {
    return null; // fontconfig absent (common in minimal containers) or no match
  }
}

// fc-match returns every alias of the matched family, comma-separated and often with the
// localized name first ("冬青黑体简体中文,Hiragino Sans GB,..."). ASS delimits Style fields
// with commas, so only one alias can be used -- prefer an ASCII one to keep the file
// portable between machines whose fontconfig localizes names differently.
function pickAlias(families) {
  const aliases = families.split(",").map((alias) => alias.trim()).filter(Boolean);
  return aliases.find((alias) => /^[\x20-\x7E]+$/.test(alias)) ?? aliases[0] ?? null;
}

// `fc-list "<family>" lang` prints one `:lang=aa|ab|...` line per matching face. Ask the
// font what it claims rather than asking fontconfig to match -- a family-name match wins
// over a :lang= constraint, so `fc-match "Arial:lang=zh"` cheerfully returns Arial.
function claimsLang(font, lang) {
  const listed = fontconfig("fc-list", [font, "lang"]);
  if (listed === null) return null; // fontconfig missing: unverifiable, not a failure
  if (!listed) return false;
  return listed
    .split("\n")
    .some((line) => (line.split(":lang=")[1] ?? "").split("|").includes(lang));
}

export function resolveWindowsTranslationFont(lang, windowsDir = process.env.WINDIR) {
  if (!windowsDir) return null;
  const fontsDir = join(windowsDir, "Fonts");
  for (const candidate of WINDOWS_FONT_CANDIDATES[lang] ?? []) {
    if (candidate.files.some((file) => existsSync(join(fontsDir, file)))) {
      return candidate.family;
    }
  }
  return null;
}

// Resolves the font for one rendered line, and refuses to emit a file that would render
// as tofu. Both lines need this: libass does not fall back per glyph, so CJK in a Latin
// font burns as blank boxes whether it is the translation or the source. Returns
// { font, lang, verified }.
export function resolveTranslationFont(text, { requested, fallback, line = "translation", flag = "--translation-font" }) {
  const lang = detectScriptLang(text);
  if (!lang) return { font: requested ?? fallback, lang: null, verified: true };

  if (requested) {
    const covers = claimsLang(requested, lang);
    if (covers === false) {
      throw new Error(
        `${flag} "${requested}" does not cover ${lang}; libass would render the ${line} as blank boxes. ` +
          `Pick a font that does (fc-list :lang=${lang} family) or drop the flag to auto-select one.`,
      );
    }
    return { font: requested, lang, verified: covers === true };
  }

  if (process.platform === "win32") {
    const font = resolveWindowsTranslationFont(lang);
    if (font) return { font, lang, verified: true };
  }

  const matched = fontconfig("fc-match", ["-f", "%{family}", `:lang=${lang}`]);
  const font = matched ? pickAlias(matched) : null;
  if (!font) {
    throw new Error(
      `the ${line} is ${lang} but no font could be auto-selected for it` +
        `${matched === null ? " (fontconfig is not installed)" : ""}. ` +
        `Pass ${flag} <name> with a font that covers ${lang}.`,
    );
  }
  return { font, lang, verified: claimsLang(font, lang) === true };
}

function parseArgs(argv) {
  const options = { style: "classic", title: "EdgeSpeak Karaoke" };
  const positional = [];
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("-")) {
      positional.push(token);
      continue;
    }
    if (token === "--list-styles" || token === "--overwrite") {
      options[token.slice(2).replaceAll("-", "_")] = true;
      continue;
    }
    const key = token === "-o" ? "output" : token.slice(2).replaceAll("-", "_");
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`${token} requires a value`);
    options[key] = value;
    index += 1;
  }
  options.input = positional[0];
  return options;
}

function number(value, field) {
  const result = Number(value);
  if (!Number.isFinite(result) || result < 0) throw new Error(`${field} must be finite and non-negative`);
  return result;
}

export function loadTranscript(path) {
  let payload = JSON.parse(readFileSync(path, "utf8"));
  if (payload && typeof payload.result === "object") payload = payload.result;
  if (!payload || !Array.isArray(payload.segments) || payload.segments.length === 0) {
    throw new Error("input JSON does not contain non-empty segments[]");
  }
  let previousEnd = 0;
  let wordCount = 0;
  let translated = 0;
  payload.segments.forEach((segment, segmentIndex) => {
    if (String(segment.translation ?? "").trim()) translated += 1;
    const start = number(segment.start, `segments[${segmentIndex}].start`);
    const end = number(segment.end, `segments[${segmentIndex}].end`);
    if (end <= start) throw new Error(`segments[${segmentIndex}] must have end > start`);
    if (segmentIndex > 0 && start < previousEnd - 0.01) {
      throw new Error("segments overlap; request start_margin=0 and end_margin=0 for karaoke");
    }
    previousEnd = end;
    if (!Array.isArray(segment.words) || segment.words.length === 0) {
      throw new Error(`segments[${segmentIndex}].words[] is missing; request timestamps=\"word\" instead of aligning the ASR text afterward`);
    }
    let previousWordEnd = start;
    segment.words.forEach((word, wordIndex) => {
      if (!word || !String(word.word ?? "").trim()) {
        throw new Error(`segments[${segmentIndex}].words[${wordIndex}] has no word`);
      }
      const wordStart = number(word.start, `segments[${segmentIndex}].words[${wordIndex}].start`);
      const wordEnd = number(word.end, `segments[${segmentIndex}].words[${wordIndex}].end`);
      if (wordEnd <= wordStart) throw new Error(`segments[${segmentIndex}].words[${wordIndex}] must have end > start`);
      if (wordStart < previousWordEnd - 0.01) throw new Error(`segments[${segmentIndex}].words[] is not monotonic`);
      previousWordEnd = wordEnd;
      wordCount += 1;
    });
  });
  // A partly-translated transcript means the translate step stopped early. Falling back
  // to source-only would hide that; dropping the untranslated cues would desync the file.
  if (translated > 0 && translated < payload.segments.length) {
    throw new Error(
      `only ${translated} of ${payload.segments.length} segments carry a translation; ` +
        "every segment needs one for bilingual output",
    );
  }
  return { segments: payload.segments, wordCount, translated: translated > 0 };
}

function assTime(seconds) {
  let cs = Math.max(0, Math.round(seconds * 100));
  const hours = Math.floor(cs / 360000);
  cs %= 360000;
  const minutes = Math.floor(cs / 6000);
  cs %= 6000;
  const wholeSeconds = Math.floor(cs / 100);
  return `${hours}:${String(minutes).padStart(2, "0")}:${String(wholeSeconds).padStart(2, "0")}.${String(cs % 100).padStart(2, "0")}`;
}

function escapeAss(text) {
  return text.replaceAll("\\", "\\\\").replaceAll("{", "\\{").replaceAll("}", "\\}");
}

// 词间分隔符取自 segment.text 本身，而不是一律补一个空格。强制对齐把标点并入词，
// 每个 word 都是 text 的子串且出现位置单调递增，所以顺序扫描能无损还原原文的分隔：
// CJK 词之间的零间隔、"high-performance" 被拆开后中间的连字符、"U.S." 的点，都靠这个还原。
// 任一词对不上就返回 null —— 交给调用方回退到单空格，不猜。
function wordSeparators(segment) {
  const text = String(segment.text ?? "");
  if (!text) return null;
  const separators = [];
  let cursor = 0;
  for (const word of segment.words) {
    const token = String(word.word).trim();
    if (!token) return null;
    const at = text.indexOf(token, cursor);
    if (at < 0) return null;
    separators.push(text.slice(cursor, at));
    cursor = at + token.length;
  }
  return separators;
}

function karaokeText(segment) {
  const eventStart = Math.round(Number(segment.start) * 100) / 100;
  const separators = wordSeparators(segment);
  let cursor = 0;
  const pieces = [];
  segment.words.forEach((word, index) => {
    const wordStart = Math.max(cursor, Math.round((Number(word.start) - eventStart) * 100));
    const gap = wordStart - cursor;
    if (index === 0 && gap > 0) pieces.push(`{\\k${gap}}`);
    if (index > 0) {
      // 换行/制表/连续空白在一行字幕里没有意义，归一成单空格；其余字符原样保留。
      const separator = escapeAss((separators ? separators[index] : " ").replaceAll(/\s+/g, " "));
      pieces.push(gap > 0 ? `{\\k${gap}}${separator}` : separator);
    }
    const wordEnd = Math.round((Number(word.end) - eventStart) * 100);
    const duration = Math.max(1, wordEnd - wordStart);
    pieces.push(`{\\kf${duration}}${escapeAss(String(word.word).trim())}`);
    cursor = wordStart + duration;
  });
  return pieces.join("");
}

function checkedColor(value, field) {
  if (!/^&H[0-9A-Fa-f]{8}$/.test(value)) throw new Error(`${field} must use ASS &HAABBGGRR format`);
  return value.toUpperCase();
}

export function resolveStyle(name, overrides = {}) {
  const preset = STYLES[name];
  if (!preset) throw new Error(`unknown style: ${name}; use one of ${Object.keys(STYLES).join(", ")}`);
  const result = { ...preset };
  if (overrides.font) result.font = overrides.font;
  if (overrides.font_size !== undefined) result.fontSize = number(overrides.font_size, "--font-size");
  if (overrides.margin_v !== undefined) result.marginV = number(overrides.margin_v, "--margin-v");
  for (const field of ["primary", "secondary", "outline", "back"]) {
    if (overrides[field]) result[field] = checkedColor(overrides[field], `--${field}`);
  }
  if (!result.fontSize || /[,\r\n]/.test(result.font)) throw new Error("font and font size are invalid for ASS");
  return result;
}

function styleRow(name, { font, fontSize, primary, secondary, style }) {
  if (/[,\r\n]/.test(font)) throw new Error(`font name "${font}" cannot be used in an ASS style row`);
  return `Style: ${name},${font},${fontSize},${primary},${secondary},${style.outline},${style.back},-1,0,0,0,100,100,0,0,${style.borderStyle},${style.outlineWidth},${style.shadow},2,120,120,${style.marginV},1`;
}

export function buildAss(segments, { title, style, layout = "source-only", translationFont, sourceFont }) {
  if (/[\r\n]/.test(title)) throw new Error("title must not contain line breaks");
  const bilingual = layout !== "source-only";
  if (bilingual && !translationFont) throw new Error("bilingual layout requires a translation font");
  const sourceOnTop = layout === "source-top";
  const secondary = Math.max(1, Math.round(style.fontSize * SECONDARY_SCALE));

  const styles = [
    styleRow("Karaoke", {
      font: sourceFont ?? style.font,
      fontSize: bilingual && !sourceOnTop ? secondary : style.fontSize,
      primary: style.primary,
      secondary: style.secondary,
      style,
    }),
  ];
  if (bilingual) {
    // Both colours are the plain fill: the translation carries no \k tags, and a line
    // that outlives the sweep would otherwise flip to the highlight colour at the end.
    styles.push(
      styleRow("Translation", {
        font: translationFont,
        fontSize: sourceOnTop ? secondary : style.fontSize,
        primary: "&H00FFFFFF",
        secondary: "&H00FFFFFF",
        style,
      }),
    );
  }

  const header = `[Script Info]\n; Generated directly from EdgeSpeak word timestamps.\nTitle: ${title}\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 0\nScaledBorderAndShadow: yes\nYCbCr Matrix: TV.709\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n${styles.join("\n")}\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n`;

  const events = segments.map((segment) => {
    const timing = `${assTime(Number(segment.start))},${assTime(Number(segment.end))}`;
    if (!bilingual) {
      return `Dialogue: 0,${timing},Karaoke,,0,0,0,karaoke,${karaokeText(segment)}`;
    }
    // \r switches style mid-event so one Dialogue holds both lines; ASS then stacks them
    // as a single block off the shared margin, which separate events would not do.
    const source = `{\\rKaraoke}${karaokeText(segment)}`;
    const translation = `{\\rTranslation}${escapeAss(String(segment.translation).trim())}`;
    const [first, second] = sourceOnTop ? [source, translation] : [translation, source];
    // The event's own style governs margins and alignment for the whole block.
    const base = sourceOnTop ? "Karaoke" : "Translation";
    return `Dialogue: 0,${timing},${base},,0,0,0,karaoke,${first}\\N${second}`;
  });
  return `${header}${events.join("\n")}\n`;
}

function filterPath(path) {
  return `ass=filename='${path.replaceAll("\\", "\\\\").replaceAll(":", "\\:").replaceAll("'", "\\'")}'`;
}

function renderPreviews({ segments, transcriptPath, media, previewDir, at, title, layout, translationFont, sourceFont, overwrite }) {
  if (!existsSync(media)) throw new Error(`preview media not found: ${media}`);
  mkdirSync(previewDir, { recursive: true });
  const cue = segments.find((segment) => at === undefined || (at >= Number(segment.start) && at <= Number(segment.end))) ?? segments[0];
  const timestamp = at === undefined ? (Number(cue.start) + Number(cue.end)) / 2 : number(at, "--preview-at");
  const previews = [];
  for (const name of Object.keys(STYLES)) {
    const assPath = resolve(previewDir, `${name}.ass`);
    const imagePath = resolve(previewDir, `${name}.png`);
    if (!overwrite && (existsSync(assPath) || existsSync(imagePath))) throw new Error(`preview exists; pass --overwrite: ${imagePath}`);
    writeFileSync(assPath, buildAss(segments, { title, style: resolveStyle(name), layout, translationFont, sourceFont }), "utf8");
    // Keep original presentation timestamps for both the subtitle renderer and frame selector.
    // Seeking around an inter-frame codec can otherwise corrupt the first decoded preview frame.
    const previewFilter = `${filterPath(assPath)},select='gte(t,${timestamp})'`;
    execFileSync("ffmpeg", [overwrite ? "-y" : "-n", "-hide_banner", "-loglevel", "error", "-i", media, "-vf", previewFilter, "-frames:v", "1", "-update", "1", imagePath], { stdio: "inherit" });
    previews.push({ style: name, description: STYLES[name].description, image: imagePath });
  }
  return { transcript: transcriptPath, timestamp, previews };
}

function usage() {
  return `Usage:\n  node karaoke-ass.mjs <transcript.json> [-o output.ass] [--style classic]\n  node karaoke-ass.mjs --list-styles\n\nOptions:\n  --preview-media <video>   Render every preset on a real source frame\n  --preview-dir <dir>       Preview destination (default: <output>.previews)\n  --preview-at <seconds>    Frame time; defaults to the midpoint of the first cue\n  --layout <name>           translation-top (default when the transcript carries\n                            translations), source-top, or source-only\n  --translation-font <name> Font for the translation line; auto-selected per script\n  --font/--font-size/--margin-v and --primary/--secondary/--outline/--back override a preset\n  --overwrite               Replace existing output and preview files`;
}

const LAYOUTS = ["translation-top", "source-top", "source-only"];

// Bilingual is the default the moment a transcript carries translations: producing a
// source-only file from a translated transcript silently drops half of what was asked for.
function resolveLayout(requested, translated) {
  if (requested === undefined) return translated ? "translation-top" : "source-only";
  if (!LAYOUTS.includes(requested)) throw new Error(`--layout must be one of ${LAYOUTS.join(", ")}`);
  if (requested !== "source-only" && !translated) {
    throw new Error(`--layout ${requested} needs segments[].translation; the transcript has none`);
  }
  return requested;
}

function main() {
  try {
    const args = parseArgs(process.argv.slice(2));
    if (args.list_styles) {
      console.log(JSON.stringify(STYLES, null, 2));
      return;
    }
    if (!args.input) throw new Error(usage());
    const input = resolve(args.input);
    const inputExtension = extname(input);
    const inputStem = inputExtension ? input.slice(0, -inputExtension.length) : input;
    const output = resolve(args.output ?? `${inputStem}.karaoke.ass`);
    if (!existsSync(input)) throw new Error(`input not found: ${input}`);
    if (existsSync(output) && !args.overwrite) throw new Error(`output exists; pass --overwrite: ${output}`);
    const { segments, wordCount, translated } = loadTranscript(input);
    const style = resolveStyle(args.style, args);
    const layout = resolveLayout(args.layout, translated);

    let translationFont;
    let font;
    if (layout !== "source-only") {
      font = resolveTranslationFont(segments.map((segment) => segment.translation).join(""), {
        requested: args.translation_font,
        fallback: style.font,
      });
      translationFont = font.font;
    }
    // The source line needs the same treatment: every preset ships a Latin font, so a CJK
    // transcript would burn as blank boxes unless the script picks a font that covers it.
    const source = resolveTranslationFont(segments.map((segment) => segment.text).join(""), {
      requested: args.font,
      fallback: style.font,
      line: "source text",
      flag: "--font",
    });
    const sourceFont = source.font;

    mkdirSync(dirname(output), { recursive: true });
    writeFileSync(output, buildAss(segments, { title: args.title, style, layout, translationFont, sourceFont }), "utf8");
    const summary = { output, style: args.style, layout, segments: segments.length, words: wordCount };
    if (source.lang) {
      summary.source_font = source.font;
      summary.source_script = source.lang;
      if (!source.verified) summary.source_font_verified = false;
    }
    if (font) {
      summary.translation_font = font.font;
      summary.translation_script = font.lang ?? "latin";
      // Say so out loud rather than implying the glyph coverage was checked.
      if (!font.verified) summary.translation_font_verified = false;
    }
    if (args.preview_media) {
      summary.preview = renderPreviews({
        segments,
        transcriptPath: input,
        media: resolve(args.preview_media),
        previewDir: resolve(args.preview_dir ?? `${output.slice(0, -4)}.previews`),
        at: args.preview_at === undefined ? undefined : Number(args.preview_at),
        title: args.title,
        layout,
        translationFont,
        sourceFont,
        overwrite: Boolean(args.overwrite),
      });
    }
    console.log(JSON.stringify(summary, null, 2));
  } catch (error) {
    fail(error instanceof Error ? error.message : String(error));
  }
}

// Compare real paths on both sides: Node resolves import.meta.url through symlinks
// but leaves process.argv[1] as the caller typed it, so a plain string compare makes
// a symlinked invocation (the `.claude/skills/...` path SKILL.md documents, a
// node_modules link, /tmp on macOS) silently skip main() and exit 0.
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
