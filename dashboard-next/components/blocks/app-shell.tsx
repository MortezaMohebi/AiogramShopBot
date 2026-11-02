import type { ReactNode } from "react";
import type { Staff } from "@/lib/types";
import { Sidebar } from "@/components/blocks/sidebar";
import { ThemeToggle } from "@/components/blocks/theme-toggle";
import { ShieldCheck } from "lucide-react";

/** Dashboard-01-inspired app shell: permanent RTL sidebar and compact header. */
export function AppShell({
  staff,
  children,
}: {
  staff: Staff;
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
            <span className="hidden items-center gap-1 rounded-full bg-accent px-3 py-1 text-xs text-accent-foreground sm:inline-flex">
              <ShieldCheck className="size-3.5" /> داده‌های واقعی
            </span>
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
