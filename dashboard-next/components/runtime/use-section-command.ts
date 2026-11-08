"use client";

import { useRef, useState } from "react";
import type { SectionRpcResult } from "@/lib/section-rpc";

/** Suppress duplicate submits and report uncertain writes without replay. */
export function useSectionCommand<Input, Output>(
  invoke: (input: Input) => Promise<SectionRpcResult<Output>>,
) {
  const active = useRef(false);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<SectionRpcResult<Output> | null>(null);

  async function run(input: Input): Promise<SectionRpcResult<Output> | null> {
    if (active.current) return null;
    active.current = true;
    setPending(true);
    setResult(null);
    let receipt: SectionRpcResult<Output>;
    try {
      receipt = await invoke(input);
    } catch {
      receipt = { ok: false, code: "outcome_unknown" };
    } finally {
      active.current = false;
      setPending(false);
    }
    setResult(receipt);
    return receipt;
  }

  return { pending, result, run, clear: () => setResult(null) };
}
