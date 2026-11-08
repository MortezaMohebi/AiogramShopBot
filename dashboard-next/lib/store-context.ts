/** Verified, redacted user Store environment received from the signed API. */

export type StoreAccessLevel = "viewer" | "editor" | "manager";

export interface StoreOption {
  id: string;
  slug: string;
  name: string;
  state: "active" | "paused" | "archived";
  access_level: StoreAccessLevel;
  active: boolean;
  current: boolean;
}

export interface StoreContextSnapshot {
  staff_id: number;
  current_store_id: string;
  default_store_id: string;
  active_store_ids: string[];
  allowed_store_ids: string[];
  version: number;
  preference_version: number;
  stores: StoreOption[];
}

export interface StaffStorePermissions {
  staff_id: number;
  default_store_id: string | null;
  default_version: number;
  stores: Array<{
    id: string;
    name: string;
    slug: string;
    state: "active" | "paused" | "archived";
    granted: boolean;
    access_level: StoreAccessLevel | null;
  }>;
}
