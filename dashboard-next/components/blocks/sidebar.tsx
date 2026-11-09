"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, MessageCircle, X } from "lucide-react";
import { LogoutControl } from "@/components/blocks/logout-control";
import type { Staff } from "@/lib/types";
import { navigation } from "@/lib/navigation";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";

function NavigationContent({ staff, onClose }: { staff: Staff; onClose?: () => void }) {
  const pathname = usePathname();
  const visible = navigation.filter((item) => item.roles.includes(staff.role));

  const groups = [
    { title: "فروش", paths: ["/dashboard", "/orders", "/fulfillments", "/shipping", "/digital-deliveries", "/finance", "/reports"] },
    { title: "محصولات", paths: ["/products", "/product-attributes", "/product-attribute-values", "/categories", "/uoms", "/data-models/products"] },
    { title: "مشتریان", paths: ["/customers", "/store-customers", "/support-tickets", "/reviews", "/campaigns", "/coupons", "/customer-notifications"] },
    { title: "تنظیمات", paths: ["/studio/workflows", "/bots", "/stores", "/payment-accounts", "/relay-workers", "/staff", "/permissions", "/services", "/settings", "/account"] },
  ];
  return <>
    <div className="flex h-20 shrink-0 items-center justify-between border-b border-border px-5">
      <div className="flex items-center gap-3">
        <div className="grid size-10 place-items-center rounded-xl bg-primary text-primary-foreground"><MessageCircle aria-hidden="true" className="size-5" /></div>
        <p className="text-sm font-bold">مدیریت فروشگاه</p>
      </div>
      {onClose && (
        <Button type="button" variant="ghost" size="icon" className="size-11"
          aria-label="بستن منوی مدیریت" onClick={onClose}>
          <X aria-hidden="true" />
        </Button>
      )}
    </div>
    <nav aria-label="بخش‌های مدیریت" className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-3">
      {groups.map((group) => {
        const links = visible.filter((item) => group.paths.includes(item.href));
        return links.length ? <div key={group.title} className="mb-4">
          <p className="px-3 pb-2 pt-2 text-xs font-medium text-muted-foreground">{group.title}</p>
          <ul className="space-y-1">{links.map(({ href, title, icon: Icon }) => {
            const current = href === "/studio/workflows" ? pathname.startsWith("/studio/") : pathname === href || pathname.startsWith(href + "/");
            return <li key={href}><Link href={href} aria-current={current ? "page" : undefined} onClick={onClose} className={cn("flex min-h-11 items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors", current ? "bg-accent font-semibold text-accent-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
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
}

export function Sidebar({ staff }: { staff: Staff }) {
  return <aside aria-label="ناوبری اصلی فروشگاه" className="sticky top-0 hidden h-dvh w-[280px] shrink-0 flex-col border-e border-border bg-card lg:flex">
    <NavigationContent staff={staff} />
  </aside>;
}

export function MobileNavigation({ staff }: { staff: Staff }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 1024px)");
    const closeOnDesktop = () => { if (desktop.matches) setOpen(false); };
    desktop.addEventListener("change", closeOnDesktop);
    return () => desktop.removeEventListener("change", closeOnDesktop);
  }, []);

  const close = () => setOpen(false);
  return <>
    <Button type="button" variant="ghost" aria-expanded={open} aria-haspopup="dialog"
      className="h-11 px-3 lg:hidden" onClick={(event) => {
        // Mobile Safari does not always focus a button when it is tapped.
        event.currentTarget.focus();
        setOpen(true);
      }}>
      <Menu aria-hidden="true" />
      منو
    </Button>
    <Dialog open={open} onClose={close} label="منوی مدیریت"
      className="mobile-navigation-drawer inset-y-0 start-0 end-auto m-0 h-dvh max-h-dvh w-[min(20rem,calc(100%-2.5rem))] max-w-none overflow-hidden rounded-none border-y-0 border-s-0">
      <div className="flex h-dvh flex-col">
        <NavigationContent staff={staff} onClose={close} />
      </div>
    </Dialog>
  </>;
}
