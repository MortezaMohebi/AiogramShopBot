import { adminFetch } from "@/lib/bridge";
import { PageHeading } from "@/components/blocks/page-heading";
import { ActionCatalog } from "@/components/actions/catalog";
import { StudioHomeNav } from "@/components/workflows/studio-home-nav";
import type { ActionCatalogPage } from "@/lib/actions/types";
import type { BotChoice, ChoicePage } from "@/lib/workflows/types";
/** Server-owned Store/permission props reset contextual inspection after a scope change. */
export default async function ActionsPage() {
  const [data, bots] = await Promise.all([
    adminFetch<ActionCatalogPage>("/actions"),
    adminFetch<ChoicePage<BotChoice>>("/actions/bots"),
  ]);
  return (
    <div className="min-w-0">
      <StudioHomeNav current="actions" />
      <PageHeading
        title="Action Catalog"
        description="قراردادها، اثر جانبی و دسترسی Actionها را بررسی کنید و خواندن کاتالوگ را بدون تغییر داده امتحان کنید."
      />
      <ActionCatalog
        key={`${data.store_id}:${data.can_inspect_data}`}
        initial={data}
        bots={bots}
      />
    </div>
  );
}
