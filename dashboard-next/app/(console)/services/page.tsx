import Link from "next/link";
import { notFound } from "next/navigation";
import { PageHeading } from "@/components/blocks/page-heading";
import { ServiceControlCard } from "@/components/blocks/service-control-card";
import { Button } from "@/components/ui/button";
import { adminFetch, currentStaff } from "@/lib/bridge";
import { serviceGroups, type ServiceControl } from "@/lib/service-controls";

const errors: Record<string, string> = {
  validation: "درخواست معتبر نیست. صفحه را دوباره باز کنید.",
  conflict: "وضعیت سرویس تغییر کرده است. وضعیت فعلی را بررسی کنید.",
  prerequisite: "پیش‌نیاز سرویس آماده نیست.",
  reauth: "برای تغییر وضعیت سرویس، هویت خود را دوباره تأیید کنید.",
  save: "تغییر وضعیت سرویس تأیید نشد. وضعیت فعلی را بررسی کنید.",
};

export default async function ServicesPage({ searchParams }: {
  searchParams: Promise<{ saved?: string; error?: string }>;
}) {
  const staff = await currentStaff();
  if (staff.role !== "superadmin") notFound();
  const [{ items }, query] = await Promise.all([
    adminFetch<{ items: ServiceControl[] }>("/services"), searchParams,
  ]);
  const byKey = new Map(items.map((item) => [item.key, item]));

  return <div className="space-y-6">
    <PageHeading title="سرویس‌ها" />
    <p className="text-sm leading-7 text-muted-foreground">
      وضعیت سرویس‌های این نصب را تغییر دهید. هر سرویس هنگام اجرا، تنظیمات و مجوزهای ربات و فروشگاه را بررسی می‌کند.
    </p>
    {query.saved ? <p role="status" className="rounded-lg border p-3 text-sm">
      تنظیم سرویس ذخیره شد. وضعیت اجرا و پیش‌نیازها را در کارت همان سرویس ببینید.
    </p> : null}
    {query.error ? <div role="alert" className="space-y-2 rounded-lg border border-destructive/40 p-3 text-sm">
      <p>{errors[query.error] ?? errors.save}</p>
      {query.error === "reauth" ? <Button size="sm" asChild variant="outline">
        <Link href="/account">تأیید هویت در حساب من</Link>
      </Button> : null}
    </div> : null}
    {serviceGroups.map((group) => <section key={group.title} className="space-y-3">
      <h2 className="text-lg font-semibold">{group.title}</h2>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {group.keys.map((key) => {
          const service = byKey.get(key);
          return service ? <ServiceControlCard key={key} service={service} /> : null;
        })}
      </div>
    </section>)}
  </div>;
}
