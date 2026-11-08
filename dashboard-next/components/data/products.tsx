import Link from "next/link";
import { RecordClickArea } from "@/components/ui/record-click-area";
import { RecordLink } from "@/components/ui/record-link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { readSection } from "@/lib/read-section";
import { formatIrr } from "@/lib/utils";
import type { Paginated, Product } from "@/lib/types";
import { BulkSelectCheckbox, BulkUnpublishSelection } from "@/components/blocks/bulk-unpublish-selection";
import { DataSectionError } from "./section-error";

type Props = { page: number; search: string; canEdit: boolean };
/** Read only this section; keep the authorized search form outside the wait. */
export async function ProductsResults({ page, search, canEdit }: Props) {
  const result = await readSection<Paginated<Product>>(`/products?page=${page}&search=${encodeURIComponent(search)}`);
  if (!result.ok) return <DataSectionError title="محصولات دریافت نشدند" />;
  return <ProductsTable data={result.data} page={page} search={search} canEdit={canEdit} />;
}

/** The existing table, empty states and pagination share one authoritative response. */
export function ProductsTable({ data, page, search, canEdit }: Props & { data: Paginated<Product> }) {
  const lastPage = Math.max(1, Math.ceil(data.total / data.page_size));
  return <BulkUnpublishSelection key={`${page}:${search}`} entity="products"
    eligible={data.items.map((item) => item.id)}
    archivable={data.items.filter((item) => item.is_published).map((item) => item.id)}
    canArchive={canEdit}>
          <Table>
            <TableHeader><TableRow>
              <TableHead><BulkSelectCheckbox all /></TableHead>
              <TableHead>محصول</TableHead><TableHead>کد</TableHead>
              <TableHead>قیمت</TableHead><TableHead>موجودی</TableHead>
              <TableHead>انتشار</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {data.items.map((item) => {
                const cells = <>
                  <TableCell><BulkSelectCheckbox id={item.id} /></TableCell>
                  <TableCell className="max-w-64 font-semibold">{canEdit
                    ? <RecordLink href={`/products/${item.id}/edit`}>{item.name}</RecordLink>
                    : item.name}</TableCell>
                  <TableCell dir="ltr" className="text-start text-xs text-muted-foreground">{item.sku}</TableCell>
                  <TableCell className="whitespace-nowrap tabular">{formatIrr(item.price_irr)}</TableCell>
                  <TableCell className="tabular">{item.stock_quantity}</TableCell>
                  <TableCell><Badge tone={item.is_published ? "success" : "neutral"}>{item.is_published ? "منتشرشده" : "پیش‌نویس"}</Badge></TableCell>
                </>;
                return canEdit
                  ? <RecordClickArea as="tr" key={item.id} className="border-b border-border">{cells}</RecordClickArea>
                  : <TableRow key={item.id}>{cells}</TableRow>;
              })}
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
  </BulkUnpublishSelection>;
}
