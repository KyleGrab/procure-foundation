import { test } from "node:test";
import assert from "node:assert/strict";
import {
  insertThousandsSeparators,
  multiplyDecimalStringByPowerOfTen,
  formatDecimalCurrency,
  formatDecimalPercent,
  formatDecimalOrUnknown,
} from "./decimal-display.ts";

test("insertThousandsSeparators groups the integer part and preserves every fractional digit exactly", () => {
  assert.strictEqual(insertThousandsSeparators("96330.00"), "96,330.00");
  assert.strictEqual(insertThousandsSeparators("1234.5678"), "1,234.5678");
  assert.strictEqual(insertThousandsSeparators("1000"), "1,000");
  assert.strictEqual(insertThousandsSeparators("125.00"), "125.00");
  assert.strictEqual(insertThousandsSeparators("-2500.5"), "-2,500.5");
});

test("multiplyDecimalStringByPowerOfTen shifts the decimal point without floating point", () => {
  assert.strictEqual(multiplyDecimalStringByPowerOfTen("0.083", 2), "8.3");
  assert.strictEqual(multiplyDecimalStringByPowerOfTen("0.5", 2), "50");
  assert.strictEqual(multiplyDecimalStringByPowerOfTen("-0.015", 2), "-1.5");
  assert.strictEqual(multiplyDecimalStringByPowerOfTen("0", 2), "0");
  assert.strictEqual(multiplyDecimalStringByPowerOfTen("1.5", 2), "150");
});

test("formatDecimalCurrency preserves the exact Decimal string, including trailing zeros", () => {
  assert.strictEqual(formatDecimalCurrency("96330.00"), "R96,330.00");
  assert.strictEqual(formatDecimalCurrency("1234.5678"), "R1,234.5678");
  assert.strictEqual(formatDecimalCurrency("0.00"), "R0.00"); // a real, known zero - not unknown
});

test("formatDecimalCurrency renders null as an em dash, never 0/R0", () => {
  assert.strictEqual(formatDecimalCurrency(null), "—");
});

test("formatDecimalPercent converts a stored fraction to percentage points", () => {
  assert.strictEqual(formatDecimalPercent("0.083"), "8.3%");
  assert.strictEqual(formatDecimalPercent("-0.015"), "-1.5%");
  assert.strictEqual(formatDecimalPercent("0"), "0.0%"); // a real, known zero - not unknown
});

test("formatDecimalPercent renders null as an em dash, never 0%", () => {
  assert.strictEqual(formatDecimalPercent(null), "—");
});

test("formatDecimalOrUnknown passes through real values and maps only null to an em dash", () => {
  assert.strictEqual(formatDecimalOrUnknown("critical"), "critical");
  assert.strictEqual(formatDecimalOrUnknown(""), "");
  assert.strictEqual(formatDecimalOrUnknown(null), "—");
});
