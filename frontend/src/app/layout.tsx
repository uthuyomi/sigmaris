// 役割: アプリ全体に適用するNext.jsルートレイアウト。

import { TooltipProvider } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { Metadata } from "next";
import { Geist, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

const geist = Geist({
  subsets: ["latin"],
  variable: "--font-sans",
});

const ibmPlexMono = IBM_Plex_Mono({
  variable: "--font-ibm-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "シグマリス",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [
      { url: "/images/icon/icon.ico", sizes: "48x48" },
      { url: "/images/icon/icon.png", sizes: "1254x1254", type: "image/png" },
    ],
    apple: [{ url: "/images/icon/icon.png", sizes: "1254x1254", type: "image/png" }],
  },
  appleWebApp: {
    capable: true,
    title: "シグマリス",
    statusBarStyle: "black-translucent",
  },
  description: "あなたの家庭支援AI",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="ja"
      className={cn(
        "h-full",
        "dark",
        "antialiased",
        ibmPlexMono.variable,
        "font-sans",
        geist.variable,
      )}
    >
      <body className="flex min-h-full flex-col bg-[#212121] text-[#ececec]">
        <TooltipProvider>{children}</TooltipProvider>
      </body>
    </html>
  );
}
