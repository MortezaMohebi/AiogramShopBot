import Link from "next/link";
export function StudioNav({
  id,
  current,
}: {
  id: string;
  current: "editor" | "preview" | "versions" | "settings";
}) {
  return (
    <nav
      aria-label="بخش‌های فرایند"
      className="mb-5 flex flex-wrap gap-2 text-sm"
    >
      {[
        { key: "editor", path: "", label: "ویرایشگر" },
        { key: "preview", path: "/preview", label: "شبیه‌ساز" },
        { key: "versions", path: "/versions", label: "نسخه‌ها" },
        { key: "settings", path: "/settings", label: "تنظیمات" },
      ].map((item) => (
        <Link
          key={item.key}
          href={`/studio/workflows/${id}${item.path}`}
          aria-current={current === item.key ? "page" : undefined}
          className={`rounded-md border px-4 py-2 focus-visible:outline-2 focus-visible:outline-ring ${current === item.key ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-muted"}`}
        >
          {item.label}
        </Link>
      ))}
      <Link href={`/studio/runtime?tab=publications&workflow_id=${id}`} className="rounded-md border border-border px-4 py-2 hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring">انتشار و اجرا</Link>
    </nav>
  );
}
