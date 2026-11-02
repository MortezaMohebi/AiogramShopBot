import { PageHeading } from "@/components/blocks/page-heading";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { adminFetch } from "@/lib/bridge";
import type { Customer, Paginated } from "@/lib/types";
import Link from "next/link";

type Params = Promise<{ page?: string }>;

/** Scoped identities: matching numeric Telegram/Bale IDs are not merged. */
export default async function CustomersPage({ searchParams }: { searchParams: Params }) {
  const params = await searchParams;
  const page = Math.max(1, Math.min(100000, Number.parseInt(params.page ?? "1", 10) || 1));
  const result = await adminFetch<Paginated<Customer>>(`/customers?page=${page}`);
  const last = Math.max(1, Math.ceil(result.total / result.page_size));
  return (
    <div>
      <PageHeading title="مشتریان" description="هویت و رضایت دریافت اطلاعیه به‌صورت مستقل برای هر پیام‌رسان ثبت می‌شود؛ رضایت کاربر به‌طور پیش‌فرض غیرفعال است." />
      <Card><CardContent className="pt-5">
        <Table>
          <TableHeader><TableRow>
            <TableHead>نام</TableHead><TableHead>پیام‌رسان</TableHead>
            <TableHead>شناسه</TableHead><TableHead>اعلان</TableHead><TableHead>وضعیت</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {result.items.map((customer) => (
              <TableRow key={customer.id}>
                <TableCell><p className="font-semibold">{customer.name || "بدون نام"}</p><p className="text-xs text-muted-foreground">{customer.username || "—"}</p></TableCell>
                <TableCell>{customer.platform === "bale" ? "بله" : "تلگرام"}</TableCell>
                <TableCell dir="ltr" className="text-start text-xs tabular">{customer.user_id}</TableCell>
                <TableCell><Badge tone={customer.allow_announcements ? "success" : "neutral"}>{customer.allow_announcements ? "مجاز" : "بدون رضایت"}</Badge></TableCell>
                <TableCell><Badge tone={customer.is_blocked ? "danger" : "neutral"}>{customer.is_blocked ? "مسدود" : "فعال"}</Badge></TableCell>
              </TableRow>
            ))}
            {!result.items.length ? <TableRow><TableCell colSpan={5} className="py-12 text-center text-muted-foreground">مشتری‌ای ثبت نشده است.</TableCell></TableRow> : null}
          </TableBody>
        </Table>
      </CardContent></Card>
      <div className="mt-5 flex items-center justify-end gap-3">
        <Button asChild variant="outline" size="sm"><Link href={`/customers?page=${Math.max(1, page - 1)}`} aria-disabled={page === 1}>قبلی</Link></Button>
        <span className="text-sm text-muted-foreground">صفحه {page} از {last}</span>
        <Button asChild variant="outline" size="sm"><Link href={`/customers?page=${Math.min(last, page + 1)}`} aria-disabled={page === last}>بعدی</Link></Button>
      </div>
    </div>
  );
}
