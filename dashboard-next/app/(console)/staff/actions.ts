"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { adminFetch } from "@/lib/bridge";

const roles = ["superadmin", "sales", "content", "finance", "marketing", "viewer"];

function text(form: FormData, name: string): string {
  return String(form.get(name) ?? "").trim();
}

/** Provision a unique database-backed operator, never a built-in password. */
export async function createStaff(form: FormData) {
  const username = text(form, "username").toLowerCase();
  const role = text(form, "role");
  const password = text(form, "password");
  if (
    !/^[a-z0-9][a-z0-9_.-]{2,79}$/.test(username) ||
    !roles.includes(role) ||
    password.length < 14 ||
    text(form, "confirmation") !== "CREATE_STAFF"
  ) {
    redirect("/staff?error=validation");
  }
  let failed = false;
  try {
    await adminFetch("/staff", "POST", {
      username, role, password, confirmation: "CREATE_STAFF",
    });
  } catch {
    failed = true;
  }
  if (failed) redirect("/staff?error=create");
  revalidatePath("/staff");
  redirect("/staff?saved=1");
}

/** Role changes, disablement and password rotation revoke old sessions. */
export async function updateStaff(form: FormData) {
  const id = text(form, "id");
  if (!/^[1-9]\d*$/.test(id) || text(form, "confirmation") !== "UPDATE_STAFF") {
    redirect("/staff?error=validation");
  }
  const role = text(form, "role");
  const password = text(form, "password");
  const self = text(form, "self") === "1";
  if (!self && !roles.includes(role)) redirect("/staff?error=role");
  if (password && password.length < 14) redirect("/staff?error=password");
  const payload = {
    ...(!self ? { role, is_active: form.has("is_active") } : {}),
    ...(password ? { password } : {}),
    confirmation: "UPDATE_STAFF",
  };
  let failed = false;
  try {
    await adminFetch(`/staff/${id}`, "PATCH", payload);
  } catch {
    failed = true;
  }
  if (failed) redirect("/staff?error=update");
  revalidatePath("/staff");
  redirect("/staff?saved=1");
}
