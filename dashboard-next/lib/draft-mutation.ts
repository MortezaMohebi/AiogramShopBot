import "server-only";
import { revalidatePath } from "next/cache";
import { bridgeFetch } from "@/lib/bridge";
import { sectionRpcError } from "@/lib/section-rpc-server";
import type { SectionRpcResult } from "@/lib/section-rpc";
import { readSession } from "@/lib/session";

/** Use the same protected bridge as page actions, with a receipt the form can use. */
export async function saveDraftMutation(
  path: string,
  method: "POST" | "PATCH",
  payload: unknown,
  ...pages: string[]
): Promise<SectionRpcResult<null>> {
  const session = await readSession();
  if (!session) return { ok: false, code: "session_expired" };
  try {
    await bridgeFetch(path, method, payload, session);
  } catch (error) {
    return { ok: false, code: sectionRpcError(error, true) };
  }
  pages.forEach(page => revalidatePath(page));
  return { ok: true, data: null };
}
