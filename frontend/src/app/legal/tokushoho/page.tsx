import type { Metadata } from "next";
import Link from "next/link";
import { PRO_MONTHLY_PRICE_JPY } from "@/lib/stripe";

export const metadata: Metadata = {
  title: "特定商取引法に基づく表記 | シグマリス",
  description: "シグマリス Proの特定商取引法に基づく表記です。",
};

const disclosureRows = [
  ["販売事業者", "シグマリス"],
  ["運営責任者", "安崎 海星"],
  ["所在地", "〒007-0842 北海道札幌市東区北四十二条東2丁目1-18 パインビレッジ2-12号"],
  ["メールアドレス", "kaiseif4e@gmail.com"],
  ["電話番号", "請求があった場合、遅滞なく開示いたします。"],
  ["販売価格", `シグマリス Pro 月額${PRO_MONTHLY_PRICE_JPY.toLocaleString("ja-JP")}円（税込）`],
  [
    "商品代金以外の必要料金",
    "インターネット接続料金、通信料金その他サービス利用に必要な費用はお客様の負担となります。",
  ],
  ["支払方法", "クレジットカード決済（Stripe）"],
  ["支払時期", "初回申込時に決済され、以後は契約更新日に月額料金が決済されます。"],
  ["サービス提供時期", "決済完了後、ただちにPro機能をご利用いただけます。"],
  [
    "返品・キャンセル",
    "デジタルサービスの性質上、決済完了後の返金には原則として応じられません。解約後も契約期間の終了まではPro機能をご利用いただけます。",
  ],
  ["解約方法", "アプリ内の設定画面からStripeの請求管理画面へ進み、いつでも解約できます。"],
  [
    "動作環境",
    "最新版の主要ブラウザ（Chrome、Safari、Edge、Firefox等）での利用を推奨します。",
  ],
] satisfies Array<[string, string]>;

export default function TokushohoPage() {
  return (
    <main className="min-h-screen bg-[#f7f2e8] px-4 py-8 text-stone-900 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-4xl">
        <Link
          href="/"
          className="inline-flex rounded-full border border-stone-900/10 bg-white px-4 py-2 text-sm font-semibold text-stone-700 transition hover:bg-stone-50"
        >
          シグマリスへ戻る
        </Link>

        <section className="mt-8 rounded-[28px] border border-stone-900/10 bg-white p-5 shadow-[0_30px_80px_-60px_rgba(41,37,36,0.75)] sm:p-8">
          <p className="text-xs font-medium uppercase tracking-[0.28em] text-stone-500">
            Legal Notice
          </p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
            特定商取引法に基づく表記
          </h1>
          <p className="mt-4 text-sm leading-7 text-stone-600">
            シグマリス Proの提供に関する表示です。内容に変更がある場合は、必要に応じて本ページを更新します。
          </p>

          <div className="mt-8 overflow-hidden rounded-2xl border border-stone-900/10">
            {disclosureRows.map(([label, value]) => (
              <div
                key={label}
                className="grid gap-2 border-b border-stone-900/10 px-4 py-4 last:border-b-0 sm:grid-cols-[13rem_1fr] sm:gap-5"
              >
                <dt className="text-sm font-semibold text-stone-950">{label}</dt>
                <dd className="text-sm leading-7 text-stone-600">{value}</dd>
              </div>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
