import type { ReactNode } from "react";

/** Consistent dashboard-block heading with optional contextual action. */
export function PageHeading({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-7 flex flex-wrap items-start justify-between gap-4">
      <div className="space-y-2">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{title}</h1>
        <p className="max-w-2xl text-sm leading-7 text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  );
}
