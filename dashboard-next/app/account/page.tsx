import Link from "next/link";
import { AccountPanel } from "@/components/blocks/account-panel";
import { LogoutControl } from "@/components/blocks/logout-control";
import { PageHeading } from "@/components/blocks/page-heading";
import { ThemeToggle } from "@/components/blocks/theme-toggle";
import { adminFetch } from "@/lib/bridge";
import type { AccountData } from "@/lib/account-control";
/** Revalidate the personal session without requiring Store access or completed MFA. */
export default async function AccountPage() {
  const account = await adminFetch<AccountData>("/account");
  return <div className="min-h-dvh bg-background text-foreground">
    <header className="border-b">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-3">
        <Link href="/dashboard" className="rounded-md px-3 py-2 text-sm font-medium hover:bg-muted">بازگشت به داشبورد</Link>
        <div className="flex items-center gap-2"><ThemeToggle /><LogoutControl /></div>
      </div>
    </header>
    <main className="mx-auto max-w-5xl space-y-6 px-4 py-6 md:py-10">
      <PageHeading title="حساب من" /><AccountPanel initial={account} />
    </main>
  </div>;
}
