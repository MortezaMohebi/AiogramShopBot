import { redirect } from "next/navigation";
import { OwnerSetupForm } from "@/components/blocks/owner-setup-form";
import { firstOwnerPending } from "@/lib/owner-setup";

export const dynamic = "force-dynamic";

export default async function SetupPage() {
  const pending = await firstOwnerPending();
  if (pending === false) redirect("/login");

  return (
    <main className="flex min-h-dvh items-center justify-center px-5 py-10">
      <section aria-labelledby="setup-title" className="w-full max-w-md space-y-5">
        <h1 id="setup-title" className="text-2xl font-semibold">ساخت اولین مدیر</h1>
        {pending === true ? <OwnerSetupForm /> : (
          <p role="alert" className="text-muted-foreground">
            وضعیت راه‌اندازی در دسترس نیست. صفحه را دوباره بارگذاری کنید.
          </p>
        )}
      </section>
    </main>
  );
}
