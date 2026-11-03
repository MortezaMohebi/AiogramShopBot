"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, MessageCircle, X } from "lucide-react";
import { LogoutControl } from "@/components/blocks/logout-control";
import type { Staff } from "@/lib/types";
import { navigation } from "@/lib/navigation";
import { cn } from "@/lib/utils";

/** Sidebar-07-inspired navigation: RTL, mobile drawer, and role-scoped links. */
export function Sidebar({ staff }: { staff: Staff }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const visible = navigation.filter((item) => item.roles.includes(staff.role));

  return (
    <>
      <button
        type="button"
        aria-label="بازکردن منوی مدیریت"
        aria-expanded={open}
        className="fixed end-4 bottom-4 z-40 grid size-12 place-items-center rounded-full bg-primary text-primary-foreground shadow-xl lg:hidden"
        onClick={() => setOpen(true)}
      >
        <Menu className="size-5" />
      </button>
      {open ? (
        <button
          aria-label="بستن منوی مدیریت"
          className="fixed inset-0 z-40 bg-black/65 lg:hidden"
          onClick={() => setOpen(false)}
        />
      ) : null}
      <aside
        aria-label="ناوبری اصلی فروشگاه"
        className={cn(
          "fixed inset-y-0 start-0 z-50 flex w-[280px] flex-col border-e border-border bg-card transition-transform duration-200 lg:sticky lg:top-0 lg:h-screen lg:translate-x-0",
          open ? "translate-x-0" : "translate-x-full lg:translate-x-0",
        )}
      >
        <div className="flex h-20 items-center justify-between border-b border-border px-5">
          <div className="flex items-center gap-3">
            <div className="grid size-10 place-items-center rounded-xl bg-primary text-primary-foreground">
              <MessageCircle className="size-5" />
            </div>
            <div>
              <p className="text-sm font-bold">مدیریت فروشگاه</p>
              <p className="text-xs text-muted-foreground">Telegram / Bale</p>
            </div>
          </div>
          <button type="button" className="lg:hidden" aria-label="بستن" onClick={() => setOpen(false)}>
            <X className="size-5" />
          </button>
        </div>

        <nav aria-label="بخش‌های مدیریت" className="scrollbar-thin flex-1 overflow-y-auto p-3">
          <p className="px-3 pb-3 pt-4 text-xs font-medium text-muted-foreground">فضای کار</p>
          <ul className="space-y-1">
            {visible.map(({ href, title, icon: Icon }) => {
              const current = pathname === href || pathname.startsWith(href + "/");
              return (
                <li key={href}>
                  <Link
                    href={href}
                    aria-current={current ? "page" : undefined}
                    onClick={() => setOpen(false)}
                    className={cn(
                      "flex h-11 items-center gap-3 rounded-lg px-3 text-sm transition-colors",
                      current
                        ? "bg-accent font-semibold text-accent-foreground"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground",
                    )}
                  >
                    <Icon aria-hidden="true" className="size-[18px]" />
                    {title}
                    {current ? <span className="ms-auto size-1.5 rounded-full bg-primary" /> : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="border-t border-border p-4">
          <div className="mb-3 rounded-lg bg-muted/70 p-3">
            <p className="text-sm font-semibold">{staff.username}</p>
            <p className="text-xs text-muted-foreground">نقش: {staff.role}</p>
          </div>
          <LogoutControl />
        </div>
      </aside>
    </>
  );
}
