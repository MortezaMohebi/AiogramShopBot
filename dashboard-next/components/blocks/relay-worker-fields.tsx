import { Input } from "@/components/ui/input";
import type { RelayWorker } from "@/lib/relay-pool";

export function RelayWorkerFields({ worker }: { worker?: RelayWorker }) {
  return <>
    <label className="space-y-2 text-sm">نام نمایشی
      <Input name="name" maxLength={160} required defaultValue={worker?.name} />
    </label>
    <label className="space-y-2 text-sm">شناسهٔ داخلی
      <Input name="slug" dir="ltr" pattern="[a-z][a-z0-9\-]{2,63}" minLength={3} maxLength={64}
        required defaultValue={worker?.slug} placeholder="relay-tehran" />
    </label>
    <label className="space-y-2 text-sm">سقف درخواست بر ثانیه
      <Input name="max_rps" type="number" min={1} max={20} defaultValue={worker?.max_rps ?? 5} required />
    </label>
    <label className="space-y-2 text-sm">سقف درخواست هم‌زمان
      <Input name="max_inflight" type="number" min={1} max={50} defaultValue={worker?.max_inflight ?? 10} required />
    </label>
  </>;
}
