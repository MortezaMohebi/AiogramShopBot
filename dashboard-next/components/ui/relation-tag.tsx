import { X } from "lucide-react";

export function RelationTag({ label, onEdit, onRemove, removeLabel, disabled }: {
  label: string;
  onEdit?: () => void;
  onRemove: () => void;
  removeLabel: string;
  disabled?: boolean;
}) {
  return <span className="inline-flex max-w-full items-center rounded-full bg-accent text-accent-foreground">
    {onEdit ? <button type="button" onClick={onEdit} disabled={disabled} className="min-h-7 min-w-0 truncate rounded-full px-2 hover:underline"
      aria-label={`ویرایش ${label}`}><bdi>{label}</bdi></button>
      : <bdi className="min-w-0 truncate px-2 text-xs">{label}</bdi>}
    <button type="button" onClick={onRemove} disabled={disabled} aria-label={removeLabel} title={removeLabel}
      className="grid size-7 shrink-0 place-items-center rounded-full hover:bg-background disabled:opacity-50">
      <X aria-hidden="true" className="size-3.5" />
    </button>
  </span>;
}
