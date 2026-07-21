"use client";
// 役割: 「記憶」画面(/memory)の3タブ(現在地/変遷/生データ)を切り替える
// タブバー。デザイン統一 第四段階。
//
// 【デザイン(依頼書「静かで自然な遷移」)】
// ダッシュボード的な事務的な切り替えを避け、AppShell のナビと同系統の
// 落ち着いたセグメント(丸角ピル)にした。配色は既存トークン(bg-muted /
// bg-card / text-foreground / text-muted-foreground)で light/dark 両対応。
// アクティブなタブのみ静かに浮き上がる(bg-card + 淡い影)。
//
// タブ状態は URL の ?tab= で表現し、各タブは通常の <Link> 遷移(サーバー側で
// 該当タブ本文だけを取得・描画する)。active はサーバーの page.tsx から
// props で受け取るため、useSearchParams(要 Suspense)は使わない。

import { cn } from "@/lib/utils";
import Link from "next/link";

export type MemoryTabKey = "current" | "timeline" | "raw";

const TABS: { key: MemoryTabKey; label: string; href: string }[] = [
  // 並び順の判断根拠: 利用者が最もよく見る「現在地」を先頭に、次に時間変遷を
  // 眺める「変遷」、最後に運用/デバッグ向けの「生データ」を置く。
  { key: "current", label: "現在地", href: "/memory" },
  { key: "timeline", label: "変遷", href: "/memory?tab=timeline" },
  { key: "raw", label: "生データ", href: "/memory?tab=raw" },
];

export function MemoryTabs({ active }: { active: MemoryTabKey }) {
  return (
    <nav
      aria-label="記憶ビューの切り替え"
      className="inline-flex items-center gap-1 self-start rounded-full border border-border bg-muted p-1"
    >
      {TABS.map((tab) => {
        const isActive = tab.key === active;
        return (
          <Link
            key={tab.key}
            href={tab.href}
            prefetch={false}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "rounded-full px-4 py-1.5 text-sm font-medium transition",
              isActive
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
