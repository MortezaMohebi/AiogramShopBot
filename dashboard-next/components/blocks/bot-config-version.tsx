"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

const Context = createContext<{
  version: number;
  advance: (from: number, to: number) => void;
} | null>(null);

export function BotConfigVersionProvider({ initialVersion, children }: {
  initialVersion: number;
  children: ReactNode;
}) {
  const [version, setVersion] = useState(initialVersion);
  return <Context.Provider value={{
    version,
    // Other forms may advance only across this page's own confirmed write.
    advance: (from, to) => setVersion(current => current === from ? to : current),
  }}>{children}</Context.Provider>;
}

export function useBotConfigVersion() {
  const value = useContext(Context);
  if (!value) throw new Error("Bot configuration version provider is missing.");
  return value;
}

export function BotConfigVersionField() {
  return <input type="hidden" name="expected_version" value={useBotConfigVersion().version} />;
}

export function BotConfigVersionValue() {
  return <>{useBotConfigVersion().version}</>;
}
