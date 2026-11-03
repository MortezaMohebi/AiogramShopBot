import type { ReactNode } from "react";
import type { Staff } from "@/lib/types";
import type { StoreContextSnapshot } from "@/lib/store-context";
import { StoreSwitcher } from "@/components/blocks/store-switcher";
import { Sidebar } from "@/components/blocks/sidebar";
import { ThemeToggle } from "@/components/blocks/theme-toggle";
import Link from "next/link";
import { CircleUserRound } from "lucide-react";

/** Dashboard-01-inspired app shell: permanent RTL sidebar and compact header. */
export function AppShell({
  staff,
  storeContext,
  children,
}: {
  staff: Staff;
  storeContext: StoreContextSnapshot;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen lg:flex lg:flex-row">
      <Sidebar staff={staff} />
      <div className="min-w-0 flex-1 lg:me-0">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-border bg-background/90 px-4 backdrop-blur-xl sm:px-8">
          <div className="flex items-center gap-2 text-sm">
            <span className="hidden text-muted-foreground sm:inline">پنل مدیریت</span>
            <span className="hidden text-muted-foreground sm:inline">/</span>
            <span className="font-semibold">فروشگاه تلگرام و بله</span>
          </div>
          <div className="flex items-center gap-2">
            <StoreSwitcher context={storeContext} />
            <Link href="/account" className="inline-flex h-10 items-center gap-2 rounded-lg border border-border bg-background px-3 text-sm font-medium transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring" aria-label="بازکردن پروفایل و امنیت حساب">
              <CircleUserRound aria-hidden="true" className="size-4" />
              <span>حساب من</span>
            </Link>
            <ThemeToggle />
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1600px] px-4 py-7 sm:px-8 sm:py-9">
          {children}
        </main>
      </div>
    </div>
  );
}
