import { PageHeading } from "@/components/blocks/page-heading";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { adminFetch } from "@/lib/bridge";
import { permissionLabels } from "@/lib/account-control";
const roleLabels: Record<string, string> = { viewer: "مشاهده‌گر", sales: "فروش", content: "محتوا", finance: "مالی", marketing: "بازاریابی", superadmin: "مدیر اصلی" };
interface Permissions { role: string; effective: string[]; roles: Record<string, string[]> }
/** Explain fixed permission sets; do not imply editable privilege escalation. */
export default async function PermissionsPage() {
  const data = await adminFetch<Permissions>("/account/permissions");
  return <div className="space-y-6"><PageHeading title="نقش‌ها و دسترسی‌ها" />
    <p className="text-sm">نقش فعلی شما: <b>{roleLabels[data.role] ?? data.role}</b></p>
    <div className="grid gap-4 lg:grid-cols-2">{Object.entries(data.roles).map(([name, values]) => <Card key={name}><CardHeader><CardTitle>{roleLabels[name] ?? name}{name === data.role ? " — نقش شما" : ""}</CardTitle></CardHeader><CardContent className="grid gap-2 sm:grid-cols-2">{values.map((value) => <p key={value} className="text-xs">{permissionLabels[value] ?? value}</p>)}</CardContent></Card>)}</div>
  </div>;
}
