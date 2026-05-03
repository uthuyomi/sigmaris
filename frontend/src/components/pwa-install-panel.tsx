"use client";

import { DownloadIcon, LaptopIcon, SmartphoneIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
};

type InstallGuide = "desktop" | "mobile" | null;

const isStandalone = () => {
  const navigatorWithStandalone = window.navigator as Navigator & { standalone?: boolean };

  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    navigatorWithStandalone.standalone === true
  );
};

const detectAppleMobile = () => /iphone|ipad|ipod/i.test(window.navigator.userAgent);

export function PwaInstallPanel() {
  const [installPrompt, setInstallPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [installed, setInstalled] = useState(false);
  const [isAppleMobile, setIsAppleMobile] = useState(false);
  const [guide, setGuide] = useState<InstallGuide>(null);

  useEffect(() => {
    const initializeState = window.setTimeout(() => {
      setInstalled(isStandalone());
      setIsAppleMobile(detectAppleMobile());
    }, 0);

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }

    const handleBeforeInstallPrompt = (event: Event) => {
      event.preventDefault();
      setInstallPrompt(event as BeforeInstallPromptEvent);
    };
    const handleInstalled = () => {
      setInstalled(true);
      setInstallPrompt(null);
      setGuide(null);
    };

    window.addEventListener("beforeinstallprompt", handleBeforeInstallPrompt);
    window.addEventListener("appinstalled", handleInstalled);

    return () => {
      window.clearTimeout(initializeState);
      window.removeEventListener("beforeinstallprompt", handleBeforeInstallPrompt);
      window.removeEventListener("appinstalled", handleInstalled);
    };
  }, []);

  const statusText = useMemo(() => {
    if (installed) return "インストール済みです。";
    if (installPrompt) return "このブラウザではボタンからインストールできます。";
    if (isAppleMobile) return "iPhone / iPad は共有メニューからホーム画面に追加できます。";
    return "ボタンを押すと、この環境での追加方法を表示します。";
  }, [installPrompt, installed, isAppleMobile]);

  const runInstall = async (nextGuide: Exclude<InstallGuide, null>) => {
    if (installed) return;

    if (!installPrompt) {
      setGuide(nextGuide);
      return;
    }

    await installPrompt.prompt();
    const choice = await installPrompt.userChoice;
    if (choice.outcome === "accepted") {
      setInstalled(true);
      setGuide(null);
    } else {
      setGuide(nextGuide);
    }
    setInstallPrompt(null);
  };

  return (
    <section
      id="install"
      className="mt-8 max-w-3xl rounded-[24px] border border-stone-900/10 bg-white/82 p-4 shadow-[0_22px_70px_-52px_rgba(41,37,36,0.75)] backdrop-blur sm:p-5"
      aria-label="ブラウザアプリとしてインストール"
    >
      <div className="flex items-start gap-3">
        <span className="inline-flex size-11 shrink-0 items-center justify-center rounded-2xl bg-stone-900 text-stone-50">
          <DownloadIcon className="size-5" />
        </span>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-stone-900">ブラウザアプリとして使う</p>
          <p className="mt-1 text-xs leading-6 text-stone-600">
            アイコンから開くと、未ログインならログインページへ、ログイン済みならチャットへ移動します。
          </p>
          <p className="mt-2 text-xs font-medium text-stone-500">{statusText}</p>
        </div>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        <button
          type="button"
          onClick={() => runInstall("desktop")}
          disabled={installed}
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-full bg-stone-900 px-4 text-sm font-semibold text-stone-50 transition hover:bg-stone-700 disabled:cursor-not-allowed disabled:bg-stone-300 disabled:text-stone-500"
        >
          <LaptopIcon className="size-4" />
          PC版を追加
        </button>
        <button
          type="button"
          onClick={() => runInstall("mobile")}
          disabled={installed}
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-full border border-stone-900/15 bg-white px-4 text-sm font-semibold text-stone-800 transition hover:bg-stone-50 disabled:cursor-not-allowed disabled:border-stone-900/8 disabled:bg-stone-100 disabled:text-stone-400"
        >
          <SmartphoneIcon className="size-4" />
          スマホ版を追加
        </button>
      </div>

      {guide ? (
        <div className="mt-4 rounded-[18px] border border-stone-900/10 bg-stone-50 px-4 py-3 text-xs leading-6 text-stone-600">
          <p className="font-semibold text-stone-800">
            {guide === "desktop" ? "PCで追加する方法" : "スマホで追加する方法"}
          </p>
          {guide === "desktop" ? (
            <ul className="mt-2 list-disc space-y-1 pl-4">
              <li>Chrome / Edge はアドレスバー右側のインストールアイコンを押します。</li>
              <li>見つからない場合は、ブラウザメニューから「インストール」または「アプリをインストール」を選びます。</li>
              <li>Firefox など未対応の環境では、ブックマークかホーム画面ショートカットで代用します。</li>
            </ul>
          ) : (
            <ul className="mt-2 list-disc space-y-1 pl-4">
              <li>iPhone / iPad は Safari の共有ボタンから「ホーム画面に追加」を選びます。</li>
              <li>Android Chrome はブラウザメニューから「アプリをインストール」または「ホーム画面に追加」を選びます。</li>
              <li>アプリ起動後は、ログイン状態に応じてログインページまたはチャットへ移動します。</li>
            </ul>
          )}
        </div>
      ) : null}
    </section>
  );
}
