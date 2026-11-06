/** Public native administration projections contain no credentials or proofs. */
export interface McpGrantView {
  id: string;
  version: number;
  store_ids: string[];
  scopes: string[];
  revoked: boolean;
  expires_at: string;
  expired: boolean;
  can_revoke: boolean;
  gateway: { issuer: string; client_id: string; connection_id: string; workspace_id: string };
}
export interface McpPage {
  actor_id: number;
  store_id: string;
  items: McpGrantView[];
  page: number;
  has_more: boolean;
  approval_authority: "wpmcp";
  scopes: string[];
  enabled: boolean;
}
export interface McpPairingView {
  id: string;
  identity: { iss: string; sub: string; client_id: string; tenant_id: string; workspace_id: string;
    connection_id: string; grant_id: string; grant_version: number; aud: string };
  store_ids: string[];
  scopes: string[];
  expires_at: string;
  expired: boolean;
  confirmed: boolean;
  can_confirm: boolean;
  approval_authority: "wpmcp";
}
export interface McpHistoryPage {
  store_id: string;
  page: number;
  has_more: boolean;
  items: { operation_id: string; grant_id: string; tool: string;
    state: "pending" | "succeeded" | "awaiting_gateway" | "cancelled"; created_at: string }[];
}
