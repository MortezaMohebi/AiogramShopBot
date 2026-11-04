/** Safe per-Store and per-Bot customer menu/checkout configuration. */

export type CustomerMenuAction =
  | "shop" | "search" | "cart" | "orders" | "account" | "support";

export interface CustomerMenuPolicy {
  scope: "store" | "bot";
  store_id: string;
  bot_id: string | null;
  version: number;
  inherited: boolean;
  actions: CustomerMenuAction[];
  available_actions: {
    key: CustomerMenuAction;
    label: string;
    callback: string;
  }[];
}

export interface CheckoutPolicy {
  store_id: string;
  bot_id: string | null;
  version: number;
  mode: "manual" | "instant";
  mode_override: "manual" | "instant" | null;
  terms_version: string;
  terms_text: string;
  terms_ready: boolean;
}

export interface SupportTicketSummary {
  id: number;
  store_id: string;
  customer_id: number;
  bot_id: string;
  topic: string;
  status: string;
  version: number;
  created_at: string;
}

export interface SupportTicketDetails extends SupportTicketSummary {
  messages: {
    id: number;
    sender_kind: "customer" | "staff" | "system";
    body: string;
    created_at: string;
  }[];
}

export interface ShipmentRecord {
  order_id: number;
  store_id: string;
  total_irr: string;
  status: string;
  kind: "physical" | "digital" | null;
  version: number;
  carrier: string | null;
  tracking_code: string | null;
}
