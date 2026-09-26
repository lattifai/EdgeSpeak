// Run with: node --test skills/edgespeak-karaoke/scripts/render-hardsub.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { planBitrateCap } from "./render-hardsub.mjs";

// A hard-subbed copy must be re-encoded, but it should not silently balloon past
// the bitrate the source shipped at. AV1 reaches a given quality at roughly 1.6x
// less bitrate than H.264, so an H.264 copy of an AV1 source needs ~1.6x to look
// equivalent -- and no more.
test("scales the cap by the efficiency gap between source and output codec", () => {
  const plan = planBitrateCap({ sourceCodec: "av1", sourceBitrate: 1482694, outputCodec: "h264" });
  assert.equal(plan.target_bitrate, Math.round(1482694 * 1.6));
  assert.equal(plan.maxrate, Math.round(plan.target_bitrate * 1.2));
  assert.equal(plan.bufsize, Math.round(plan.target_bitrate * 2.4));
});

test("keeps the source bitrate when the codec does not change", () => {
  const plan = planBitrateCap({ sourceCodec: "h264", sourceBitrate: 5_000_000, outputCodec: "h264" });
  assert.equal(plan.target_bitrate, 5_000_000);
});

test("narrows the gap when the output codec is also modern", () => {
  const plan = planBitrateCap({ sourceCodec: "av1", sourceBitrate: 1_000_000, outputCodec: "vp9" });
  assert.equal(plan.target_bitrate, Math.round(1_000_000 * (1.6 / 1.5)));
});

test("allows a much lower cap when the source is an intra-only mezzanine format", () => {
  const plan = planBitrateCap({ sourceCodec: "prores", sourceBitrate: 100_000_000, outputCodec: "h264" });
  assert.ok(plan.target_bitrate < 100_000_000, "ProRes should not dictate a delivery bitrate");
});

// Capping on a guess would be worse than not capping: an unknown codec or a
// container that reports no per-stream bitrate must fall back to plain CRF.
test("returns null when the bitrate cannot be trusted", () => {
  for (const sourceBitrate of [undefined, null, 0, -1, "N/A", Number.NaN]) {
    assert.equal(
      planBitrateCap({ sourceCodec: "av1", sourceBitrate, outputCodec: "h264" }),
      null,
      `expected no cap for bitrate ${String(sourceBitrate)}`,
    );
  }
});

test("returns null for codecs with no known efficiency ratio", () => {
  assert.equal(planBitrateCap({ sourceCodec: "cinepak", sourceBitrate: 1_000_000, outputCodec: "h264" }), null);
  assert.equal(planBitrateCap({ sourceCodec: "av1", sourceBitrate: 1_000_000, outputCodec: "ffv1" }), null);
});

// This module now exports helpers, so it needs the same symlink-safe entry guard
// that karaoke-ass.mjs got: importing it must not shell out to ffmpeg.
test("importing the module does not execute the CLI", () => {
  assert.equal(typeof planBitrateCap, "function");
});
