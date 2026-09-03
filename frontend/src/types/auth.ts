export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface MembershipSummary {
  organisation_public_id: string;
  organisation_name: string;
  role: string;
  status: string;
}

export interface CurrentUser {
  public_id: string;
  first_name: string;
  last_name: string;
  email: string;
  memberships: MembershipSummary[];
}
