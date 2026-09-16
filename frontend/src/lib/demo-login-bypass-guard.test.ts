import { test } from "node:test";
import assert from "node:assert/strict";
import { shouldShowDemoLoginBypass } from "./demo-login-bypass-guard.ts";

test("visible only when both development AND the explicit flag are true together", () => {
  assert.strictEqual(shouldShowDemoLoginBypass("development", "true"), true);
});

test("hidden in local development with no flag set - dev alone is not enough", () => {
  assert.strictEqual(shouldShowDemoLoginBypass("development", undefined), false);
  assert.strictEqual(shouldShowDemoLoginBypass("development", "false"), false);
});

test("hidden with the flag set but NODE_ENV not exactly 'development' - the flag alone is not enough, even in a real production build", () => {
  assert.strictEqual(shouldShowDemoLoginBypass("production", "true"), false);
  assert.strictEqual(shouldShowDemoLoginBypass(undefined, "true"), false);
  assert.strictEqual(shouldShowDemoLoginBypass("test", "true"), false);
});

test("hidden when both are unset or false - the default, most important case", () => {
  assert.strictEqual(shouldShowDemoLoginBypass(undefined, undefined), false);
  assert.strictEqual(shouldShowDemoLoginBypass("production", undefined), false);
});

test("does not match a near-miss or differently-cased value on either side - exact string only", () => {
  assert.strictEqual(shouldShowDemoLoginBypass("Development", "true"), false);
  assert.strictEqual(shouldShowDemoLoginBypass("development", "True"), false);
  assert.strictEqual(shouldShowDemoLoginBypass("development", "TRUE"), false);
  assert.strictEqual(shouldShowDemoLoginBypass("development", "1"), false);
});
