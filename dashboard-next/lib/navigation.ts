import type { StaffRole } from "@/lib/types";
import { BarChart3, Bot, Boxes, ClipboardList, ContactRound, FolderTree, LayoutDashboard, Megaphone, Settings2, Webhook, Truck, TicketPercent, MessagesSquare, ShieldCheck, UserCog, UserRound, KeyRound, Image as ImageIcon, type LucideIcon } from "lucide-react";
export interface NavigationItem { title: string; href: string; icon: LucideIcon; roles: StaffRole[] }
const all: StaffRole[] = ["superadmin", "sales", "content", "finance", "marketing", "viewer"];
/** Navigation reflects fixed server roles; never replaces server authorization. */
export const navigation: NavigationItem[] = [
  { title: "نمای کلی", href: "/dashboard", icon: LayoutDashboard, roles: all },
  { title: "حساب من", href: "/account", icon: UserRound, roles: all },
  { title: "مجوزها و نقش‌ها", href: "/permissions", icon: KeyRound, roles: all },
  { title: "محصولات", href: "/products", icon: Boxes, roles: ["superadmin", "content"] },
  { title: "دسته‌بندی‌ها", href: "/categories", icon: FolderTree, roles: ["superadmin", "content"] },
  { title: "سفارش‌ها", href: "/orders", icon: ClipboardList, roles: ["superadmin", "sales", "finance"] },
  { title: "مشتریان", href: "/customers", icon: ContactRound, roles: ["superadmin", "sales"] },
  { title: "ارسال کالا", href: "/shipping", icon: Truck, roles: ["superadmin", "sales"] },
  { title: "کد تخفیف", href: "/coupons", icon: TicketPercent, roles: ["superadmin", "marketing", "sales"] },
  { title: "رضایت مشتریان", href: "/reviews", icon: MessagesSquare, roles: ["superadmin", "content"] },
  { title: "کمپین‌ها", href: "/campaigns", icon: Megaphone, roles: ["superadmin", "marketing"] },
  { title: "امور مالی", href: "/finance", icon: ShieldCheck, roles: ["superadmin", "finance"] },
  { title: "گزارش‌ها", href: "/reports", icon: BarChart3, roles: all },
  { title: "مدیران و دسترسی‌ها", href: "/staff", icon: UserCog, roles: ["superadmin"] },
  { title: "ربات‌ها", href: "/bots", icon: Bot, roles: ["superadmin"] },
  { title: "زیرساخت اتصال", href: "/bot-connections", icon: Webhook, roles: ["superadmin"] },
  { title: "Relay Worker Pool", href: "/relay-workers", icon: Webhook, roles: ["superadmin"] },
  { title: "تنظیمات", href: "/settings", icon: Settings2, roles: ["superadmin"] },
];
