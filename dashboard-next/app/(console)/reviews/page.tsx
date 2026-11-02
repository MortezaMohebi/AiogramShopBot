import { notFound } from "next/navigation";
import { PageHeading } from "@/components/blocks/page-heading";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { Paginated } from "@/lib/types";

type Review = {
  id: number; product_id: number; product_name: string;
  text: string | null; has_file: boolean; is_approved: boolean;
};

/** Read-only moderation queue; approval still uses protected legacy controls. */
export default async function ReviewsPage() {
  const staff = await currentStaff();
  if (!["superadmin", "content"].includes(staff.role)) notFound();
  const reviews = await adminFetch<Paginated<Review>>("/testimonials?page=1");
  return (
    <div>
      <PageHeading title="رضایت مشتریان" description="متن و رسانه‌ها ابتدا تأییدنشده ثبت می‌شوند؛ انتشار تنها پس از بررسی مدیر محتوا مجاز است." />
      <Card><CardContent className="pt-5">
        <Table>
          <TableHeader><TableRow><TableHead>محصول</TableHead><TableHead>متن</TableHead><TableHead>رسانه</TableHead><TableHead>انتشار</TableHead></TableRow></TableHeader>
          <TableBody>
            {reviews.items.map((item) => (
              <TableRow key={item.id}>
                <TableCell className="font-medium">{item.product_name}</TableCell>
                <TableCell className="max-w-xs truncate">{item.text || "رضایت رسانه‌ای"}</TableCell>
                <TableCell>{item.has_file ? "دارد" : "ندارد"}</TableCell>
                <TableCell><Badge tone={item.is_approved ? "success" : "warning"}>{item.is_approved ? "تأییدشده" : "در انتظار بررسی"}</Badge></TableCell>
              </TableRow>
            ))}
            {!reviews.items.length ? <TableRow><TableCell colSpan={4} className="py-8 text-center text-muted-foreground">رضایتی ثبت نشده است.</TableCell></TableRow> : null}
          </TableBody>
        </Table>
        <p className="mt-5 text-xs text-muted-foreground">ثبت فایل و تأیید نهایی رسانه در این شاخه همچنان از مسیر محافظت‌شدهٔ SQLAdmin انجام می‌شود.</p>
      </CardContent></Card>
    </div>
  );
}
