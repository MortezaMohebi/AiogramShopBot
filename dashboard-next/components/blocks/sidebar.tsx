"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, MessageCircle, X } from "lucide-react";
import { LogoutControl } from "@/components/blocks/logout-control";
import type { Staff } from "@/lib/types";
import { navigation } from "@/lib/navigation";
import { cn } from "@/lib/utils";
import { Dialog } from "@/components/ui/dialog";

/** Sidebar-07-inspired navigation: RTL, mobile drawer, and role-scoped links. */
export function Sidebar({ staff }: { staff: Staff }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const visible = navigation.filter((item) => item.roles.includes(staff.role));

  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 1024px)");
    const closeOnDesktop = () => { if (desktop.matches) setOpen(false); };
    desktop.addEventListener("change", closeOnDesktop);
    return () => desktop.removeEventListener("change", closeOnDesktop);
  }, []);

  const groups = [
    { title: "فروش", paths: ["/dashboard", "/orders", "/fulfillments", "/shipping", "/digital-deliveries", "/finance", "/reports"] },
    { title: "محصولات", paths: ["/products", "/categories", "/uoms", "/data-models/products"] },
    { title: "مشتریان", paths: ["/customers", "/store-customers", "/support-tickets", "/reviews", "/campaigns", "/coupons", "/customer-notifications"] },
    { title: "تنظیمات", paths: ["/studio/workflows", "/bots", "/stores", "/payment-accounts", "/bot-connections", "/relay-workers", "/staff", "/permissions", "/settings", "/account"] },
  ];
  const content = <>
    <div className="flex h-20 shrink-0 items-center justify-between border-b border-border px-5">
      <div className="flex items-center gap-3">
        <div className="grid size-10 place-items-center rounded-xl bg-primary text-primary-foreground"><MessageCircle aria-hidden="true" className="size-5" /></div>
        <p className="text-sm font-bold">مدیریت فروشگاه</p>
      </div>
      <button type="button" className="grid size-10 place-items-center rounded-md hover:bg-muted lg:hidden" aria-label="بستن منوی مدیریت" onClick={() => setOpen(false)}><X aria-hidden="true" className="size-5" /></button>
    </div>
    <nav aria-label="بخش‌های مدیریت" className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-3">
      {groups.map((group) => {
        const links = visible.filter((item) => group.paths.includes(item.href));
        return links.length ? <div key={group.title} className="mb-4">
          <p className="px-3 pb-2 pt-2 text-xs font-medium text-muted-foreground">{group.title}</p>
          <ul className="space-y-1">{links.map(({ href, title, icon: Icon }) => {
            const current = href === "/studio/workflows" ? pathname.startsWith("/studio/") : pathname === href || pathname.startsWith(href + "/");
            return <li key={href}><Link href={href} aria-current={current ? "page" : undefined} onClick={() => setOpen(false)} className={cn("flex min-h-11 items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors", current ? "bg-accent font-semibold text-accent-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
              <Icon aria-hidden="true" className="size-[18px] shrink-0" />{title}
              {current ? <span aria-hidden="true" className="ms-auto size-1.5 shrink-0 rounded-full bg-primary" /> : null}
            </Link></li>;
          })}</ul>
        </div> : null;
      })}
    </nav>
    <div className="shrink-0 border-t border-border p-4">
      <p dir="auto" className="mb-3 truncate text-sm font-medium">{staff.username}</p>
      <LogoutControl />
    </div>
  </>;

  return <>
    <button type="button" aria-label="بازکردن منوی مدیریت" aria-expanded={open} aria-haspopup="dialog" className="fixed end-4 bottom-4 z-40 grid size-12 place-items-center rounded-full bg-primary text-primary-foreground shadow-xl lg:hidden" onClick={() => setOpen(true)}><Menu aria-hidden="true" className="size-5" /></button>
    <aside aria-label="ناوبری اصلی فروشگاه" className="sticky top-0 hidden h-dvh w-[280px] shrink-0 flex-col border-e border-border bg-card lg:flex">{content}</aside>
    <Dialog open={open} onClose={() => setOpen(false)} label="منوی مدیریت" className="m-0 me-auto h-dvh max-h-dvh w-[min(280px,calc(100%-1rem))] max-w-none rounded-none border-y-0 border-s-0">
      <div className="flex h-dvh flex-col">{content}</div>
    </Dialog>
  </>;
}
