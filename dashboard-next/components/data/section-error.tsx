import { ReadRefresh } from "./refresh";

/** A failed read is neither an empty result nor proof that a mutation failed. */
export function DataSectionError({ title }: { title: string }) {
  return <section className="space-y-3 rounded-xl border bg-card p-5">
    <h2 className="font-semibold">{title}</h2>
    <p role="alert" className="text-sm leading-7 text-muted-foreground">اطلاعات این بخش دریافت نشد. دوباره تلاش کنید.</p>
    <ReadRefresh />
  </section>;
}
