import { test } from "node:test";
import assert from "node:assert/strict";
import { shouldShowRegistrationLink } from "./registration-guard.ts";

test("shows the registration link by default when the env var is unset - production unchanged", () => {
  assert.strictEqual(shouldShowRegistrationLink(undefined), true);
});

test("shows it for any value other than the exact string 'false'", () => {
  assert.strictEqual(shouldShowRegistrationLink("true"), true);
  assert.strictEqual(shouldShowRegistrationLink(""), true);
});

test("hides it only for the exact string 'false' - the one deliberate opt-out", () => {
  assert.strictEqual(shouldShowRegistrationLink("false"), false);
});

test("does not match a near-miss or differently-cased value - exact string only", () => {
  // Same discipline as shouldShowDevDemoLogin - a security-relevant guard must not silently
  // treat "False"/"FALSE"/"no" as if they meant "false". An operator who mistypes this should
  // get the safe (link visible, backend 403 still the real control) outcome, not a silent one.
  assert.strictEqual(shouldShowRegistrationLink("False"), true);
  assert.strictEqual(shouldShowRegistrationLink("FALSE"), true);
  assert.strictEqual(shouldShowRegistrationLink("no"), true);
});
