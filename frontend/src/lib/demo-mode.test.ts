import { test } from "node:test";
import assert from "node:assert/strict";
import { isDemoModeEnabled } from "./demo-mode.ts";

test("visible in local development regardless of the demo-mode flag", () => {
  assert.strictEqual(isDemoModeEnabled("development", undefined), true);
  assert.strictEqual(isDemoModeEnabled("development", "false"), true);
});

test("visible when the demo-mode flag is exactly 'true', even outside development", () => {
  assert.strictEqual(isDemoModeEnabled("production", "true"), true);
  assert.strictEqual(isDemoModeEnabled(undefined, "true"), true);
});

test("hidden in production with no flag set - the default, most important case", () => {
  assert.strictEqual(isDemoModeEnabled("production", undefined), false);
});

test("hidden when both inputs are undefined", () => {
  assert.strictEqual(isDemoModeEnabled(undefined, undefined), false);
});

test("does not match a near-miss or differently-cased flag value - exact string only", () => {
  // Same discipline as the other visibility guards in this codebase: an operator who mistypes
  // this should get the safe (hidden) outcome, never a silent accidental production exposure.
  assert.strictEqual(isDemoModeEnabled("production", "True"), false);
  assert.strictEqual(isDemoModeEnabled("production", "TRUE"), false);
  assert.strictEqual(isDemoModeEnabled("production", "1"), false);
  assert.strictEqual(isDemoModeEnabled("production", "yes"), false);
});
