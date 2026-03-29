"use client";

import type { ImportCandidate } from "@/lib/import/schema";
import { useState } from "react";

type PreviewResponse = {
  sourceType: "sheet" | "image";
  sourceLabel: string;
  extracted: {
    summary: string;
    candidates: ImportCandidate[];
  };
};

export function ImportEntryPanel() {
  const [sheetUrl, setSheetUrl] = useState("");
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [loading, setLoading] = useState<null | "sheet" | "image" | "commit">(null);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const analyzeWithSheet = async () => {
    setLoading("sheet");
    setStatus(null);

    try {
      const formData = new FormData();
      formData.append("sheetUrl", sheetUrl);

      const res = await fetch("/api/import/preview", {
        method: "POST",
        body: formData,
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "シート読み取りに失敗しました。");

      setPreview(data);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "シート読み取りに失敗しました。");
    } finally {
      setLoading(null);
    }
  };

  const analyzeWithImage = async () => {
    if (!imageFile) return;

    setLoading("image");
    setStatus(null);

    try {
      const formData = new FormData();
      formData.append("image", imageFile);

      const res = await fetch("/api/import/preview", {
        method: "POST",
        body: formData,
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "画像解析に失敗しました。");

      setPreview(data);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "画像解析に失敗しました。");
    } finally {
      setLoading(null);
    }
  };

  const commitToGoogleCalendar = async () => {
    if (!preview?.extracted.candidates.length) return;

    setLoading("commit");
    setStatus(null);

    try {
      const res = await fetch("/api/import/commit", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          target: "google-calendar",
          candidates: preview.extracted.candidates,
        }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Google Calendar 反映に失敗しました。");

      setStatus(`Google カレンダーへ ${data.createdCount} 件反映したよ。`);
    } catch (error) {
      setStatus(
        error instanceof Error ? error.message : "Google Calendar 反映に失敗しました。",
      );
    } finally {
      setLoading(null);
    }
  };

  return (
    <aside className="space-y-4">
      <section className="rounded-[32px] border border-stone-900/10 bg-white/75 p-5 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur">
        <p className="text-xs uppercase tracking-[0.3em] text-stone-500">Import entry</p>
        <h2 className="mt-2 text-lg font-semibold text-stone-900">
          URL か画像から予定候補を作る
        </h2>

        <div className="mt-4 space-y-4">
          <div className="rounded-[24px] border border-stone-900/10 bg-stone-50 p-4">
            <p className="text-sm font-semibold text-stone-900">Google Sheets URL</p>
            <input
              value={sheetUrl}
              onChange={(e) => setSheetUrl(e.target.value)}
              placeholder="https://docs.google.com/spreadsheets/d/..."
              className="mt-3 w-full rounded-2xl border border-stone-900/10 bg-white px-4 py-3 text-sm outline-none"
            />
            <button
              type="button"
              disabled={!sheetUrl || loading !== null}
              onClick={analyzeWithSheet}
              className="mt-3 w-full rounded-full bg-stone-900 px-4 py-3 text-sm font-semibold text-stone-50 transition hover:bg-stone-800 disabled:opacity-50"
            >
              {loading === "sheet" ? "読み取り中..." : "シートを解析"}
            </button>
          </div>

          <div className="rounded-[24px] border border-stone-900/10 bg-stone-50 p-4">
            <p className="text-sm font-semibold text-stone-900">画像ファイル</p>
            <input
              type="file"
              accept="image/*"
              onChange={(e) => setImageFile(e.target.files?.[0] ?? null)}
              className="mt-3 block w-full text-sm text-stone-700"
            />
            <button
              type="button"
              disabled={!imageFile || loading !== null}
              onClick={analyzeWithImage}
              className="mt-3 w-full rounded-full bg-stone-900 px-4 py-3 text-sm font-semibold text-stone-50 transition hover:bg-stone-800 disabled:opacity-50"
            >
              {loading === "image" ? "解析中..." : "画像を解析"}
            </button>
          </div>
        </div>
      </section>

      <section className="rounded-[32px] border border-stone-900/10 bg-stone-900 p-5 text-stone-50">
        <p className="text-xs uppercase tracking-[0.3em] text-stone-400">Message examples</p>
        <ul className="mt-3 space-y-3 text-sm leading-7 text-stone-300">
          <li>このシートURLを読んで、私の勤務だけ候補にして</li>
          <li>この画像から来週分を取り込んで</li>
          <li>休憩時間は除いて Google カレンダーに入れたい</li>
          <li>まず予定候補だけ出して。まだ登録しないで</li>
        </ul>
      </section>

      {preview ? (
        <section className="rounded-[32px] border border-stone-900/10 bg-white/75 p-5 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur">
          <p className="text-xs uppercase tracking-[0.3em] text-stone-500">Preview</p>
          <p className="mt-2 text-sm font-semibold text-stone-900">
            取り込み元: {preview.sourceLabel}
          </p>
          <p className="mt-3 text-sm leading-7 text-stone-600">{preview.extracted.summary}</p>

          <div className="mt-4 space-y-3">
            {preview.extracted.candidates.map((candidate, index) => (
              <div
                key={`${candidate.title}-${candidate.date}-${index}`}
                className="rounded-[24px] border border-stone-900/10 bg-stone-50 px-4 py-4"
              >
                <p className="text-sm font-semibold text-stone-900">{candidate.title}</p>
                <p className="mt-1 text-sm text-stone-600">
                  {candidate.date} {candidate.startTime} - {candidate.endTime}
                </p>
                {candidate.description ? (
                  <p className="mt-2 text-sm leading-7 text-stone-600">
                    {candidate.description}
                  </p>
                ) : null}
              </div>
            ))}
          </div>

          <button
            type="button"
            disabled={!preview.extracted.candidates.length || loading !== null}
            onClick={commitToGoogleCalendar}
            className="mt-4 w-full rounded-full bg-[#e76f51] px-4 py-3 text-sm font-semibold text-white transition hover:bg-[#d95f42] disabled:opacity-50"
          >
            {loading === "commit"
              ? "Google カレンダーへ反映中..."
              : "Google カレンダーへ反映"}
          </button>
        </section>
      ) : null}

      {status ? (
        <section className="rounded-[32px] border border-stone-900/10 bg-[linear-gradient(180deg,_rgba(231,111,81,0.12),_rgba(255,255,255,0.92))] p-5">
          <p className="text-sm leading-7 text-stone-700">{status}</p>
        </section>
      ) : null}
    </aside>
  );
}
