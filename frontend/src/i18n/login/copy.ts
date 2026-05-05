import type { LoginToolCopy } from "@/i18n/login/types";

export const loginCopy = {
  backToTop: "トップへ",
  badge: "Google連携で始めます",
  title: "予定の取り込みと保存に必要な連携を行います。",
  body: "ログインすると、Google Calendarへの保存、Sheets URLの読み取り、予定に合わせた移動時間の確認が使えるようになります。予定候補は確認してから保存できます。",
  permissionNote:
    "Google CalendarとSheetsの権限は、予定の読み取り・保存・取り込みに使います。",
  afterLoginEyebrow: "After login",
  afterLoginTitle: "ログイン後に使えること",
  firstStepTitle: "最初の使い方",
  firstStepBody:
    "まずGoogle Calendarを同期し、そのあと勤務表の画像やSheets URLをチャットに送ります。読み取った予定候補を確認してから保存できます。",
};

export const connectedTools: LoginToolCopy[] = [
  {
    icon: "calendar",
    title: "Google Calendar",
    text: "確認した予定や移動予定を保存します。",
  },
  {
    icon: "sheets",
    title: "Google Sheets",
    text: "勤務表や予定表のURLを読み取ります。",
  },
  {
    icon: "maps",
    title: "Google Maps",
    text: "移動時間や出発時刻の目安を出します。",
  },
  {
    icon: "image",
    title: "画像取り込み",
    text: "スクリーンショットから予定候補を作ります。",
  },
];
