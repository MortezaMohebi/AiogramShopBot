"use client";

import { deleteCampaignMedia } from "@/app/(console)/campaigns/actions";
import { DisplayOrderControls } from "@/components/blocks/display-order-controls";
import { useDisplayOrder } from "@/components/blocks/use-display-order";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { OrderHandle, orderOperations } from "@/components/ui/order-handle";

export interface CampaignFile {
  id: number;
  filename: string;
  kind: string;
  size_bytes: number;
  caption: string | null;
}

export function CampaignMediaOrder({ campaignId, files, editable }: {
  campaignId: number; files: CampaignFile[]; editable: boolean;
}) {
  const order = useDisplayOrder(files, "campaign-media", campaignId);
  if (!files.length) return <p className="text-sm text-muted-foreground">هیچ فایلی به کمپین پیوست نشده است.</p>;
  return <>
    <div className="overflow-x-auto rounded-md border">
      <table data-order-list className="w-full min-w-96 text-sm">
        <thead className="bg-muted"><tr><th scope="col" className="p-2 text-start">فایل</th>
          <th scope="col" className="p-2 text-start">توضیح</th><th scope="col" className={orderOperations}>عملیات</th></tr></thead>
        <tbody>{order.rows.map((file) => <tr key={file.id} data-order-row={String(file.id)} className="border-t">
          <td><div className="flex items-center gap-2 p-1">
            {editable && <OrderHandle id={String(file.id)} label={file.filename} ids={order.ids} move={order.move} disabled={order.pending} />}
            <div className="min-w-0"><bdi className="break-all">{file.filename}</bdi>
              <p className="text-xs text-muted-foreground">{file.kind} · {(file.size_bytes / 1_000_000).toFixed(1)} MB</p>
            </div>
          </div></td>
          <td className="px-2"><span dir="auto">{file.caption || "—"}</span></td>
          <td className={orderOperations}><div className="flex flex-wrap items-center gap-2 py-1">
            <a className="text-primary underline" target="_blank" rel="noopener noreferrer"
              href={`/api/admin/preview/campaign/${file.id}`}>پیش‌نمایش</a>
            {editable && <details>
              <summary className="cursor-pointer text-destructive">حذف</summary>
              <form action={deleteCampaignMedia} className="flex flex-wrap items-center gap-1 py-2">
                <input type="hidden" name="campaign_id" value={campaignId} />
                <input type="hidden" name="media_id" value={file.id} />
                <Input name="confirmation" required dir="ltr" placeholder="DELETE_DRAFT_ATTACHMENT"
                  aria-label="عبارت تأیید حذف" className="w-52 text-xs" />
                <Button type="submit" size="sm" variant="destructive" disabled={order.pending}>حذف فایل</Button>
              </form>
            </details>}
          </div></td>
        </tr>)}</tbody>
      </table>
    </div>
    {editable && <DisplayOrderControls order={order} />}
  </>;
}
