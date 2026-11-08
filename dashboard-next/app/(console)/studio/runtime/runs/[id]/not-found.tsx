import Link from "next/link";
export default function MissingRun() {
  return <div className="space-y-4 rounded-xl border bg-card p-6">
  <h1 className="text-xl font-bold">اجرا در دسترس نیست</h1>
  <p className="text-sm leading-7 text-muted-foreground">این شناسه در فروشگاه جاری پیدا نشد یا برای این نشست در دسترس نیست.</p>
  <Link className="text-sm text-primary underline" href="/studio/runtime?tab=runs">فهرست اجراها</Link>
</div>;
}
