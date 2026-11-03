"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { adminFetch, ApiError } from "@/lib/bridge";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ACCESS = new Set(["viewer", "editor", "manager"]);

function fail(error: unknown, memberId: number): never {
  if (!(error instanceof ApiError)) throw error;
  if (error.status === 401) redirect("/login?expired=1");
  if (error.status === 428) redirect(`/staff/${memberId}/stores?error=reauth`);
  const allowed = new Set([
    "store_permission_denied", "store_access_denied",
    "invalid_store_grants", "invalid_store_default",
    "last_store_manager", "configuration_changed",
    "staff_not_found", "invalid_credentials", "invalid_verification",
  ]);
  const code = error.code && allowed.has(error.code) ? error.code : "save";
  redirect(`/staff/${memberId}/stores?error=${code}`);
}

/** Replace only Stores that this manager is authorized to administer. */
export async function saveStaffStoreAccess(form: FormData): Promise<void> {
  const rawId = String(form.get("staff_id") ?? "");
  const memberId = Number(rawId);
  if (!/^[1-9][0-9]*$/.test(rawId) ||
      !Number.isSafeInteger(memberId)) {
    redirect("/staff?error=validation");
  }
  const ids = form.getAll("store_ids").map(String);
  const defaultStore = String(form.get("default_store_id") ?? "");
  const current_password = String(form.get("current_password") ?? "");
  const second_factor = String(form.get("second_factor") ?? "");
  if (ids.length < 1 || ids.length > 100 ||
    new Set(ids).size !== ids.length ||
    ids.some((id) => !UUID.test(id)) ||
    !UUID.test(defaultStore) || !ids.includes(defaultStore) ||
    !current_password || current_password.length > 256 ||
    !/^[0-9]{6}$/.test(second_factor)) {
    redirect(`/staff/${memberId}/stores?error=validation`);
  }
  const grants = ids.map((id) => ({
    store_id: id,
    access_level: String(form.get(`access:${id}`) ?? ""),
  }));
  if (grants.some((grant) => !ACCESS.has(grant.access_level))) {
    redirect(`/staff/${memberId}/stores?error=validation`);
  }
  try {
    await adminFetch(`/staff/${memberId}/store-access`, "POST", {
      grants, default_store_id: defaultStore, current_password, second_factor,
    });
  } catch (error) { fail(error, memberId); }
  revalidatePath("/staff");
  revalidatePath(`/staff/${memberId}/stores`);
  redirect(`/staff/${memberId}/stores?saved=1`);
}
