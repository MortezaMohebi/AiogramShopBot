import type { StaffRole } from "@/lib/types";
import { ListTree, Tags } from "lucide-react";
import { Workflow, BarChart3, Bot, Boxes, Ruler, Database, ClipboardList, ContactRound, Store, Wallet, Users, ServerCog, FolderTree, LayoutDashboard, Megaphone, Settings2, Webhook, Truck, TicketPercent, MessagesSquare, ShieldCheck, UserCog, UserRound, KeyRound, type LucideIcon } from "lucide-react";
export interface NavigationItem { title: string; href: string; icon: LucideIcon; roles: StaffRole[] }
const all: StaffRole[] = ["superadmin", "sales", "content", "finance", "marketing", "viewer"];
/** Navigation reflects fixed server roles; never replaces server authorization. */
export const navigation: NavigationItem[] = [
  { title: "نمای کلی", href: "/dashboard", icon: LayoutDashboard, roles: all },
  { title: "گردش‌کارها", href: "/studio/workflows", icon: Workflow, roles: all },
  { title: "حساب من", href: "/account", icon: UserRound, roles: all },
  { title: "مجوزها و نقش‌ها", href: "/permissions", icon: KeyRound, roles: all },
  { title: "محصولات", href: "/products", icon: Boxes, roles: ["superadmin", "content"] },
  { title: "ویژگی‌های محصول", href: "/product-attributes", icon: ListTree, roles: ["superadmin", "content"] },
  { title: "مقدارهای ویژگی", href: "/product-attribute-values", icon: Tags, roles: ["superadmin", "content"] },
  { title: "واحدهای اندازه‌گیری", href: "/uoms", icon: Ruler, roles: ["superadmin"] },
  { title: "ورود و خروج داده", href: "/data-models/products", icon: Database, roles: ["superadmin", "content"] },
  { title: "دسته‌بندی‌ها", href: "/categories", icon: FolderTree, roles: ["superadmin", "content"] },
  { title: "سفارش‌ها", href: "/orders", icon: ClipboardList, roles: ["superadmin", "sales", "finance"] },
  { title: "تحویل دیجیتال و رسیدها", href: "/digital-deliveries", icon: ClipboardList, roles: ["superadmin", "sales", "finance"] },
  { title: "تحویل سفارش‌ها", href: "/fulfillments", icon: Truck, roles: ["superadmin", "sales"] },
  { title: "پشتیبانی و تیکت‌ها", href: "/support-tickets", icon: MessagesSquare, roles: ["superadmin", "sales"] },
  { title: "مشتریان", href: "/customers", icon: ContactRound, roles: ["superadmin", "sales"] },
  { title: "ارسال کالا", href: "/shipping", icon: Truck, roles: ["superadmin", "sales"] },
  { title: "کد تخفیف", href: "/coupons", icon: TicketPercent, roles: ["superadmin", "marketing", "sales"] },
  { title: "رضایت مشتریان", href: "/reviews", icon: MessagesSquare, roles: ["superadmin", "content"] },
  { title: "کمپین‌ها", href: "/campaigns", icon: Megaphone, roles: ["superadmin", "marketing"] },
  { title: "امور مالی", href: "/finance", icon: ShieldCheck, roles: ["superadmin", "finance"] },
  { title: "گزارش‌ها", href: "/reports", icon: BarChart3, roles: all },
  { title: "مدیران و دسترسی‌ها", href: "/staff", icon: UserCog, roles: ["superadmin"] },
  { title: "ربات‌ها", href: "/bots", icon: Bot, roles: ["superadmin"] },
  { title: "فروشگاه‌های من", href: "/stores", icon: Store, roles: ["superadmin"] },
  { title: "مشتریان یکپارچه", href: "/store-customers", icon: Users, roles: ["superadmin"] },
  { title: "اعلان‌ها و موجودی", href: "/customer-notifications", icon: Megaphone, roles: ["superadmin"] },
  { title: "حساب‌های پرداخت", href: "/payment-accounts", icon: Wallet, roles: ["superadmin"] },
  { title: "اتصال‌های Relay", href: "/relay-workers", icon: Webhook, roles: ["superadmin"] },
  { title: "سرویس‌ها", href: "/services", icon: ServerCog, roles: ["superadmin"] },
  { title: "تنظیمات", href: "/settings", icon: Settings2, roles: ["superadmin"] },
];
