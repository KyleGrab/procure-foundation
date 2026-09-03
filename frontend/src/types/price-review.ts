export interface PriceReview {
  public_id: string;
  supplier_public_id: string;
  status: string;
  effective_date: string | null;
  currency: string;
  price_basis: string;
  completed_at: string | null;
}

export interface PriceReviewLine {
  public_id: string;
  old_supplier_sku: string | null;
  old_description: string | null;
  old_pack_raw: string | null;
  old_price: string | null;
  new_supplier_sku: string | null;
  new_description: string | null;
  new_pack_raw: string | null;
  new_price: string | null;
  match_status: string;
  match_confidence: string | null;
  movement_type: string | null;
  percentage_change: string | null;
  annual_impact: string | null;
  risk_classification: string | null;
  buyer_decision: string | null;
  target_price: string | null;
  potential_cost_avoidance: string | null;
}

export interface SupplierSummary {
  total_previous_skus: number;
  total_new_skus: number;
  matched_skus: number;
  new_skus: number;
  discontinued_skus: number;
  increasing_skus: number;
  decreasing_skus: number;
  unchanged_skus: number;
  pack_changes: number;
  weighted_average_price_increase_pct: string | null;
  annual_cost_impact: string;
  products_requiring_manual_review: number;
}
