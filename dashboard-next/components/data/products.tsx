import { RecordClickArea } from "@/components/ui/record-click-area";
import { RecordLink } from "@/components/ui/record-link";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ListRangePager } from "@/components/blocks/list-range-pager";
import { readSection } from "@/lib/read-section";
import { productEditHref, productsListHref } from "@/lib/product-list-context";
import { formatIrr } from "@/lib/utils";
import type { Paginated, Product } from "@/lib/types";
import { BulkSelectCheckbox, BulkUnpublishSelection } from "@/components/blocks/bulk-unpublish-selection";
import { DataSectionError } from "./section-error";

type Props = { page: number; search: string; canEdit: boolean };
/** Read only this section; keep the authorized search form outside the wait. */
export async function ProductsResults({ page, search, canEdit }: Props) {
  const result = await readSection<Paginated<Product>>(`/products?page=${page}&search=${encodeURIComponent(search)}`);
  if (!result.ok) return <div className="lg:col-span-2"><DataSectionError title="محصولات دریافت نشدند" /></div>;
  return <ProductsTable data={result.data} page={page} search={search} canEdit={canEdit} />;
}

/** The existing table, empty states and pagination share one authoritative response. */
export function ProductsTable({ data, page, search, canEdit }: Props & { data: Paginated<Product> }) {
  const lastPage = Math.max(1, Math.ceil(data.total / data.page_size));
  const offset = (page - 1) * data.page_size;
  return <>
    <ListRangePager label="صفحه‌گردان فهرست محصولات"
      start={data.items.length ? offset + 1 : 0} end={data.items.length ? offset + data.items.length : 0}
      total={data.total}
      previous={page > 1 ? productsListHref(search, Math.min(page - 1, lastPage)) : undefined}
      next={page < lastPage && page < 100_000 ? productsListHref(search, page + 1) : undefined} />
    <div className="min-w-0 lg:col-span-2">
    <BulkUnpublishSelection key={`${page}:${search}`} entity="products"
    eligible={data.items.map((item) => item.id)}
    archivable={data.items.filter((item) => item.is_published).map((item) => item.id)}
    canArchive={canEdit}>
          <Table className="min-w-[40rem] [&_td]:px-3 [&_td]:py-1.5 [&_th]:h-9 [&_th]:px-3">
            <TableHeader className="bg-muted"><TableRow>
              <TableHead><BulkSelectCheckbox all /></TableHead>
              <TableHead>محصول</TableHead><TableHead>کد</TableHead>
              <TableHead>قیمت</TableHead><TableHead>موجودی</TableHead>
              <TableHead>انتشار</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {data.items.map(item => {
                const cells = <>
                  <TableCell><BulkSelectCheckbox id={item.id} /></TableCell>
                  <TableCell className="max-w-64 font-semibold">{canEdit
                    ? <RecordLink href={productEditHref(item.id, search)}>{item.name}</RecordLink>
                    : item.name}</TableCell>
                  <TableCell dir="ltr" className="text-start text-xs text-muted-foreground">{item.sku}</TableCell>
                  <TableCell className="whitespace-nowrap tabular">{formatIrr(item.price_irr)}</TableCell>
                  <TableCell className="tabular">{item.stock_quantity}</TableCell>
                  <TableCell><Badge tone={item.is_published ? "success" : "neutral"}>{item.is_published ? "منتشرشده" : "پیش‌نویس"}</Badge></TableCell>
                </>;
                const striped = "border-b border-border even:bg-muted/25 even:hover:bg-muted/45";
                return canEdit
                  ? <RecordClickArea as="tr" key={item.id} className={striped}>{cells}</RecordClickArea>
                  : <TableRow key={item.id} className={striped}>{cells}</TableRow>;
              })}
              {!data.items.length ? <TableRow><TableCell colSpan={6} className="py-12 text-center text-muted-foreground">{search ? "محصولی با این نام یا SKU پیدا نشد. جست‌وجو را تغییر دهید." : "هنوز محصولی ثبت نشده است."}</TableCell></TableRow> : null}
            </TableBody>
          </Table>
    </BulkUnpublishSelection>
    </div>
  </>;
}
