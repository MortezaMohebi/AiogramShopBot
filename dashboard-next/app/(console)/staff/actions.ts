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

/** Only role and activation status may be edited by another administrator. */
export async function updateStaff(form: FormData) {
  const id = text(form, "id"), role = text(form, "role");
  if (!/^[1-9][0-9]*$/.test(id) || !roles.includes(role)) redirect("/staff?error=validation");
  try {
    await adminFetch(`/staff/${id}`, "PATCH", {
      role, is_active: form.has("is_active"),
    });
  } catch (error) { failure(error); }
  revalidatePath("/staff");
  redirect("/staff?saved=1");
}
