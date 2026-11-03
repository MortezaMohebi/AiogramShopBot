"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { adminFetch, ApiError } from "@/lib/bridge";

const roles = ["superadmin", "sales", "content", "finance", "marketing", "viewer"];
const text = (form: FormData, key: string) => String(form.get(key) ?? "").trim();
const safeCodes = new Set(["reauthentication_required", "staff_username_exists", "last_admin_protected", "use_my_account"]);

/** Surface a safe actionable failure, preserving Next.js redirect exceptions. */
function failure(error: unknown): never {
  if (!(error instanceof ApiError)) throw error;
  if (error.status === 401) redirect("/login?expired=1");
  redirect(`/staff?error=${error.code && safeCodes.has(error.code) ? error.code : "update"}`);
}

/** Preserve password characters; only usernames and prose are normalized. */
export async function createStaff(form: FormData) {
  const username = text(form, "username").toLowerCase();
  const role = text(form, "role") || "viewer";
  const password = String(form.get("password") ?? "");
  if (!/^[a-z0-9][a-z0-9_.-]{2,79}$/.test(username) || !roles.includes(role)
      || password.length < 14 || password.length > 256 || text(form, "confirmation") !== "CREATE_STAFF") {
    redirect("/staff?error=validation");
  }
  try { await adminFetch("/staff", "POST", { username, role, password, confirmation: "CREATE_STAFF" }); }
  catch (error) { failure(error); }
  revalidatePath("/staff");
  redirect("/staff?saved=1");
}

/** Server-side role checks and audit/revocation are authoritative. */
export async function updateStaff(form: FormData) {
  const id = text(form, "id"), role = text(form, "role");
  const password = String(form.get("password") ?? "");
  if (!/^[1-9]\d*$/.test(id) || !roles.includes(role)
      || (password && (password.length < 14 || password.length > 256))
      || text(form, "confirmation") !== "UPDATE_STAFF") redirect("/staff?error=validation");
  try {
    await adminFetch(`/staff/${id}`, "PATCH", {
      role, is_active: form.has("is_active"), ...(password ? { password } : {}), confirmation: "UPDATE_STAFF",
    });
  } catch (error) { failure(error); }
  revalidatePath("/staff");
  redirect("/staff?saved=1");
}
