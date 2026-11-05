import Link from "next/link";
/** Keep Action discovery inside Studio while preserving the existing workflow routes. */
export function StudioHomeNav({
  current,
}: {
  current: "workflows" | "actions" | "runtime";
}) {
  return (
    <nav
      aria-label="بخش‌های Studio"
      className="mb-5 flex flex-wrap gap-2 text-sm"
    >
      {[
        { key: "workflows", href: "/studio/workflows", label: "فرایندها" },
        { key: "runtime", href: "/studio/runtime", label: "Runtime" },
        { key: "actions", href: "/studio/actions", label: "Action Catalog" },
      ].map((item) => (
        <Link
          key={item.key}
          href={item.href}
          aria-current={current === item.key ? "page" : undefined}
          className={`rounded-md border px-4 py-2 focus-visible:outline-2 focus-visible:outline-ring ${current === item.key ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-muted"}`}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}
