import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { Providers } from "@/components/providers";
import { PwaInstallBanner } from "@/components/blocks/pwa-install-banner";
import "./globals.css";

export const metadata: Metadata = {
  title: "مدیریت فروشگاه | Telegram + Bale",
  description: "پنل فارسی مدیریت فروشگاه مشترک تلگرام و بله",
  robots: { index: false, follow: false },
  appleWebApp: { capable: true, title: "مدیریت فروشگاه", statusBarStyle: "default" },
  icons: { apple: [{ url: "/pwa/icon/apple", sizes: "180x180", type: "image/png" }] },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#146b66" },
    { media: "(prefers-color-scheme: dark)", color: "#0e141b" },
  ],
};

/** The entire admin UI and installed shadcn components run in Persian RTL. */
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="fa" dir="rtl" suppressHydrationWarning>
      <body className="min-h-screen antialiased">
        <Providers><PwaInstallBanner />{children}</Providers>
      </body>
    </html>
  );
}
