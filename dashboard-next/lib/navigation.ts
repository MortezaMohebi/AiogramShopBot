import type { StaffRole } from "@/lib/types";
import {
  BarChart3,
  Boxes,
  ClipboardList,
  ContactRound,
  FolderTree,
  LayoutDashboard,
  Megaphone,
  Settings2,
  ShieldCheck,
  Image as ImageIcon,
  type LucideIcon,
} from "lucide-react";

export interface NavigationItem {
  title: string;
  href: string;
  icon: LucideIcon;
  roles: StaffRole[];
}

/** Visible navigation is derived from role; Python enforces actual access. */
export const navigation: NavigationItem[] = [
  {
    title: "نمای کلی", href: "/dashboard", icon: LayoutDashboard,
    roles: ["superadmin", "sales", "content", "finance", "marketing", "viewer"],
  },
  {
    title: "محصولات", href: "/products", icon: Boxes,
    roles: ["superadmin", "content"],
  },
  {
    title: "دسته‌بندی‌ها", href: "/categories", icon: FolderTree,
    roles: ["superadmin", "content"],
  },
  {
    title: "سفارش‌ها", href: "/orders", icon: ClipboardList,
    roles: ["superadmin", "sales", "finance"],
  },
  {
    title: "مشتریان", href: "/customers", icon: ContactRound,
    roles: ["superadmin", "sales"],
  },
  {
    title: "رسانه‌ها", href: "/media", icon: ImageIcon,
    roles: ["superadmin", "content"],
  },
  {
    title: "کمپین‌ها", href: "/campaigns", icon: Megaphone,
    roles: ["superadmin", "marketing"],
  },
  {
    title: "امور مالی", href: "/finance", icon: ShieldCheck,
    roles: ["superadmin", "finance"],
  },
  {
    title: "گزارش‌ها", href: "/reports", icon: BarChart3,
    roles: ["superadmin", "sales", "content", "finance", "marketing", "viewer"],
  },
  {
    title: "تنظیمات", href: "/settings", icon: Settings2,
    roles: ["superadmin"],
  },
];

/** Finance ledger stays behind its existing guarded SQLAdmin interface. */
export const legacyFinanceIcon = ShieldCheck;
