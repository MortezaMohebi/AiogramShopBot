import Link from "next/link";
import { currentStaff } from "@/lib/bridge";
import { McpWithdrawal } from "@/components/mcp/withdrawal";

/** Account withdrawal deliberately needs no StoreContext or Store layout. */
export default async function McpAccount({ searchParams }: {
  searchParams: Promise<{ grant?: string }>;
}) {
  const staff = await currentStaff();
  const query = await searchParams;
  const id = query.grant && /^[0-9a-f-]{36}$/i.test(query.grant) ? query.grant : "";
  return <main className="mx-auto min-h-screen max-w-3xl space-y-6 p-4 py-10 sm:p-8">
    <header className="space-y-3"><h1 className="text-2xl font-bold">لغو دسترسی MCP</h1>
      <p className="text-sm leading-7 text-muted-foreground">اگر دیگر به فروشگاه دسترسی ندارید، همچنان می‌توانید دسترسی اتصال متعلق به خودتان را لغو کنید.</p></header>
    <McpWithdrawal key={`${staff.id}:${id}`} initialId={id} />
    <nav className="flex flex-wrap gap-4 text-sm"><Link className="underline" href="/account">حساب کاربری</Link>
      <Link className="underline" href="/studio/mcp">اتصال‌های فروشگاه انتخاب‌شده</Link></nav>
  </main>;
}
