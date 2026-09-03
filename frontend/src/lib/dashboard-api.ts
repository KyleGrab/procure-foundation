/**
 * Typed API client for the dashboard. Every function here maps to a real, built backend route
 * (backend/app/api/v1/spend_analytics.py, opportunities.py, savings_register.py, ai_copilot.py -
 * all built and syntax-checked this session, none of them ever actually run since this sandbox
 * has no network to npm install or start a Postgres/FastAPI server). Extends
 * src/lib/api.ts's apiFetch (Phase 1) rather than duplicating the fetch/auth-header logic.
 */
import { apiFetch } from "./api";

export function formatZAR(amount: number): string {
  return new Intl.NumberFormat("en-ZA", {
    style: "currency",
    currency: "ZAR",
    maximumFractionDigits: 0,
  }).format(amount);
}

export interface SpendItem {
  key: string;
  label: string;
  amount: string; // Decimal serialized as string by the backend - never parsed to float for
  // display math client-side; formatZAR(Number(amount)) is for *display* rounding only, the
  // authoritative figure stays the string the backend computed with Decimal.
}

export interface MonthOverMonthPoint {
  month: string;
  amount: string;
  change_pct: string | null;
}

export interface TopPriceIncrease {
  supplier: string;
  product: string | null;
  percentage_change: string | null;
  annual_impact: string | null;
  risk_classification: string | null;
}

export interface ABCResult {
  item: SpendItem;
  cumulative_pct: string;
  classification: "A" | "B" | "C";
}

export interface ParetoResult {
  contributors: SpendItem[];
  contributor_count: number;
  total_item_count: number;
  cumulative_pct_covered: string;
}

export interface Opportunity {
  public_id: string;
  title: string;
  opportunity_type: string;
  supplier_public_id: string | null;
  description: string | null;
  annual_financial_impact: string | null;
  annual_financial_impact_status: string;
  annual_financial_impact_source_basis: string | null;
  annual_financial_impact_effective_from: string | null;
  savings_type: string | null;
  baseline_value: string | null;
  baseline_methodology: string | null;
  confidence: "low" | "medium" | "high" | null;
  realised_savings: string | null;
  realised_savings_status: string;
  realised_savings_source_basis: string | null;
  realised_savings_effective_period_start: string | null;
  realised_savings_effective_period_end: string | null;
  status: string;
  approved_at: string | null;
}

export interface SavingsWaterfall {
  identified: string;
  validated: string;
  approved: string;
  implementation: string;
  realised: string;
  excluded_count: number;
  excluded_reason_breakdown: { unknown: number; legacy_unverified: number };
}

export interface CopilotQueryResponse {
  intent: string;
  structured_result: Record<string, unknown>;
  summary: string;
  missing_data_notes: string[];
}

export interface GraphNode {
  id: string;
  label: string;
  node_type: string;
  source: string;
  metadata: Record<string, unknown>;
}

export interface GraphEdge {
  source_id: string;
  target_id: string;
  weight: string;
  status: string;
  source: string;
  similarity_score: string;
  combined_spend: string | null;
  match_method: string;
  description_a: string;
  description_b: string;
  flag_public_id: string;
}

export interface DomainGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export function authHeaders(): { accessToken?: string } {
  // Matches the existing pattern in app/login/page.tsx and app/register/page.tsx (Phase 1) for
  // consistency - but worth flagging plainly: lib/api.ts's own header comment says the access
  // token should live in memory and "never localStorage," and sessionStorage carries the same
  // XSS-readability exposure that comment is warning about (any JS on the page can read it,
  // same as localStorage - the only difference is sessionStorage clears at tab close). This is a
  // pre-existing inconsistency from Phase 1, not introduced here - flagged rather than silently
  // propagated further. Fixing it means moving token storage to a React context/provider across
  // login, register, and every page that calls an authenticated endpoint, which is a real
  // refactor out of scope for this dashboard build - noted for a future security-hardening pass,
  // the same way ADR-011 flagged and then fixed the RLS gap once someone had reason to look.
  const token = typeof window !== "undefined" ? sessionStorage.getItem("procureiq_access_token") : null;
  return token ? { accessToken: token } : {};
}

export const spendAnalyticsApi = {
  bySupplier: () => apiFetch<SpendItem[]>("/spend-analytics/by-supplier", authHeaders()),
  bySku: (supplierPublicId?: string) =>
    apiFetch<SpendItem[]>(
      `/spend-analytics/by-sku${supplierPublicId ? `?supplier_public_id=${supplierPublicId}` : ""}`,
      authHeaders(),
    ),
  abcClassification: () => apiFetch<ABCResult[]>("/spend-analytics/abc-classification", authHeaders()),
  pareto: () => apiFetch<ParetoResult>("/spend-analytics/pareto", authHeaders()),
  trend: () => apiFetch<MonthOverMonthPoint[]>("/spend-analytics/trend", authHeaders()),
  topPriceIncreases: (limit = 10) =>
    apiFetch<TopPriceIncrease[]>(`/spend-analytics/top-price-increases?limit=${limit}`, authHeaders()),
  priceVariance: (supplierPublicId: string, skuOrDescription: string) =>
    apiFetch(
      `/spend-analytics/price-variance/${supplierPublicId}?sku_or_description=${encodeURIComponent(skuOrDescription)}`,
      authHeaders(),
    ),
};

export const opportunitiesApi = {
  list: (params?: { savings_type?: string; status?: string }) => {
    const query = new URLSearchParams(params as Record<string, string>).toString();
    return apiFetch<Opportunity[]>(`/opportunities${query ? `?${query}` : ""}`, authHeaders());
  },
  create: (payload: Partial<Opportunity>) =>
    apiFetch<Opportunity>("/opportunities", { method: "POST", body: JSON.stringify(payload), ...authHeaders() }),
  advance: (publicId: string, targetStatus: string) =>
    apiFetch<Opportunity>(`/opportunities/${publicId}/advance?target_status=${targetStatus}`, {
      method: "POST", ...authHeaders(),
    }),
  duplicateSkuFlags: (status?: string) =>
    apiFetch(`/opportunities/duplicate-sku-flags${status ? `?status=${status}` : ""}`, authHeaders()),
  reviewDuplicateSkuFlag: (publicId: string, confirmed: boolean) =>
    apiFetch(`/opportunities/duplicate-sku-flags/${publicId}/review?confirmed=${confirmed}`, {
      method: "POST", ...authHeaders(),
    }),
  consolidationFlags: (status?: string) =>
    apiFetch(`/opportunities/consolidation-flags${status ? `?status=${status}` : ""}`, authHeaders()),
  consolidationGraph: () =>
    apiFetch<DomainGraph>("/opportunities/consolidation-graph", authHeaders()),
  reviewConsolidationFlag: (publicId: string, action: "mark_under_review" | "recommend_consolidation" | "reject", notes?: string) =>
    apiFetch<{ public_id: string; status: string; review_notes: string | null; reviewed_at: string | null }>(
      `/opportunities/consolidation-flags/${publicId}/review`,
      { method: "POST", body: JSON.stringify({ action, notes: notes ?? null }), ...authHeaders() },
    ),
};

export const savingsRegisterApi = {
  list: (savingsType?: string) =>
    apiFetch<Opportunity[]>(`/savings-register${savingsType ? `?savings_type=${savingsType}` : ""}`, authHeaders()),
  waterfall: () => apiFetch<SavingsWaterfall>("/savings-register/waterfall", authHeaders()),
};

export interface ExecutiveMetrics {
  active_contracts: number;
  open_rebate_periods: number;
  open_consolidation_flags: number;
}

export const dashboardApi = {
  executiveMetrics: () => apiFetch<ExecutiveMetrics>("/dashboard/executive-metrics", authHeaders()),
};

export const aiCopilotApi = {
  query: (question: string) =>
    apiFetch<CopilotQueryResponse>("/ai/query", {
      method: "POST", body: JSON.stringify({ question }), ...authHeaders(),
    }),
  negotiationBrief: (supplierPublicId: string) =>
    apiFetch(`/ai/negotiation-brief?supplier_public_id=${supplierPublicId}`, {
      method: "POST", ...authHeaders(),
    }),
};
