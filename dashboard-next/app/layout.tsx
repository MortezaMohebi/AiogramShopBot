import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { Providers } from "@/components/providers";
import { PwaInstallBanner } from "@/components/blocks/pwa-install-banner";
import { publicAppearance } from "../lib/pwa-appearance";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const settings = await publicAppearance();
  return {
    title: settings.name,
    description: "پنل فارسی مدیریت فروشگاه مشترک تلگرام و بله",
    robots: { index: false, follow: false },
    appleWebApp: { capable: true, title: settings.short_name, statusBarStyle: "default" },
    icons: { apple: [{ url: `/pwa/icon/apple?v=${settings.version}`, sizes: "180x180", type: "image/png" }] },
  };
}

export async function generateViewport(): Promise<Viewport> {
  const settings = await publicAppearance();
  return { themeColor: settings.theme_color, width: "device-width", initialScale: 1 };
}

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
