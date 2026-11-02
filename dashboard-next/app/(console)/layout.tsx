import type { ReactNode } from "react";
import { AppShell } from "@/components/blocks/app-shell";
import { currentStaff } from "@/lib/bridge";

/** Every protected page revalidates its revocable staff identity at render. */
export default async function ConsoleLayout({ children }: { children: ReactNode }) {
  const staff = await currentStaff();
  return <AppShell staff={staff}>{children}</AppShell>;
}
