import Link from "next/link";
import { notFound } from "next/navigation";
import { createRelayWorker } from "../actions";
import { PasswordActionForm } from "@/components/blocks/password-action-form";
import { PageHeading } from "@/components/blocks/page-heading";
import { RelayWorkerFields } from "@/components/blocks/relay-worker-fields";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { currentStaff, optionalStoreRead } from "@/lib/bridge";
import { relayMessage, type RelayWorkersSnapshot } from "@/lib/relay-pool";

export default async function NewRelayWorkerPage({ searchParams }: {
  searchParams: Promise<{ error?: string }>;
}) {
  if ((await currentStaff()).role !== "superadmin") notFound();
  const data = await optionalStoreRead<RelayWorkersSnapshot>("/relay-workers");
  if (!data) notFound();
  const { error } = await searchParams;
  return <>
    <PageHeading title="Worker جدید" action={<Button asChild variant="outline" size="sm"><Link href="/relay-workers">بازگشت به فهرست</Link></Button>} />
    <Card><CardContent className="space-y-4 pt-5">
      {error && <p role="alert" className="text-sm text-destructive">{relayMessage(error)}</p>}
      {!data.approved_origins.length ? <p className="text-sm">ابتدا نشانی Worker را در سرور مجاز کنید. <Link href="/relay-workers#relay-setup" className="underline">راهنمای اتصال</Link></p> :
        <PasswordActionForm action={createRelayWorker} when="required" includePassword={false} className="grid gap-4 sm:grid-cols-2">
          <RelayWorkerFields />
          <label className="space-y-2 text-sm sm:col-span-2">نشانی Worker
            <Input name="origin" type="url" dir="ltr" maxLength={300} required list="allowed-worker-origins" placeholder="https://relay.example.workers.dev" />
            <datalist id="allowed-worker-origins">{data.approved_origins.map(origin => <option key={origin} value={origin} />)}</datalist>
          </label>
          <div><Button type="submit">ثبت Worker</Button></div>
        </PasswordActionForm>}
    </CardContent></Card>
  </>;
}
