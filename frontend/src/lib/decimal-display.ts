/**
 * Decimal-safe display formatting for the illustrative Price Review demo (see
 * price-review-demo-data.ts). Deliberately zero imports, same "pure logic separated from
 * presentation" boundary this codebase already applies on the backend (spec §2.1) and in
 * treasury-display.ts on the frontend.
 *
 * Every value in and out is a string (or null) - the exact Decimal string the backend's wire
 * types already use (types/price-review.ts's `string | null` fields). Nothing here ever runs a
 * value through `Number()` or `parseFloat()` before rendering it: JS binary floating point can't
 * represent most decimal fractions exactly (0.1 + 0.2 !== 0.3), and this is money and percentage
 * data. All arithmetic below is plain string/digit manipulation instead.
 *
 * Unknown values (null) always render as the em dash "—" - never "0", "R0", or "0%". A value that
 * is genuinely, knowably zero (e.g. an unchanged price) is not unknown and renders as the real
 * zero it is; the two are deliberately kept distinguishable rather than collapsed into one blank
 * state.
 */

const UNKNOWN = "—";

/** Inserts thousands separators into a decimal string's integer part only, via string
 * manipulation - no Number()/toLocaleString(), which would round or silently drop a trailing
 * zero a Decimal string is entitled to keep (e.g. "96330.00" must stay "96,330.00", not become
 * "96,330"). */
export function insertThousandsSeparators(value: string): string {
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [intPart, fracPart] = unsigned.split(".");
  const withCommas = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return (negative ? "-" : "") + withCommas + (fracPart !== undefined ? `.${fracPart}` : "");
}

/** Renders a Decimal-string currency amount exactly as received (thousands-separated, every
 * digit preserved) or "—" when the value is unknown. */
export function formatDecimalCurrency(value: string | null, symbol = "R"): string {
  if (value === null) return UNKNOWN;
  return `${symbol}${insertThousandsSeparators(value)}`;
}

/** Multiplies a Decimal string by 10^exponent using digit manipulation only - used to convert a
 * stored fraction (e.g. "0.083") into the percentage points a human reads (e.g. "8.3"). Handles
 * a leading sign and shifting the decimal point in either direction without ever parsing to a
 * binary float. */
export function multiplyDecimalStringByPowerOfTen(value: string, exponent: number): string {
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [intPart, fracPart = ""] = unsigned.split(".");
  const digits = intPart + fracPart;
  const fracDigitsAfterShift = fracPart.length - exponent;

  let result: string;
  if (fracDigitsAfterShift <= 0) {
    result = digits + "0".repeat(-fracDigitsAfterShift);
  } else {
    const splitAt = digits.length - fracDigitsAfterShift;
    const left = digits.slice(0, splitAt) || "0";
    const right = digits.slice(splitAt);
    result = `${left}.${right}`;
  }

  result = result.replace(/^0+(?=\d)/, "");
  return negative && result !== "0" && !/^0\.0*$/.test(result) ? `-${result}` : result;
}

/** Renders a Decimal-string fraction (e.g. "0.083" meaning 8.3%) as a percentage, or "—" when
 * the value is unknown. Truncates (never rounds) to `fractionDigits` places after the shift -
 * callers should supply values already precise enough that this is lossless (this demo's data
 * is curated to exactly that precision; see price-review-demo-data.ts). Truncation was chosen
 * over string-based rounding deliberately: rounding correctly without floats means implementing
 * carry-propagation by hand, which is real complexity to add and re-verify for a codepath whose
 * only caller controls its own input precision - not worth the added surface here. */
export function formatDecimalPercent(value: string | null, fractionDigits = 1): string {
  if (value === null) return UNKNOWN;
  const points = multiplyDecimalStringByPowerOfTen(value, 2);
  const [intPart, fracPart = ""] = points.split(".");
  const paddedFrac = (fracPart + "0".repeat(fractionDigits)).slice(0, fractionDigits);
  const rendered = fractionDigits > 0 ? `${intPart}.${paddedFrac}` : intPart;
  return `${rendered}%`;
}

/** Renders any other unknown-capable string field, or "—" when null. Never coerces null to an
 * empty string, "0", or any other value that could be mistaken for real data. */
export function formatDecimalOrUnknown(value: string | null): string {
  return value === null ? UNKNOWN : value;
}
