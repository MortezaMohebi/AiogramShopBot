"use client";

import type { ReactNode } from "react";
import { DirectionProvider } from "@radix-ui/react-direction";
import { ThemeProvider } from "next-themes";

/** Maintain first-class Persian RTL direction and user-selectable color mode. */
export function Providers({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <DirectionProvider dir="rtl">{children}</DirectionProvider>
    </ThemeProvider>
  );
}
