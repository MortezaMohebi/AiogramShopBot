/** Redacted, strongly scoped StoreCustomer and payment-account contracts. */

export type CartScope = "bot" | "customer";
export type CreditScope = "identity" | "customer";

export interface StoreCommercePolicy {
  store_id: string;
  cart_scope: CartScope;
  credit_scope: CreditScope;
  version: number;
}

export interface BotCommercePolicy {
  bot_id: string;
  runtime_owner: "legacy" | "registry";
  version: number;
  cart_enabled: boolean | null;
  credit_enabled: boolean | null;
  credit_label: string | null;
  default_deny: boolean;
}

export type PaymentRail = "bale_wallet" | "telegram_fiat" | "telegram_stars";
export type PaymentAccountState = "draft" | "active" | "disabled";

export interface PaymentAccount {
  id: string;
  store_id: string;
  platform: "telegram" | "bale";
  rail_type: PaymentRail;
  currency: "IRR" | "XTR";
  name: string;
  state: PaymentAccountState;
  version: number;
  has_credential: boolean;
}

export interface BotPaymentAccount extends PaymentAccount {
  granted: boolean;
  priority: number;
}

export interface PaymentAccountList {
  store_id: string;
  items: PaymentAccount[];
}

export interface BotPaymentList {
  bot_id: string;
  items: BotPaymentAccount[];
}

export interface StoreCustomerSummary {
  id: number;
  store_id: string;
  display_name: string | null;
  identities: {
    id: number;
    platform: "telegram" | "bale";
    bot_id: string;
    platform_user_id: string;
  }[];
}

export interface StoreCustomerList {
  items: StoreCustomerSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface StoreCustomerDetail {
  customer: {
    id: number;
    store_id: string;
    display_name: string | null;
    phone: string | null;
  };
  identities: StoreCustomerSummary["identities"];
  wallets: {
    id: number;
    balance_irr: string;
    scope: "identity" | "customer";
    identity_id: number | null;
  }[];
}
