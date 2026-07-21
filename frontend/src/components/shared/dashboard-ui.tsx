// 役割: /memory・/timeline・/growth・/live に各ページ内でインライン重複定義
// されていた表示部品を、テーマ対応のトークンベースで一箇所に集約した共有
// コンポーネント群（デザイン統一 第一段階、docs/sigmaris/
// frontend_design_unification_report.md）。
//
// 【設計方針（判断根拠）】
// - 色は hex 直書きをやめ、globals.css で既に定義済みの CSS 変数トークン
//   （bg-card・bg-background・text-foreground・text-muted-foreground・
//   bg-primary・border-border 等）を使う。現状 :root と .dark が同値
//   （ダーク）のため、この置き換えによる見た目の変化はごく僅かで、ダークの
//   現行外観は維持される。将来 :root に light 値を入れる第二段階で、この
//   共有部品は自動的に light/dark 両対応になる（本タスクの土台整理の狙い）。
// - Linear/Claude.ai/Vercel を参照した「余白を大胆に・装飾控えめ」の方針に
//   沿い、パディング・行間をやや広げる微調整のみ加えた（大きな構造変更は
//   しない）。
// - #2a2a2a（旧Section背景）に厳密対応するトークンは存在しないため bg-card
//   （#2f2f2f）へ寄せた。依頼書が許容する「トークン化に伴う微妙な色差」に
//   該当する。
// - エラー表示の赤・注意色のオレンジ（#e07856）は意味を持つセマンティック
//   カラーで、既存トークンに対応が無いため据え置く（第二段階で検討）。

import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

// ─── ページ先頭のヒーローカード（Σアバター＋タイトル） ──────────────────
export function PageHero({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <section className="rounded-3xl border border-border bg-card px-6 py-7 sm:px-7">
      <div className="flex items-center gap-4">
        <div className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-primary text-2xl font-semibold text-primary-foreground">
          Σ
        </div>
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">{title}</h1>
          <p className="mt-1.5 text-sm leading-6 text-muted-foreground">{description}</p>
        </div>
      </div>
    </section>
  );
}

// ─── セクションカード ─────────────────────────────────────────────────
export function Section({
  title,
  description,
  action,
  children,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-3xl border border-border bg-card p-5 shadow-[0_18px_60px_-45px_rgba(0,0,0,0.75)] sm:p-6">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-foreground sm:text-lg">{title}</h2>
          <p className="mt-1.5 text-sm leading-6 text-muted-foreground">{description}</p>
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      {children}
    </section>
  );
}

// ─── バッジ ───────────────────────────────────────────────────────────
export function Badge({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border border-border bg-white/[0.06] px-2.5 py-1 text-xs font-medium text-foreground",
        className,
      )}
    >
      {children}
    </span>
  );
}

// ─── 確信度バー（0〜1 を進捗バーで表示） ──────────────────────────────
function clampConfidence(value: unknown): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.min(1, Math.max(0, numeric));
}

export function ConfidenceBar({
  value,
  label = "確信度",
}: {
  value: unknown;
  label?: string;
}) {
  const confidence = clampConfidence(value);
  const percent = Math.round(confidence * 100);

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{label}</span>
        <span>{confidence.toFixed(2)}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-white/10">
        <div className="h-full rounded-full bg-primary" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

// ─── 空状態 ───────────────────────────────────────────────────────────
export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-border bg-white/[0.03] px-4 py-5 text-sm text-muted-foreground">
      {children}
    </div>
  );
}

// ─── エラー状態（セマンティックな赤は据え置き） ──────────────────────
export function ErrorState({ message }: { message: string }) {
  return (
    <div className="rounded-2xl border border-red-400/20 bg-red-500/10 px-4 py-3 text-sm text-red-100">
      {message}
    </div>
  );
}
