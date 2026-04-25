// 役割: Google Sheets APIから予定取り込み用のデータを読む処理をまとめる。

import { google } from "googleapis";
import { createGoogleOAuthClient, hasGoogleOAuthConfig } from "@/lib/google/oauth";
import { readGoogleProviderTokens } from "@/lib/google/provider-tokens";

export const hasGoogleSheetsReadConfig = () => hasGoogleOAuthConfig();

export const extractSpreadsheetId = (url: string) => {
  const match = url.match(/\/spreadsheets\/d\/([a-zA-Z0-9-_]+)/);
  return match?.[1];
};

export const readGoogleSheetPreview = async (url: string) => {
  const spreadsheetId = extractSpreadsheetId(url);

  if (!spreadsheetId) {
    throw new Error("Google Sheets URL から spreadsheetId を取り出せませんでした。");
  }

  const tokens = await readGoogleProviderTokens();
  const auth = createGoogleOAuthClient(tokens);
  const sheets = google.sheets({ version: "v4", auth });

  const spreadsheet = await sheets.spreadsheets.get({
    spreadsheetId,
    includeGridData: false,
  });

  const firstSheetTitle = spreadsheet.data.sheets?.[0]?.properties?.title;
  if (!firstSheetTitle) {
    throw new Error("シート名を取得できませんでした。");
  }

  const values = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${firstSheetTitle}!A1:Z50`,
  });

  return {
    spreadsheetId,
    sheetTitle: firstSheetTitle,
    rows: values.data.values ?? [],
  };
};
