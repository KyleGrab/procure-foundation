/**
 * FX exposure network client. Follows dashboard-api.ts's real, established pattern
 * (apiFetch<T> + authHeaders()) rather than inventing a new fetch wrapper. Maps to the real
 * backend route POST /treasury/calculate-exposure (backend/app/api/v1/treasury.py, built and
 * syntax-checked this engagement; not run, same standing sandbox limitation as every backend
 * route - no live Postgres, no running FastAPI server).
 *
 * Pure display/formatting logic lives in treasury-display.ts, not here - this file is the one
 * and only place network/auth concerns exist for this domain.
 */
import { apiFetch } from "./api";
import { authHeaders } from "./dashboard-api";
import type { FxExposureResult } from "./treasury-display";

export interface FxExposureRequest {
  transactionDate: string;
  reportingDate: string;
  customerId?: string;
  currencyCode: string;
  foreignCurrencyAmount: number;
  transactionDateSpotRate: number;
  reportingDateSpotRate: number;
  fecContractRate?: number;
}

export const treasuryApi = {
  calculateExposure: (payload: FxExposureRequest) =>
    apiFetch<FxExposureResult>("/treasury/calculate-exposure", {
      method: "POST",
      body: JSON.stringify({
        transaction_date: payload.transactionDate, reporting_date: payload.reportingDate,
        customer_id: payload.customerId ?? null, currency_code: payload.currencyCode,
        foreign_currency_amount: payload.foreignCurrencyAmount,
        transaction_date_spot_rate: payload.transactionDateSpotRate,
        reporting_date_spot_rate: payload.reportingDateSpotRate,
        fec_contract_rate: payload.fecContractRate ?? null,
      }),
      ...authHeaders(),
    }),
};

export type { FxExposureResult, FxDisplayState } from "./treasury-display";
export { resolveFxDisplayState, formatZARPrecise } from "./treasury-display";
