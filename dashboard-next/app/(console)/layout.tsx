import { Suspense, type ReactNode } from "react";
import { AppShell } from "@/components/blocks/app-shell";
import { ConsoleReauthentication } from "@/components/blocks/console-reauthentication";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { StoreContextSnapshot } from "@/lib/store-context";

/** Every protected page revalidates its revocable staff identity at render. */
export default async function ConsoleLayout({ children }: { children: ReactNode }) {
  const [staff, storeContext] = await Promise.all([
    currentStaff(),
    adminFetch<StoreContextSnapshot>("/store-context"),
  ]);
  return <AppShell staff={staff} storeContext={storeContext}>
    <Suspense><ConsoleReauthentication /></Suspense>
    {children}
  </AppShell>;
}
