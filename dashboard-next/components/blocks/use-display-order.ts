"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { saveDisplayOrder } from "@/app/(console)/display-order-actions";
import { useSectionCommand } from "@/components/runtime/use-section-command";

export function useDisplayOrder<T extends { id: number }>(items: T[],
  kind: "categories" | "product-media" | "campaign-media", parentId: number | null = null) {
  const incoming = items.map((item) => item.id);
  const key = incoming.join(",");
  const [saved, setSaved] = useState<{ key: string; ids: number[] }>();
  const [draft, setDraft] = useState<{ key: string; ids: number[] }>();
  const [announcement, setAnnouncement] = useState("");
  const baseline = saved?.key === key ? saved.ids : incoming;
  const ids = draft?.key === key ? draft.ids : baseline;
  const dirty = ids.some((id, index) => id !== baseline[index]);
  const byId = new Map(items.map((item) => [item.id, item]));
  const command = useSectionCommand((next: number[]) => saveDisplayOrder(kind, parentId, baseline, next));
  const router = useRouter();
  const needsRefresh = command.result?.ok === false &&
    (command.result.code === "conflict" || command.result.code === "outcome_unknown");

  function move(from: string, to: string) {
    const start = ids.indexOf(Number(from));
    const end = ids.indexOf(Number(to));
    if (command.pending || needsRefresh || start < 0 || end < 0 || start === end) return;
    const next = [...ids];
    next.splice(end, 0, ...next.splice(start, 1));
    setDraft({ key, ids: next });
    setAnnouncement(`ردیف به جایگاه ${(end + 1).toLocaleString("fa-IR")} منتقل شد.`);
    command.clear();
  }

  async function save() {
    if (!dirty) return true;
    if (needsRefresh || command.pending) return false;
    const result = await command.run(ids);
    if (result?.ok) {
      setSaved({ key, ids: result.data.ids });
      setDraft(undefined);
    }
    return result?.ok === true;
  }

  return {
    rows: ids.flatMap((id) => byId.get(id) ?? []), ids: ids.map(String), move, save, dirty, announcement,
    pending: command.pending, discard: () => { setDraft(undefined); command.clear(); },
    needsRefresh, refresh: () => {
      setDraft(undefined);
      setSaved(undefined);
      command.clear();
      router.refresh();
    },
    message: command.result?.ok ? "ترتیب ذخیره شد."
      : command.result?.code === "conflict" ? "فهرست تغییر کرده است. فهرست تازه را بررسی کنید."
      : command.result?.code === "permission_denied" ? "اجازهٔ تغییر ترتیب این فهرست را ندارید."
      : command.result?.code === "session_expired" ? "نشست شما پایان یافته است. دوباره وارد شوید."
      : command.result ? "ذخیرهٔ ترتیب تأیید نشد. وضعیت فهرست را بررسی کنید." : "",
    error: command.result?.ok === false,
  };
}
