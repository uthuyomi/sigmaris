"use client";

import { DownloadIcon, LaptopIcon, SmartphoneIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
};

const isStandalone = () => {
  const navigatorWithStandalone = window.navigator as Navigator & { standalone?: boolean };

  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    navigatorWithStandalone.standalone === true
  );
};

export function PwaInstallPanel() {
  const [installPrompt, setInstallPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [installed, setInstalled] = useState(false);
  const [isAppleMobile, setIsAppleMobile] = useState(false);

  useEffect(() => {
    const initializeState = window.setTimeout(() => {
      setInstalled(isStandalone());
      setIsAppleMobile(/iphone|ipad|ipod/i.test(window.navigator.userAgent));
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
    if (installed) return "インストール済み";
    if (installPrompt) return "このブラウザでインストールできます";
    if (isAppleMobile) return "共有メニューからホーム画面に追加できます";
    return "ブラウザのインストールメニューから追加できます";
  }, [installPrompt, installed, isAppleMobile]);

  const install = async () => {
    if (!installPrompt) return;

    await installPrompt.prompt();
    const choice = await installPrompt.userChoice;
    if (choice.outcome === "accepted") {
      setInstalled(true);
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
          onClick={install}
          disabled={!installPrompt || installed}
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-full bg-stone-900 px-4 text-sm font-semibold text-stone-50 transition hover:bg-stone-700 disabled:cursor-not-allowed disabled:bg-stone-300 disabled:text-stone-500"
        >
          <LaptopIcon className="size-4" />
          PC版をインストール
        </button>
        <button
          type="button"
          onClick={install}
          disabled={!installPrompt || installed}
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-full border border-stone-900/15 bg-white px-4 text-sm font-semibold text-stone-800 transition hover:bg-stone-50 disabled:cursor-not-allowed disabled:border-stone-900/8 disabled:bg-stone-100 disabled:text-stone-400"
        >
          <SmartphoneIcon className="size-4" />
          スマホ版をインストール
        </button>
      </div>

      {installPrompt || installed ? null : (
        <p className="mt-3 text-xs leading-6 text-stone-500">
          iPhone / iPad は Safari の共有ボタンから「ホーム画面に追加」を選びます。
          PC はアドレスバーのインストールボタン、またはブラウザメニューから追加できます。
        </p>
      )}
    </section>
  );
}
