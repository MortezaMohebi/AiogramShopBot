"use client";

import { AlertTriangle, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/** Friendly failure state without disclosing backend/API stack traces. */
export default function DashboardError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="mx-auto max-w-xl py-16">
      <Card>
        <CardHeader>
          <div className="mb-4 grid size-12 place-items-center rounded-xl bg-amber-500/10 text-amber-700 dark:text-amber-300">
            <AlertTriangle className="size-6" />
          </div>
          <CardTitle>داده‌ها در دسترس نیستند</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <p className="text-sm leading-7 text-muted-foreground">
            اتصال امن داشبورد به سرویس اصلی برقرار نشد یا مجوز این بخش تغییر کرده است.
            هیچ عدد آزمایشی به‌جای اطلاعات واقعی نمایش داده نمی‌شود.
          </p>
          <Button type="button" onClick={reset}><RotateCcw /> تلاش دوباره</Button>
        </CardContent>
      </Card>
    </div>
  );
}
