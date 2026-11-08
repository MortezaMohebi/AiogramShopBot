"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { SectionRpcError, SectionRpcResult } from "@/lib/section-rpc";

interface SectionQuery<Q> {
  keys: readonly string[];
  read(params: Pick<URLSearchParams, "get">): Q;
  write(query: Q): URLSearchParams;
}

/** Keep URL, Back/Forward and section-only reads in sync, including stale replies. */
export function useSectionList<Q, T>(
  codec: SectionQuery<Q>, initialQuery: Q, initialData: T,
  read: (query: Q, signal: AbortSignal) => Promise<SectionRpcResult<T>>,
) {
  const params = useSearchParams();
  const key = codec.write(codec.read(params)).toString();
  const query = useMemo(() => codec.read(new URLSearchParams(key)), [codec, key]);
  const [generation, setGeneration] = useState(0);
  const [snapshot, setSnapshot] = useState<{
    key: string; generation: number; data: T; error: SectionRpcError | null;
  }>(() => ({ key: codec.write(initialQuery).toString(), generation: 0, data: initialData, error: null }));
  const pending = snapshot.key !== key || snapshot.generation !== generation;

  useEffect(() => {
    if (!pending) return;
    const controller = new AbortController();
    async function load() {
      let result: SectionRpcResult<T>;
      try {
        result = await read(query, controller.signal);
      } catch {
        result = { ok: false, code: "unavailable" };
      }
      if (controller.signal.aborted) return;
      setSnapshot(previous => result.ok
        ? { key, generation, data: result.data, error: null }
        : { ...previous, key, generation, error: result.code });
    }
    void load();
    return () => controller.abort();
  }, [generation, key, pending, query, read]);

  const navigate = useCallback((next: Q, replace = false) => {
    const url = new URL(window.location.href);
    if (codec.write(codec.read(url.searchParams)).toString() === codec.write(next).toString()) return;
    for (const name of codec.keys) url.searchParams.delete(name);
    for (const [name, value] of codec.write(next)) url.searchParams.set(name, value);
    const path = url.pathname + url.search + url.hash;
    if (replace) window.history.replaceState(null, "", path);
    else window.history.pushState(null, "", path);
  }, [codec]);

  return {
    key, query, data: snapshot.data, pending,
    error: pending ? null : snapshot.error,
    navigate,
    reload: () => setGeneration(value => value + 1),
  };
}
