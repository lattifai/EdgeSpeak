#!/usr/bin/env node

import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, realpathSync } from "node:fs";
import { dirname, extname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const CONTAINERS = Object.freeze({
  ".mp4": { extension: ".mp4", video: "libx264", expectedVideo: "h264", audio: "aac", crf: 21, extra: ["-pix_fmt", "yuv420p", "-movflags", "+faststart"] },
  ".m4v": { extension: ".m4v", video: "libx264", expectedVideo: "h264", audio: "aac", crf: 21, extra: ["-pix_fmt", "yuv420p", "-movflags", "+faststart"] },
  ".mov": { extension: ".mov", video: "libx264", expectedVideo: "h264", audio: "aac", crf: 21, extra: ["-pix_fmt", "yuv420p", "-movflags", "+faststart"] },
  ".mkv": { extension: ".mkv", video: "libx264", expectedVideo: "h264", audio: "copy", crf: 21, extra: ["-pix_fmt", "yuv420p"] },
  ".webm": { extension: ".webm", video: "libvpx-vp9", expectedVideo: "vp9", audio: "libopus", crf: 31, extra: ["-b:v", "0"] },
  ".ts": { extension: ".ts", video: "libx264", expectedVideo: "h264", audio: "aac", crf: 21, extra: ["-pix_fmt", "yuv420p"] },
  ".m2ts": { extension: ".m2ts", video: "libx264", expectedVideo: "h264", audio: "aac", crf: 21, extra: ["-pix_fmt", "yuv420p"] },
});

// Rough coding efficiency relative to H.264 = 1.0: a higher number means the codec
// reaches comparable perceived quality at a lower bitrate. Used only to size a cap,
// never to predict quality, so approximate values are fine.
const CODEC_EFFICIENCY = Object.freeze({
  mpeg1video: 0.4, mpeg2video: 0.5, mpeg4: 0.6, msmpeg4v3: 0.6, theora: 0.7,
  vp8: 0.9, h264: 1.0, vp9: 1.5, hevc: 1.5, av1: 1.6,
  prores: 0.15, dnxhd: 0.15, ffvhuff: 0.1, huffyuv: 0.1, rawvideo: 0.05,
});

// Hard subtitles force a re-encode, and a fixed CRF ignores what the source shipped
// at: burning CRF 21 into a lean 1.5 Mbps AV1 file produced a 4.2 Mbps H.264 copy,
// 2.8x the source bitrate for no visible gain. Derive a ceiling from the source
// instead, scaled by how much less efficient the output codec is.
export function planBitrateCap({ sourceCodec, sourceBitrate, outputCodec }) {
  const bitrate = Number(sourceBitrate);
  if (!Number.isFinite(bitrate) || bitrate <= 0) return null;
  const from = CODEC_EFFICIENCY[sourceCodec];
  const to = CODEC_EFFICIENCY[outputCodec];
  if (!from || !to) return null;
  const target = Math.round(bitrate * (from / to));
  return {
    source_codec: sourceCodec,
    source_bitrate: bitrate,
    output_codec: outputCodec,
    target_bitrate: target,
    maxrate: Math.round(target * 1.2),
    bufsize: Math.round(target * 2.4),
  };
}

function parseArgs(argv) {
  const options = { format: "source", preset: "medium", audio_bitrate: "192k" };
  const positional = [];
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("-")) { positional.push(token); continue; }
    if (token === "--overwrite") { options.overwrite = true; continue; }
    const key = token === "-o" ? "output" : token.slice(2).replaceAll("-", "_");
    if (!argv[index + 1]) throw new Error(`${token} requires a value`);
    options[key] = argv[index + 1];
    index += 1;
  }
  [options.media, options.subtitles] = positional;
  return options;
}

function probe(path) {
  return JSON.parse(execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration,size,format_name,bit_rate:stream=codec_type,codec_name,width,height,bit_rate", "-of", "json", path], { encoding: "utf8" }));
}

function filterPath(path) {
  return `ass=filename='${path.replaceAll("\\", "\\\\").replaceAll(":", "\\:").replaceAll("'", "\\'")}'`;
}

function selectProfile(media, output, format) {
  if (output) {
    const extension = extname(output).toLowerCase();
    if (!CONTAINERS[extension]) throw new Error(`unsupported output extension: ${extension}`);
    return { profile: CONTAINERS[extension], fallback: false };
  }
  const requested = format === "source" ? extname(media).toLowerCase() : `.${format.toLowerCase()}`;
  if (CONTAINERS[requested]) return { profile: CONTAINERS[requested], fallback: false };
  if (format !== "source") throw new Error(`unsupported --format: ${format}`);
  return { profile: CONTAINERS[".mkv"], fallback: true };
}

function main() {
  try {
    const args = parseArgs(process.argv.slice(2));
    if (!args.media || !args.subtitles) throw new Error("Usage: node render-hardsub.mjs <media> <subtitles.ass> [-o output] [--format source|mp4|mov|mkv|webm] [--overwrite]");
    const media = resolve(args.media);
    const subtitles = resolve(args.subtitles);
    if (!existsSync(media)) throw new Error(`media not found: ${media}`);
    if (!existsSync(subtitles)) throw new Error(`subtitles not found: ${subtitles}`);
    const selection = selectProfile(media, args.output, args.format);
    const sourceExtension = extname(media);
    const stem = sourceExtension ? media.slice(0, -sourceExtension.length) : media;
    const output = resolve(args.output ?? `${stem}.karaoke.hardsub${selection.profile.extension}`);
    if (output === media) throw new Error("output must differ from source media");
    if (existsSync(output) && !args.overwrite) throw new Error(`output exists; pass --overwrite: ${output}`);
    const source = probe(media);
    const sourceVideos = source.streams.filter((stream) => stream.codec_type === "video");
    const sourceAudios = source.streams.filter((stream) => stream.codec_type === "audio");
    if (sourceVideos.length !== 1) throw new Error("hard subtitles require exactly one source video stream");
    const crf = args.crf === undefined ? selection.profile.crf : Number(args.crf);
    if (!Number.isInteger(crf) || crf < 0 || crf > 63) throw new Error("--crf must be an integer in [0, 63]");
    // Match the source bitrate by default; an explicit --maxrate (or --maxrate none)
    // means the caller has already decided and we stay out of the way. Only x264 gets
    // a cap: VP9's rate control reads -b:v/-maxrate differently and the .webm profile
    // deliberately pins -b:v 0 for constant-quality mode.
    const capable = selection.profile.video === "libx264";
    const plan = capable && args.maxrate === undefined
      ? planBitrateCap({ sourceCodec: sourceVideos[0].codec_name, sourceBitrate: sourceVideos[0].bit_rate, outputCodec: selection.profile.expectedVideo })
      : null;
    mkdirSync(dirname(output), { recursive: true });
    const command = [args.overwrite ? "-y" : "-n", "-hide_banner", "-i", media, "-map", "0:v:0", "-map", "0:a?", "-map_metadata", "0", "-map_chapters", "0", "-vf", filterPath(subtitles), "-c:v", selection.profile.video];
    if (selection.profile.video === "libx264") command.push("-preset", args.preset);
    command.push("-crf", String(crf));
    if (plan) command.push("-maxrate:v", String(plan.maxrate), "-bufsize:v", String(plan.bufsize));
    else if (capable && args.maxrate !== undefined && args.maxrate !== "none") command.push("-maxrate:v", args.maxrate, "-bufsize:v", args.maxrate);
    command.push(...selection.profile.extra, "-c:a", selection.profile.audio);
    if (selection.profile.audio !== "copy") command.push("-b:a", args.audio_bitrate);
    command.push(output);
    const run = spawnSync("ffmpeg", command, { stdio: "inherit" });
    if (run.error) throw run.error;
    if (run.status !== 0) throw new Error(`ffmpeg failed with exit code ${run.status}`);
    const result = probe(output);
    const videos = result.streams.filter((stream) => stream.codec_type === "video");
    const audios = result.streams.filter((stream) => stream.codec_type === "audio");
    const subtitlesStreams = result.streams.filter((stream) => stream.codec_type === "subtitle");
    if (videos.length !== 1 || videos[0].codec_name !== selection.profile.expectedVideo) throw new Error("validation failed: unexpected output video codec");
    if (subtitlesStreams.length !== 0) throw new Error("validation failed: hard-subbed output contains a subtitle stream");
    if (audios.length !== sourceAudios.length) throw new Error("validation failed: audio stream count changed");
    const duration = Number(result.format.duration);
    if (Math.abs(duration - Number(source.format.duration)) > 0.35) throw new Error("validation failed: output duration differs from source");
    console.log(JSON.stringify({ output, source_extension: sourceExtension, output_extension: selection.profile.extension, container_fallback: selection.fallback, duration, size: Number(result.format.size), video_codec: videos[0].codec_name, video_bitrate: Number(videos[0].bit_rate) || null, source_video_bitrate: Number(sourceVideos[0].bit_rate) || null, bitrate_cap: plan, audio_codecs: audios.map((stream) => stream.codec_name), subtitle_streams: 0 }, null, 2));
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}

// Same symlink-safe guard as karaoke-ass.mjs: this module exports planBitrateCap, so
// importing it must not shell out to ffmpeg, and a symlinked invocation must still run.
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
