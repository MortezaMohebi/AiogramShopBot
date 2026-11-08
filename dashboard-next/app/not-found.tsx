import Link from "next/link";
import { Button } from "@/components/ui/button";

/** A safe navigation fallback for unknown internal dashboard routes. */
export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-8 text-center">
      <p className="text-7xl font-black text-primary">۴۰۴</p>
      <h1 className="text-xl font-bold">صفحه مورد نظر پیدا نشد</h1>
      <p className="text-muted-foreground">ممکن است صفحه حذف شده یا دسترسی تغییر کرده باشد.</p>
      <Button asChild><Link href="/dashboard">بازگشت به داشبورد</Link></Button>
    </main>
  );
}
