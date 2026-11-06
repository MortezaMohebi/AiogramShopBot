import { AccountPanel } from "@/components/blocks/account-panel";
import { PageHeading } from "@/components/blocks/page-heading";
import { adminFetch } from "@/lib/bridge";
import type { AccountData } from "@/lib/account-control";
/** Every authenticated role can manage its own account, never another user's. */
export default async function AccountPage() {
  const account = await adminFetch<AccountData>("/account");
  return <div className="mx-auto max-w-5xl space-y-6"><PageHeading title="حساب من" /><AccountPanel initial={account} /></div>;
}
