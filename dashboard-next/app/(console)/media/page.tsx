import { notFound } from "next/navigation";
import { PageHeading } from "@/components/blocks/page-heading";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { Paginated } from "@/lib/types";
import Link from "next/link";

type Media = {
  id: number;
  product_id: number;
  product_name: string;
  kind: string;
  filename: string;
  size_bytes: number;
  is_published: boolean;
  position: number;
};
type Params = Promise<{page?: string}>;

const sizes = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 });

/** List actual private media metadata; old guarded uploader remains available. */
export default async function MediaPage({ searchParams }: { searchParams: Params }) {
  const staff = await currentStaff();
  if (!["superadmin", "content"].includes(staff.role)) notFound();
  const params = await searchParams;
  const page = Math.max(1, Math.min(100000, Number.parseInt(params.page ?? "1", 10) || 1));
  const result = await adminFetch<Paginated<Media>>(`/media?page=${page}`);
  const legacy = process.env.LEGACY_ADMIN_PUBLIC_URL;
  return (
    <div>
      <PageHeading
        title="رسانه‌های فروشگاه"
        description="تصاویر و فایل‌ها در فضای خصوصی نگهداری می‌شوند. برای بله، عکس تا ۱۰ MB و سایر فایل‌ها تا ۵۰ MB مجاز است."
        action={legacy ? <Button asChild><a href={`${legacy.replace(/\/$/, "")}/media-upload`} rel="noopener noreferrer">بارگذاری در پنل فعلی</a></Button> : undefined}
      />
      {!legacy ? <p className="mb-5 rounded-lg border border-border bg-muted px-4 py-3 text-sm text-muted-foreground">نمایش رسانه‌ها فعال است؛ Upload و تأیید انتشار همچنان در SQLAdmin محافظت‌شده انجام می‌شود و لینک آن باید هنگام استقرار تنظیم شود.</p> : null}
      <Card><CardContent className="pt-5">
        <Table><TableHeader><TableRow><TableHead>محصول</TableHead><TableHead>فایل</TableHead><TableHead>نوع</TableHead><TableHead>حجم</TableHead><TableHead>انتشار</TableHead></TableRow></TableHeader>
          <TableBody>{result.items.map((item) => (
            <TableRow key={item.id}>
              <TableCell>{item.product_name}</TableCell>
              <TableCell dir="ltr" className="max-w-52 truncate text-start text-xs">{item.filename}</TableCell>
              <TableCell>{item.kind}</TableCell>
              <TableCell className="whitespace-nowrap">{sizes.format(item.size_bytes / 1_000_000)} MB</TableCell>
              <TableCell><Badge tone={item.is_published ? "success" : "neutral"}>{item.is_published ? "منتشرشده" : "منتشرنشده"}</Badge></TableCell>
            </TableRow>))}
            {!result.items.length ? <TableRow><TableCell colSpan={5} className="py-10 text-center text-muted-foreground">رسانه‌ای ثبت نشده است.</TableCell></TableRow> : null}
          </TableBody>
        </Table>
      </CardContent></Card>
    </div>
  );
}
