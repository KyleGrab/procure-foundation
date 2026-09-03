import { test } from "node:test";
import assert from "node:assert/strict";
import { shouldShowDevDemoLogin } from "./dev-demo-guard.ts";

test("shows the dev demo button when NODE_ENV is exactly 'development'", () => {
  assert.strictEqual(shouldShowDevDemoLogin("development"), true);
});

test("hides it when NODE_ENV is 'production' - the case that matters most", () => {
  assert.strictEqual(shouldShowDevDemoLogin("production"), false);
});

test("hides it when NODE_ENV is 'test'", () => {
  assert.strictEqual(shouldShowDevDemoLogin("test"), false);
});

test("hides it when NODE_ENV is undefined - never shows by default/absence of a value", () => {
  assert.strictEqual(shouldShowDevDemoLogin(undefined), false);
});

test("hides it for any near-miss string - no partial or case-insensitive match", () => {
  // A guard this security-sensitive must not accidentally match "Development", "DEV", or a
  // typo'd value - exact string equality only.
  assert.strictEqual(shouldShowDevDemoLogin("Development"), false);
  assert.strictEqual(shouldShowDevDemoLogin("dev"), false);
  assert.strictEqual(shouldShowDevDemoLogin(""), false);
});
