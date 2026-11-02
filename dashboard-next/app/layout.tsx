import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Providers } from "@/components/providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "مدیریت فروشگاه | Telegram + Bale",
  description: "پنل فارسی مدیریت فروشگاه مشترک تلگرام و بله",
  robots: { index: false, follow: false },
};

/** The entire admin UI and installed shadcn components run in Persian RTL. */
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="fa" dir="rtl" suppressHydrationWarning>
      <body className="min-h-screen antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
