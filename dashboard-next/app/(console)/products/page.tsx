import Link from "next/link";
import { Plus, Search } from "lucide-react";
import { PageHeading } from "@/components/blocks/page-heading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { adminFetch, currentStaff } from "@/lib/bridge";
import { formatIrr } from "@/lib/utils";
import type { Paginated, Product } from "@/lib/types";

type Params = Promise<{ page?: string; search?: string; saved?: string }>;

/** Product catalogue block with server pagination, actual SKU and stock. */
export default async function ProductsPage({ searchParams }: { searchParams: Params }) {
  const q = await searchParams;
  const page = Math.max(1, Math.min(100000, Number.parseInt(q.page ?? "1", 10) || 1));
  const search = (q.search ?? "").slice(0, 100);
  const staff = await currentStaff();
  const canEdit = staff.role === "superadmin" || staff.role === "content";
  const data = await adminFetch<Paginated<Product>>(
    `/products?page=${page}&search=${encodeURIComponent(search)}`,
  );
  const lastPage = Math.max(1, Math.ceil(data.total / data.page_size));

  return (
    <div>
      <PageHeading
        title="محصولات"
        action={canEdit ? <Button asChild><Link href="/products/new"><Plus /> محصول جدید</Link></Button> : undefined}
      />
      <div className="mb-4 flex flex-wrap gap-2">
        <Button asChild variant="outline" size="sm">
          <Link href="/data-models/products">جست‌وجوی پیشرفته و ورود و خروج داده</Link>
        </Button>
        <Button asChild variant="outline" size="sm">
          <Link href="/uoms">واحدهای اندازه‌گیری</Link>
        </Button>
      </div>
      {q.saved ? <p role="status" className="mb-4 rounded-lg bg-accent px-4 py-3 text-sm text-accent-foreground">محصول ذخیره شد.</p> : null}
      <Card>
        <CardContent className="pt-5">
          <form method="get" className="mb-5 flex flex-wrap items-end gap-2">
            <label className="min-w-48 flex-1 space-y-2 text-sm">
              <span className="font-medium">جستجو در محصول و SKU</span>
              <Input name="search" maxLength={100} placeholder="نام یا کد کالا..." defaultValue={search} />
            </label>
            <Button type="submit" variant="outline"><Search /> جستجو</Button>
          </form>
          <Table>
            <TableHeader><TableRow>
              <TableHead>محصول</TableHead><TableHead>کد</TableHead>
              <TableHead>قیمت</TableHead><TableHead>موجودی</TableHead>
              <TableHead>انتشار</TableHead><TableHead>عملیات</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {data.items.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="max-w-64 font-semibold">{item.name}</TableCell>
                  <TableCell dir="ltr" className="text-start text-xs text-muted-foreground">{item.sku}</TableCell>
                  <TableCell className="whitespace-nowrap tabular">{formatIrr(item.price_irr)}</TableCell>
                  <TableCell className="tabular">{item.stock_quantity}</TableCell>
                  <TableCell><Badge tone={item.is_published ? "success" : "neutral"}>{item.is_published ? "منتشرشده" : "پیش‌نویس"}</Badge></TableCell>
                  <TableCell>
                    {canEdit ? <Link className="text-sm font-semibold text-primary hover:underline" href={`/products/${item.id}/edit`}>ویرایش</Link> : <span className="text-muted-foreground">فقط مشاهده</span>}
                  </TableCell>
                </TableRow>
              ))}
              {!data.items.length ? <TableRow><TableCell colSpan={6} className="py-12 text-center text-muted-foreground">{search ? "محصولی با این نام یا SKU پیدا نشد. جست‌وجو را تغییر دهید." : "هنوز محصولی ثبت نشده است."}</TableCell></TableRow> : null}
            </TableBody>
          </Table>
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 text-sm">
            <span className="text-muted-foreground">جمع کل: {new Intl.NumberFormat("fa-IR").format(data.total)} محصول</span>
            <div className="flex items-center gap-2">
              {page <= 1 ? <Button size="sm" variant="outline" disabled>قبلی</Button> : <Button asChild size="sm" variant="outline">
                <Link href={`/products?page=${page - 1}&search=${encodeURIComponent(search)}`}>قبلی</Link>
              </Button>}
              <span className="tabular">{page} / {lastPage}</span>
              {page >= lastPage ? <Button size="sm" variant="outline" disabled>بعدی</Button> : <Button asChild size="sm" variant="outline">
                <Link href={`/products?page=${page + 1}&search=${encodeURIComponent(search)}`}>بعدی</Link>
              </Button>}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
