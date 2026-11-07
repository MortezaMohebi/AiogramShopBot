import Link from "next/link";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/** Explain an existing backend scope restriction without changing its authority. */
export function StoreScopeNotice({ title }: { title: string }) {
  return <div data-store-scope-unavailable="true">
    <PageHeading title={title} />
    <Card className="max-w-2xl">
      <CardHeader><CardTitle>انتخاب فروشگاه</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm leading-7 text-muted-foreground">
          برای استفاده از این بخش، فقط فروشگاه اصلی را از منوی بالای صفحه انتخاب کنید.
          اگر آن را نمی‌بینید، دسترسی خود را با مدیر حساب بررسی کنید.
        </p>
        <Button asChild variant="outline"><Link href="/bots">تنظیمات ربات‌ها</Link></Button>
      </CardContent>
    </Card>
  </div>;
}
