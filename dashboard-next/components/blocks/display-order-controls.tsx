"use client";

import { DraftActions } from "@/components/ui/draft-actions";
import { useDraftNavigation } from "@/components/blocks/use-draft-navigation";
import { Button } from "@/components/ui/button";
import type { useDisplayOrder } from "@/components/blocks/use-display-order";

export function DisplayOrderControls({ order }: { order: ReturnType<typeof useDisplayOrder> }) {
  useDraftNavigation(order.dirty || order.pending, order.save);
  return <div className="flex flex-wrap items-center gap-2">
    <span className="sr-only" role="status">{order.announcement}</span>
    {order.needsRefresh && <Button type="button" variant="outline" size="sm" onClick={order.refresh}>تازه‌کردن فهرست</Button>}
    {!order.needsRefresh && <DraftActions dirty={order.dirty} pending={order.pending}
      onSave={() => void order.save()} onDiscard={order.discard} />}
    {order.message && <p role={order.error ? "alert" : "status"} className={order.error ? "text-sm text-destructive" : "text-sm text-muted-foreground"}>{order.message}</p>}
  </div>;
}
