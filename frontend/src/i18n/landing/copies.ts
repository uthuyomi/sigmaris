import type { AppLocale } from "@/i18n/types";
import type { LandingCopy } from "@/i18n/landing/types";

export const landingCopies: Record<AppLocale, LandingCopy> = {
  ja: {
    tagline: "予定と移動をまとめて管理",
    login: "ログイン",
    previewEyebrow: "Timeline preview",
    previewTitle: "4月25日の予定",
    heroEyebrow: "Chat-first scheduler",
    previewItems: [
      ["08:40", "自宅を出発", "車 / 25分 / 5分前に到着"],
      ["09:10", "早番勤務", "Google Calendarに保存"],
      ["17:35", "店舗から移動", "次の予定に合わせて作成"],
      ["18:15", "打ち合わせ", "場所あり / 移動確認済み"],
    ],
    heroTitle: "勤務表や予定メモを、カレンダーに登録できる形へ変換します。",
    heroBody:
      "シグマリスは、画像やGoogle Sheetsから予定を読み取り、確認してからGoogle Calendarに保存できるスケジュール整理アプリです。場所がある予定は、移動時間や出発時刻までまとめて計算できます。",
    heroCards: [
      ["読み取り", "画像・Sheets URL"],
      ["確認", "予定内容をチェック"],
      ["移動", "出発時刻も計算"],
    ],
    primaryCta: "Googleで始める",
    secondaryCta: "機能を見る",
    detailsEyebrow: "What you can do",
    detailsTitle: "面倒な予定整理を、まとめて自動化します。",
    detailsBody:
      "勤務表や予定メモをもとに、予定候補を自動で作成します。登録前に内容を確認できるため、読み取りミスにも気づきやすく、安心してカレンダーへ保存できます。",
    useCases: [
      {
        icon: "image",
        title: "勤務表の画像から予定を読み取ります",
        text: "スクリーンショットや写真から、日付・開始時刻・終了時刻を読み取り、予定候補を作成します。",
      },
      {
        icon: "sheets",
        title: "Google Sheetsから予定を作成します",
        text: "シートのURLを送ると、勤務や予定に関係する行を読み取り、登録前に内容を確認できます。",
      },
      {
        icon: "route",
        title: "移動時間も自動で計算します",
        text: "予定の場所と出発地をもとに、何時に出発すればよいかを計算し、移動予定を作成します。",
      },
      {
        icon: "calendar",
        title: "Google Calendarに保存します",
        text: "確認した予定や移動予定を、そのままGoogle Calendarへ登録できます。",
      },
    ],
    workflowEyebrow: "Workflow",
    workflowTitle: "使い方は、シンプルです。",
    workflowBody:
      "画像やシートを送るだけで、予定候補を作成します。内容を確認してから保存するため、予定管理に必要なチェック工程も残せます。",
    workflow: [
      {
        step: "1",
        title: "画像やURLを送ります",
        text: "勤務表の画像、SheetsのURL、予定メモをチャットに送ります。",
      },
      {
        step: "2",
        title: "読み取った予定を確認します",
        text: "予定名・日付・時刻を確認してから保存できます。",
      },
      {
        step: "3",
        title: "必要なら移動時間を追加します",
        text: "出発地と移動手段をもとに、開始時刻に間に合う出発時間を計算します。",
      },
      {
        step: "4",
        title: "カレンダーで予定を確認します",
        text: "月表示で全体を確認し、日別タイムラインで一日の流れを細かく確認できます。",
      },
    ],
    examplesEyebrow: "Examples",
    examplesTitle: "たとえば、こう頼めます。",
    examples: [
      "この勤務表の画像から、来週の予定を作ってください",
      "このSheets URLを読み込んで、夜勤だけ予定にしてください",
      "18時の予定に間に合うように、自宅から車で向かう移動予定も入れてください",
    ],
    audienceTitle: "こんな人に向いています",
    audienceItems: [
      "勤務表やシフト表を、毎回カレンダーに手入力している人。",
      "予定の場所に合わせて、出発時刻までまとめて管理したい人。",
      "予定を登録する前に、チャットで内容を整理したい人。",
    ],
  },
  en: {
    tagline: "Manage schedules and travel together",
    login: "Log in",
    previewEyebrow: "Timeline preview",
    previewTitle: "Schedule for Apr 25",
    heroEyebrow: "Chat-first scheduler",
    previewItems: [
      ["08:40", "Leave home", "Car / 25 min / arrive 5 min early"],
      ["09:10", "Early shift", "Saved to Google Calendar"],
      ["17:35", "Travel from store", "Created for the next event"],
      ["18:15", "Meeting", "Location set / travel checked"],
    ],
    heroTitle: "Convert shift tables and schedule notes into calendar-ready events.",
    heroBody:
      "Sigmaris reads schedules from images and Google Sheets, lets you review them, and saves them to Google Calendar. For events with locations, it can also calculate travel time and departure times.",
    heroCards: [
      ["Read", "Images and Sheets URLs"],
      ["Review", "Check event details"],
      ["Travel", "Calculate departure times"],
    ],
    primaryCta: "Start with Google",
    secondaryCta: "View features",
    detailsEyebrow: "What you can do",
    detailsTitle: "Automate the tedious parts of schedule cleanup.",
    detailsBody:
      "Sigmaris creates event candidates from shift tables and schedule notes. You can review everything before saving, making it easier to catch reading mistakes before events reach your calendar.",
    useCases: [
      {
        icon: "image",
        title: "Read events from shift table images",
        text: "Extract dates, start times, and end times from screenshots or photos and turn them into event candidates.",
      },
      {
        icon: "sheets",
        title: "Create events from Google Sheets",
        text: "Send a sheet URL to read rows related to shifts or events, then review the details before saving.",
      },
      {
        icon: "route",
        title: "Calculate travel time automatically",
        text: "Use the event location and departure point to calculate when to leave and create a travel event.",
      },
      {
        icon: "calendar",
        title: "Save to Google Calendar",
        text: "Register reviewed events and travel blocks directly in Google Calendar.",
      },
    ],
    workflowEyebrow: "Workflow",
    workflowTitle: "The workflow is simple.",
    workflowBody:
      "Send an image or sheet, and Sigmaris creates event candidates. You review the details before saving, so the checks that matter for scheduling stay in place.",
    workflow: [
      {
        step: "1",
        title: "Send an image or URL",
        text: "Send a shift table image, Sheets URL, or schedule note in chat.",
      },
      {
        step: "2",
        title: "Review the detected events",
        text: "Check the title, date, and time before saving.",
      },
      {
        step: "3",
        title: "Add travel time if needed",
        text: "Use the departure point and travel mode to calculate a departure time that arrives on time.",
      },
      {
        step: "4",
        title: "Review everything in the calendar",
        text: "Use the month view for the overview and the day timeline for the detailed flow.",
      },
    ],
    examplesEyebrow: "Examples",
    examplesTitle: "For example, you can ask:",
    examples: [
      "Create next week's events from this shift table image",
      "Read this Sheets URL and schedule only the night shifts",
      "Add a driving travel event from home so I arrive by my 6 PM event",
    ],
    audienceTitle: "Built for people who",
    audienceItems: [
      "Manually copy shift tables into their calendar each time.",
      "Want to manage departure times together with event locations.",
      "Want to organize event details in chat before registering them.",
    ],
  },
  ko: {
    tagline: "일정과 이동을 함께 관리",
    login: "로그인",
    previewEyebrow: "Timeline preview",
    previewTitle: "4월 25일 일정",
    heroEyebrow: "Chat-first scheduler",
    previewItems: [
      ["08:40", "집에서 출발", "자동차 / 25분 / 5분 전 도착"],
      ["09:10", "오전 근무", "Google Calendar에 저장"],
      ["17:35", "매장에서 이동", "다음 일정에 맞춰 생성"],
      ["18:15", "미팅", "장소 있음 / 이동 확인 완료"],
    ],
    heroTitle: "근무표와 일정 메모를 캘린더에 등록할 수 있는 형태로 변환합니다.",
    heroBody:
      "Sigmaris는 이미지와 Google Sheets에서 일정을 읽어 오고, 확인한 뒤 Google Calendar에 저장할 수 있는 일정 정리 앱입니다. 장소가 있는 일정은 이동 시간과 출발 시각까지 함께 계산할 수 있습니다.",
    heroCards: [
      ["읽기", "이미지・Sheets URL"],
      ["확인", "일정 내용 확인"],
      ["이동", "출발 시각 계산"],
    ],
    primaryCta: "Google로 시작하기",
    secondaryCta: "기능 보기",
    detailsEyebrow: "What you can do",
    detailsTitle: "번거로운 일정 정리를 한 번에 자동화합니다.",
    detailsBody:
      "근무표나 일정 메모를 바탕으로 일정 후보를 자동으로 만듭니다. 저장 전에 내용을 확인할 수 있어 인식 오류를 발견하기 쉽고, 안심하고 캘린더에 저장할 수 있습니다.",
    useCases: [
      {
        icon: "image",
        title: "근무표 이미지에서 일정을 읽습니다",
        text: "스크린샷이나 사진에서 날짜, 시작 시각, 종료 시각을 읽어 일정 후보를 만듭니다.",
      },
      {
        icon: "sheets",
        title: "Google Sheets에서 일정을 만듭니다",
        text: "시트 URL을 보내면 근무나 일정과 관련된 행을 읽고, 저장 전에 내용을 확인할 수 있습니다.",
      },
      {
        icon: "route",
        title: "이동 시간도 자동으로 계산합니다",
        text: "일정 장소와 출발지를 바탕으로 언제 출발해야 하는지 계산하고 이동 일정을 만듭니다.",
      },
      {
        icon: "calendar",
        title: "Google Calendar에 저장합니다",
        text: "확인한 일정과 이동 일정을 그대로 Google Calendar에 등록할 수 있습니다.",
      },
    ],
    workflowEyebrow: "Workflow",
    workflowTitle: "사용 방법은 간단합니다.",
    workflowBody:
      "이미지나 시트를 보내면 일정 후보를 만듭니다. 내용을 확인한 뒤 저장하므로 일정 관리에 필요한 확인 과정도 유지할 수 있습니다.",
    workflow: [
      {
        step: "1",
        title: "이미지나 URL을 보냅니다",
        text: "근무표 이미지, Sheets URL, 일정 메모를 채팅으로 보냅니다.",
      },
      {
        step: "2",
        title: "읽어 온 일정을 확인합니다",
        text: "일정명, 날짜, 시간을 확인한 뒤 저장할 수 있습니다.",
      },
      {
        step: "3",
        title: "필요하면 이동 시간을 추가합니다",
        text: "출발지와 이동 수단을 바탕으로 시작 시각에 맞는 출발 시간을 계산합니다.",
      },
      {
        step: "4",
        title: "캘린더에서 일정을 확인합니다",
        text: "월 보기로 전체를 확인하고, 일별 타임라인에서 하루 흐름을 자세히 볼 수 있습니다.",
      },
    ],
    examplesEyebrow: "Examples",
    examplesTitle: "예를 들어 이렇게 요청할 수 있습니다.",
    examples: [
      "이 근무표 이미지에서 다음 주 일정을 만들어 주세요",
      "이 Sheets URL을 읽고 야간 근무만 일정으로 만들어 주세요",
      "18시 일정에 맞게 집에서 차로 이동하는 일정도 넣어 주세요",
    ],
    audienceTitle: "이런 분께 적합합니다",
    audienceItems: [
      "근무표나 시프트표를 매번 캘린더에 직접 입력하는 분.",
      "일정 장소에 맞춰 출발 시각까지 함께 관리하고 싶은 분.",
      "일정을 등록하기 전에 채팅으로 내용을 정리하고 싶은 분.",
    ],
  },
  "zh-CN": {
    tagline: "统一管理日程与出行",
    login: "登录",
    previewEyebrow: "Timeline preview",
    previewTitle: "4月25日的日程",
    heroEyebrow: "Chat-first scheduler",
    previewItems: [
      ["08:40", "从家出发", "驾车 / 25分钟 / 提前5分钟到达"],
      ["09:10", "早班", "已保存到 Google Calendar"],
      ["17:35", "从门店出发", "按下一项日程生成"],
      ["18:15", "会议", "有地点 / 已确认出行"],
    ],
    heroTitle: "将排班表和日程备忘转换成可登记到日历的内容。",
    heroBody:
      "Sigmaris 可以从图片和 Google Sheets 中读取日程，确认后保存到 Google Calendar。带地点的日程，还可以一起计算出行时间和出发时间。",
    heroCards: [
      ["读取", "图片・Sheets URL"],
      ["确认", "检查日程内容"],
      ["出行", "计算出发时间"],
    ],
    primaryCta: "使用 Google 开始",
    secondaryCta: "查看功能",
    detailsEyebrow: "What you can do",
    detailsTitle: "把繁琐的日程整理集中自动化。",
    detailsBody:
      "根据排班表和日程备忘自动生成日程候选。保存前可以确认内容，因此更容易发现识别错误，也能安心保存到日历。",
    useCases: [
      {
        icon: "image",
        title: "从排班表图片读取日程",
        text: "从截图或照片中读取日期、开始时间和结束时间，并生成日程候选。",
      },
      {
        icon: "sheets",
        title: "从 Google Sheets 创建日程",
        text: "发送表格 URL 后，会读取与排班或日程相关的行，并在保存前确认内容。",
      },
      {
        icon: "route",
        title: "自动计算出行时间",
        text: "根据日程地点和出发地，计算应该几点出发，并创建出行日程。",
      },
      {
        icon: "calendar",
        title: "保存到 Google Calendar",
        text: "确认后的日程和出行日程可以直接登记到 Google Calendar。",
      },
    ],
    workflowEyebrow: "Workflow",
    workflowTitle: "使用方式很简单。",
    workflowBody:
      "只要发送图片或表格，就会生成日程候选。确认内容后再保存，也能保留日程管理所需的检查步骤。",
    workflow: [
      {
        step: "1",
        title: "发送图片或 URL",
        text: "把排班表图片、Sheets URL 或日程备忘发送到聊天中。",
      },
      {
        step: "2",
        title: "确认读取出的日程",
        text: "确认日程名称、日期和时间后再保存。",
      },
      {
        step: "3",
        title: "需要时添加出行时间",
        text: "根据出发地和出行方式，计算能准时到达的出发时间。",
      },
      {
        step: "4",
        title: "在日历中确认日程",
        text: "用月视图查看整体，再用日视图详细确认一天的流程。",
      },
    ],
    examplesEyebrow: "Examples",
    examplesTitle: "例如，可以这样请求。",
    examples: [
      "请根据这张排班表图片创建下周的日程",
      "请读取这个 Sheets URL，只把夜班做成日程",
      "请添加从家开车出发、能赶上18点日程的出行安排",
    ],
    audienceTitle: "适合这些人",
    audienceItems: [
      "每次都手动把排班表输入到日历的人。",
      "想把日程地点和出发时间一起管理的人。",
      "登记日程前想先在聊天中整理内容的人。",
    ],
  },
  "zh-TW": {
    tagline: "統一管理行程與移動",
    login: "登入",
    previewEyebrow: "Timeline preview",
    previewTitle: "4月25日的行程",
    heroEyebrow: "Chat-first scheduler",
    previewItems: [
      ["08:40", "從家出發", "開車 / 25分鐘 / 提前5分鐘到達"],
      ["09:10", "早班", "已儲存到 Google Calendar"],
      ["17:35", "從店鋪移動", "依下一個行程建立"],
      ["18:15", "會議", "有地點 / 已確認移動"],
    ],
    heroTitle: "將排班表與行程備忘轉換成可登錄到行事曆的內容。",
    heroBody:
      "Sigmaris 可以從圖片與 Google Sheets 讀取行程，確認後儲存到 Google Calendar。帶有地點的行程，也能一併計算移動時間與出發時間。",
    heroCards: [
      ["讀取", "圖片・Sheets URL"],
      ["確認", "檢查行程內容"],
      ["移動", "計算出發時間"],
    ],
    primaryCta: "使用 Google 開始",
    secondaryCta: "查看功能",
    detailsEyebrow: "What you can do",
    detailsTitle: "把繁瑣的行程整理集中自動化。",
    detailsBody:
      "根據排班表與行程備忘自動建立行程候選。儲存前可以確認內容，因此更容易發現讀取錯誤，也能安心儲存到行事曆。",
    useCases: [
      {
        icon: "image",
        title: "從排班表圖片讀取行程",
        text: "從截圖或照片讀取日期、開始時間與結束時間，並建立行程候選。",
      },
      {
        icon: "sheets",
        title: "從 Google Sheets 建立行程",
        text: "送出試算表 URL 後，會讀取與排班或行程相關的列，並在儲存前確認內容。",
      },
      {
        icon: "route",
        title: "自動計算移動時間",
        text: "根據行程地點與出發地，計算應該幾點出發，並建立移動行程。",
      },
      {
        icon: "calendar",
        title: "儲存到 Google Calendar",
        text: "確認後的行程與移動行程可以直接登錄到 Google Calendar。",
      },
    ],
    workflowEyebrow: "Workflow",
    workflowTitle: "使用方式很簡單。",
    workflowBody:
      "只要送出圖片或試算表，就會建立行程候選。確認內容後再儲存，也能保留行程管理需要的檢查流程。",
    workflow: [
      {
        step: "1",
        title: "送出圖片或 URL",
        text: "把排班表圖片、Sheets URL 或行程備忘送到聊天中。",
      },
      {
        step: "2",
        title: "確認讀取出的行程",
        text: "確認行程名稱、日期與時間後再儲存。",
      },
      {
        step: "3",
        title: "需要時加入移動時間",
        text: "根據出發地與移動方式，計算能準時到達的出發時間。",
      },
      {
        step: "4",
        title: "在行事曆中確認行程",
        text: "用月視圖確認整體，再用日別時間軸細看一天的流程。",
      },
    ],
    examplesEyebrow: "Examples",
    examplesTitle: "例如，可以這樣請它處理。",
    examples: [
      "請根據這張排班表圖片建立下週的行程",
      "請讀取這個 Sheets URL，只把夜班做成行程",
      "請加入從家開車出發、能趕上18點行程的移動安排",
    ],
    audienceTitle: "適合這些人",
    audienceItems: [
      "每次都手動把排班表輸入到行事曆的人。",
      "想把行程地點和出發時間一起管理的人。",
      "登錄行程前想先在聊天中整理內容的人。",
    ],
  },
  es: {
    tagline: "Gestiona horarios y traslados juntos",
    login: "Iniciar sesión",
    previewEyebrow: "Timeline preview",
    previewTitle: "Agenda del 25 de abril",
    heroEyebrow: "Chat-first scheduler",
    previewItems: [
      ["08:40", "Salir de casa", "Coche / 25 min / llegar 5 min antes"],
      ["09:10", "Turno temprano", "Guardado en Google Calendar"],
      ["17:35", "Traslado desde la tienda", "Creado para el siguiente evento"],
      ["18:15", "Reunión", "Ubicación definida / traslado revisado"],
    ],
    heroTitle: "Convierte turnos y notas de agenda en eventos listos para el calendario.",
    heroBody:
      "Sigmaris lee horarios desde imágenes y Google Sheets, te permite revisarlos y guardarlos en Google Calendar. Si un evento tiene ubicación, también calcula el tiempo de traslado y la hora de salida.",
    heroCards: [
      ["Lectura", "Imágenes y URL de Sheets"],
      ["Revisión", "Comprobar detalles"],
      ["Traslado", "Calcular salida"],
    ],
    primaryCta: "Empezar con Google",
    secondaryCta: "Ver funciones",
    detailsEyebrow: "What you can do",
    detailsTitle: "Automatiza en conjunto la organización pesada de tus horarios.",
    detailsBody:
      "A partir de turnos y notas de agenda, crea candidatos de eventos automáticamente. Puedes revisar el contenido antes de guardar, detectar errores de lectura y enviar todo al calendario con más confianza.",
    useCases: [
      {
        icon: "image",
        title: "Lee eventos desde imágenes de turnos",
        text: "Extrae fecha, hora de inicio y hora de fin desde capturas o fotos para crear candidatos de eventos.",
      },
      {
        icon: "sheets",
        title: "Crea eventos desde Google Sheets",
        text: "Envía la URL de una hoja para leer las filas relacionadas con turnos o eventos y revisarlas antes de guardar.",
      },
      {
        icon: "route",
        title: "Calcula automáticamente el tiempo de traslado",
        text: "Con la ubicación del evento y el punto de salida, calcula a qué hora conviene salir y crea el traslado.",
      },
      {
        icon: "calendar",
        title: "Guarda en Google Calendar",
        text: "Registra directamente en Google Calendar los eventos y traslados revisados.",
      },
    ],
    workflowEyebrow: "Workflow",
    workflowTitle: "El uso es simple.",
    workflowBody:
      "Envía una imagen o una hoja y se crearán candidatos de eventos. Como revisas el contenido antes de guardar, mantienes el control necesario para gestionar tu agenda.",
    workflow: [
      {
        step: "1",
        title: "Envía una imagen o URL",
        text: "Envía una imagen de turnos, una URL de Sheets o una nota de agenda en el chat.",
      },
      {
        step: "2",
        title: "Revisa los eventos leídos",
        text: "Comprueba nombre, fecha y hora antes de guardar.",
      },
      {
        step: "3",
        title: "Añade tiempo de traslado si hace falta",
        text: "Calcula una hora de salida que llegue a tiempo según origen y modo de transporte.",
      },
      {
        step: "4",
        title: "Revisa la agenda en el calendario",
        text: "Usa la vista mensual para el panorama y la línea diaria para el detalle.",
      },
    ],
    examplesEyebrow: "Examples",
    examplesTitle: "Por ejemplo, puedes pedir:",
    examples: [
      "Crea los eventos de la próxima semana desde esta imagen de turnos",
      "Lee esta URL de Sheets y agenda solo los turnos nocturnos",
      "Añade también un traslado en coche desde casa para llegar al evento de las 18:00",
    ],
    audienceTitle: "Ideal para personas que",
    audienceItems: [
      "Introducen manualmente sus turnos en el calendario cada vez.",
      "Quieren gestionar también la hora de salida según la ubicación.",
      "Quieren ordenar los detalles en el chat antes de registrar eventos.",
    ],
  },
  fr: {
    tagline: "Gérer les plannings et trajets ensemble",
    login: "Connexion",
    previewEyebrow: "Timeline preview",
    previewTitle: "Planning du 25 avril",
    heroEyebrow: "Chat-first scheduler",
    previewItems: [
      ["08:40", "Départ du domicile", "Voiture / 25 min / arrivée 5 min avant"],
      ["09:10", "Service du matin", "Enregistré dans Google Calendar"],
      ["17:35", "Trajet depuis le magasin", "Créé pour le prochain événement"],
      ["18:15", "Réunion", "Lieu défini / trajet vérifié"],
    ],
    heroTitle: "Transformez plannings et notes en événements prêts pour le calendrier.",
    heroBody:
      "Sigmaris lit les horaires depuis des images et Google Sheets, vous laisse les vérifier, puis les enregistre dans Google Calendar. Pour les événements avec lieu, il calcule aussi le temps de trajet et l'heure de départ.",
    heroCards: [
      ["Lecture", "Images et URL Sheets"],
      ["Vérification", "Contrôler les détails"],
      ["Trajet", "Calculer le départ"],
    ],
    primaryCta: "Commencer avec Google",
    secondaryCta: "Voir les fonctions",
    detailsEyebrow: "What you can do",
    detailsTitle: "Automatisez les tâches fastidieuses de préparation du planning.",
    detailsBody:
      "À partir de plannings et de notes, Sigmaris crée automatiquement des propositions d'événements. Vous pouvez tout vérifier avant d'enregistrer, repérer les erreurs de lecture et sauvegarder plus sereinement.",
    useCases: [
      {
        icon: "image",
        title: "Lire les événements depuis une image de planning",
        text: "Extrait les dates, heures de début et heures de fin depuis des captures ou photos pour créer des propositions.",
      },
      {
        icon: "sheets",
        title: "Créer des événements depuis Google Sheets",
        text: "Envoyez l'URL d'une feuille pour lire les lignes liées aux services ou événements, puis vérifiez avant d'enregistrer.",
      },
      {
        icon: "route",
        title: "Calculer automatiquement le temps de trajet",
        text: "À partir du lieu de l'événement et du point de départ, calcule l'heure de départ et crée le trajet.",
      },
      {
        icon: "calendar",
        title: "Enregistrer dans Google Calendar",
        text: "Ajoutez directement les événements et trajets vérifiés dans Google Calendar.",
      },
    ],
    workflowEyebrow: "Workflow",
    workflowTitle: "L'utilisation est simple.",
    workflowBody:
      "Envoyez une image ou une feuille, et Sigmaris crée des propositions. Vous vérifiez avant d'enregistrer, afin de garder l'étape de contrôle nécessaire.",
    workflow: [
      {
        step: "1",
        title: "Envoyez une image ou une URL",
        text: "Envoyez une image de planning, une URL Sheets ou une note dans le chat.",
      },
      {
        step: "2",
        title: "Vérifiez les événements détectés",
        text: "Contrôlez le nom, la date et l'heure avant d'enregistrer.",
      },
      {
        step: "3",
        title: "Ajoutez le trajet si nécessaire",
        text: "Calculez une heure de départ compatible avec le début de l'événement.",
      },
      {
        step: "4",
        title: "Vérifiez dans le calendrier",
        text: "Consultez l'ensemble en vue mensuelle et le détail dans la timeline du jour.",
      },
    ],
    examplesEyebrow: "Examples",
    examplesTitle: "Par exemple, vous pouvez demander :",
    examples: [
      "Crée les événements de la semaine prochaine depuis cette image de planning",
      "Lis cette URL Sheets et crée seulement les services de nuit",
      "Ajoute aussi un trajet en voiture depuis chez moi pour arriver à l'événement de 18 h",
    ],
    audienceTitle: "Convient aux personnes qui",
    audienceItems: [
      "Saisissent manuellement leurs plannings dans le calendrier.",
      "Veulent gérer l'heure de départ avec le lieu de l'événement.",
      "Veulent organiser les détails dans le chat avant l'enregistrement.",
    ],
  },
  de: {
    tagline: "Termine und Wege gemeinsam verwalten",
    login: "Anmelden",
    previewEyebrow: "Timeline preview",
    previewTitle: "Plan für den 25. April",
    heroEyebrow: "Chat-first scheduler",
    previewItems: [
      ["08:40", "Von zu Hause losfahren", "Auto / 25 Min. / 5 Min. früher ankommen"],
      ["09:10", "Frühschicht", "In Google Calendar gespeichert"],
      ["17:35", "Fahrt vom Laden", "Für den nächsten Termin erstellt"],
      ["18:15", "Besprechung", "Ort vorhanden / Weg geprüft"],
    ],
    heroTitle: "Wandle Dienstpläne und Terminnotizen in kalenderfertige Einträge um.",
    heroBody:
      "Sigmaris liest Termine aus Bildern und Google Sheets, lässt dich alles prüfen und speichert es in Google Calendar. Bei Terminen mit Ort werden auch Fahrzeit und Abfahrtszeit berechnet.",
    heroCards: [
      ["Auslesen", "Bilder und Sheets-URLs"],
      ["Prüfen", "Termindetails ansehen"],
      ["Weg", "Abfahrtszeit berechnen"],
    ],
    primaryCta: "Mit Google starten",
    secondaryCta: "Funktionen ansehen",
    detailsEyebrow: "What you can do",
    detailsTitle: "Automatisiere die mühsame Terminaufbereitung an einem Ort.",
    detailsBody:
      "Aus Dienstplänen und Terminnotizen erstellt Sigmaris automatisch Terminvorschläge. Vor dem Speichern kannst du alles prüfen, Lesefehler leichter erkennen und sicher in den Kalender übernehmen.",
    useCases: [
      {
        icon: "image",
        title: "Termine aus Dienstplan-Bildern auslesen",
        text: "Liest Datum, Startzeit und Endzeit aus Screenshots oder Fotos und erstellt Terminvorschläge.",
      },
      {
        icon: "sheets",
        title: "Termine aus Google Sheets erstellen",
        text: "Sende eine Tabellen-URL, um schicht- oder terminbezogene Zeilen auszulesen und vor dem Speichern zu prüfen.",
      },
      {
        icon: "route",
        title: "Fahrzeit automatisch berechnen",
        text: "Berechnet anhand von Terminort und Startpunkt, wann du losfahren solltest, und erstellt einen Wegeintrag.",
      },
      {
        icon: "calendar",
        title: "In Google Calendar speichern",
        text: "Geprüfte Termine und Wegeeinträge lassen sich direkt in Google Calendar eintragen.",
      },
    ],
    workflowEyebrow: "Workflow",
    workflowTitle: "Die Nutzung ist einfach.",
    workflowBody:
      "Sende ein Bild oder eine Tabelle, und Sigmaris erstellt Terminvorschläge. Da du vor dem Speichern prüfst, bleibt der wichtige Kontrollschritt erhalten.",
    workflow: [
      {
        step: "1",
        title: "Bild oder URL senden",
        text: "Sende ein Dienstplanbild, eine Sheets-URL oder eine Terminnotiz im Chat.",
      },
      {
        step: "2",
        title: "Ausgelesene Termine prüfen",
        text: "Prüfe Titel, Datum und Uhrzeit, bevor du speicherst.",
      },
      {
        step: "3",
        title: "Bei Bedarf Fahrzeit hinzufügen",
        text: "Berechne anhand von Startpunkt und Verkehrsmittel eine passende Abfahrtszeit.",
      },
      {
        step: "4",
        title: "Termine im Kalender prüfen",
        text: "Nutze die Monatsansicht für den Überblick und die Tages-Timeline für Details.",
      },
    ],
    examplesEyebrow: "Examples",
    examplesTitle: "Zum Beispiel kannst du fragen:",
    examples: [
      "Erstelle aus diesem Dienstplanbild die Termine für nächste Woche",
      "Lies diese Sheets-URL und plane nur die Nachtschichten ein",
      "Füge auch eine Autofahrt von zu Hause ein, damit ich den Termin um 18 Uhr erreiche",
    ],
    audienceTitle: "Geeignet für Menschen, die",
    audienceItems: [
      "Dienst- oder Schichtpläne jedes Mal manuell in den Kalender eintragen.",
      "Abfahrtszeiten zusammen mit Terminorten verwalten möchten.",
      "Termindetails vor dem Eintragen im Chat ordnen möchten.",
    ],
  },
  "pt-BR": {
    tagline: "Gerencie agenda e deslocamentos juntos",
    login: "Entrar",
    previewEyebrow: "Timeline preview",
    previewTitle: "Agenda de 25 de abril",
    heroEyebrow: "Chat-first scheduler",
    previewItems: [
      ["08:40", "Sair de casa", "Carro / 25 min / chegar 5 min antes"],
      ["09:10", "Turno da manhã", "Salvo no Google Calendar"],
      ["17:35", "Deslocamento da loja", "Criado para o próximo compromisso"],
      ["18:15", "Reunião", "Local definido / deslocamento conferido"],
    ],
    heroTitle: "Transforme escalas e notas de agenda em eventos prontos para o calendário.",
    heroBody:
      "Sigmaris lê agendas de imagens e Google Sheets, permite revisar tudo e salva no Google Calendar. Para compromissos com local, também calcula tempo de deslocamento e horário de saída.",
    heroCards: [
      ["Leitura", "Imagens e URLs do Sheets"],
      ["Revisão", "Conferir detalhes"],
      ["Deslocamento", "Calcular saída"],
    ],
    primaryCta: "Começar com Google",
    secondaryCta: "Ver recursos",
    detailsEyebrow: "What you can do",
    detailsTitle: "Automatize a organização trabalhosa da agenda.",
    detailsBody:
      "Com base em escalas e notas, o Sigmaris cria candidatos de eventos automaticamente. Você revisa tudo antes de salvar, encontra erros de leitura com mais facilidade e envia ao calendário com confiança.",
    useCases: [
      {
        icon: "image",
        title: "Lê eventos de imagens de escala",
        text: "Extrai data, horário de início e horário de fim de capturas ou fotos para criar candidatos de eventos.",
      },
      {
        icon: "sheets",
        title: "Cria eventos a partir do Google Sheets",
        text: "Envie a URL de uma planilha para ler linhas relacionadas a turnos ou eventos e revisar antes de salvar.",
      },
      {
        icon: "route",
        title: "Calcula deslocamento automaticamente",
        text: "Com o local do compromisso e o ponto de partida, calcula quando sair e cria o deslocamento.",
      },
      {
        icon: "calendar",
        title: "Salva no Google Calendar",
        text: "Registre eventos e deslocamentos revisados diretamente no Google Calendar.",
      },
    ],
    workflowEyebrow: "Workflow",
    workflowTitle: "O uso é simples.",
    workflowBody:
      "Envie uma imagem ou planilha e o Sigmaris cria candidatos de eventos. Você revisa antes de salvar, mantendo a conferência necessária para a agenda.",
    workflow: [
      {
        step: "1",
        title: "Envie uma imagem ou URL",
        text: "Envie uma imagem de escala, URL do Sheets ou nota de agenda no chat.",
      },
      {
        step: "2",
        title: "Revise os eventos lidos",
        text: "Confira nome, data e horário antes de salvar.",
      },
      {
        step: "3",
        title: "Adicione deslocamento se necessário",
        text: "Calcule um horário de saída que chegue a tempo, com base na origem e no modo de transporte.",
      },
      {
        step: "4",
        title: "Confira no calendário",
        text: "Use a visão mensal para o geral e a linha do dia para o fluxo detalhado.",
      },
    ],
    examplesEyebrow: "Examples",
    examplesTitle: "Por exemplo, você pode pedir:",
    examples: [
      "Crie os eventos da próxima semana a partir desta imagem da escala",
      "Leia esta URL do Sheets e agende apenas os turnos da noite",
      "Adicione também um deslocamento de carro saindo de casa para chegar ao evento das 18h",
    ],
    audienceTitle: "Indicado para quem",
    audienceItems: [
      "Digita escalas ou turnos manualmente no calendário toda vez.",
      "Quer gerenciar horário de saída junto com o local do compromisso.",
      "Quer organizar os detalhes no chat antes de registrar eventos.",
    ],
  },
  it: {
    tagline: "Gestisci insieme agenda e spostamenti",
    login: "Accedi",
    previewEyebrow: "Timeline preview",
    previewTitle: "Agenda del 25 aprile",
    heroEyebrow: "Chat-first scheduler",
    previewItems: [
      ["08:40", "Partenza da casa", "Auto / 25 min / arrivo 5 min prima"],
      ["09:10", "Turno mattutino", "Salvato in Google Calendar"],
      ["17:35", "Spostamento dal negozio", "Creato per l'evento successivo"],
      ["18:15", "Riunione", "Luogo impostato / spostamento verificato"],
    ],
    heroTitle: "Trasforma turni e note in eventi pronti per il calendario.",
    heroBody:
      "Sigmaris legge gli impegni da immagini e Google Sheets, ti permette di controllarli e li salva in Google Calendar. Per gli eventi con luogo, calcola anche tempo di viaggio e orario di partenza.",
    heroCards: [
      ["Lettura", "Immagini e URL Sheets"],
      ["Controllo", "Verifica dettagli"],
      ["Spostamento", "Calcolo partenza"],
    ],
    primaryCta: "Inizia con Google",
    secondaryCta: "Vedi funzioni",
    detailsEyebrow: "What you can do",
    detailsTitle: "Automatizza in un unico flusso la parte noiosa dell'agenda.",
    detailsBody:
      "Da turni e note, Sigmaris crea automaticamente proposte di eventi. Puoi controllare tutto prima di salvare, individuare errori di lettura e registrare con più sicurezza.",
    useCases: [
      {
        icon: "image",
        title: "Legge eventi da immagini di turni",
        text: "Estrae data, ora di inizio e ora di fine da screenshot o foto e crea proposte di eventi.",
      },
      {
        icon: "sheets",
        title: "Crea eventi da Google Sheets",
        text: "Invia l'URL di un foglio per leggere le righe legate a turni o eventi e controllarle prima di salvare.",
      },
      {
        icon: "route",
        title: "Calcola automaticamente il tempo di viaggio",
        text: "Usa luogo dell'evento e punto di partenza per calcolare quando partire e creare lo spostamento.",
      },
      {
        icon: "calendar",
        title: "Salva in Google Calendar",
        text: "Registra direttamente in Google Calendar eventi e spostamenti verificati.",
      },
    ],
    workflowEyebrow: "Workflow",
    workflowTitle: "L'uso è semplice.",
    workflowBody:
      "Invia un'immagine o un foglio e Sigmaris crea proposte di eventi. Controlli i dettagli prima di salvare, mantenendo il passaggio di verifica necessario.",
    workflow: [
      {
        step: "1",
        title: "Invia un'immagine o URL",
        text: "Invia nel chat un'immagine di turni, un URL Sheets o una nota.",
      },
      {
        step: "2",
        title: "Controlla gli eventi letti",
        text: "Verifica nome, data e orario prima di salvare.",
      },
      {
        step: "3",
        title: "Aggiungi il viaggio se serve",
        text: "Calcola un orario di partenza in tempo per l'inizio, in base a origine e mezzo.",
      },
      {
        step: "4",
        title: "Controlla nel calendario",
        text: "Usa la vista mensile per il quadro generale e la timeline giornaliera per il dettaglio.",
      },
    ],
    examplesEyebrow: "Examples",
    examplesTitle: "Per esempio, puoi chiedere:",
    examples: [
      "Crea gli eventi della prossima settimana da questa immagine dei turni",
      "Leggi questo URL Sheets e crea solo i turni notturni",
      "Aggiungi anche uno spostamento in auto da casa per arrivare all'evento delle 18",
    ],
    audienceTitle: "Adatto a chi",
    audienceItems: [
      "Inserisce manualmente turni e tabelle nel calendario ogni volta.",
      "Vuole gestire anche l'orario di partenza insieme al luogo dell'evento.",
      "Vuole organizzare i dettagli in chat prima di registrare gli eventi.",
    ],
  },
  id: {
    tagline: "Kelola jadwal dan perjalanan sekaligus",
    login: "Masuk",
    previewEyebrow: "Timeline preview",
    previewTitle: "Jadwal 25 April",
    heroEyebrow: "Chat-first scheduler",
    previewItems: [
      ["08:40", "Berangkat dari rumah", "Mobil / 25 menit / tiba 5 menit lebih awal"],
      ["09:10", "Shift pagi", "Disimpan ke Google Calendar"],
      ["17:35", "Perjalanan dari toko", "Dibuat untuk acara berikutnya"],
      ["18:15", "Rapat", "Lokasi ada / perjalanan dicek"],
    ],
    heroTitle: "Ubah tabel shift dan catatan jadwal menjadi acara siap masuk kalender.",
    heroBody:
      "Sigmaris membaca jadwal dari gambar dan Google Sheets, lalu memungkinkan Anda memeriksanya sebelum menyimpan ke Google Calendar. Untuk acara yang memiliki lokasi, waktu perjalanan dan jam berangkat juga dapat dihitung sekaligus.",
    heroCards: [
      ["Baca", "Gambar dan URL Sheets"],
      ["Periksa", "Cek detail acara"],
      ["Perjalanan", "Hitung jam berangkat"],
    ],
    primaryCta: "Mulai dengan Google",
    secondaryCta: "Lihat fitur",
    detailsEyebrow: "What you can do",
    detailsTitle: "Otomatiskan pekerjaan merapikan jadwal yang merepotkan.",
    detailsBody:
      "Berdasarkan tabel shift dan catatan jadwal, Sigmaris membuat kandidat acara secara otomatis. Anda bisa memeriksa isinya sebelum menyimpan, sehingga kesalahan baca lebih mudah terlihat dan kalender tetap aman.",
    useCases: [
      {
        icon: "image",
        title: "Membaca jadwal dari gambar tabel shift",
        text: "Mengambil tanggal, jam mulai, dan jam selesai dari screenshot atau foto untuk membuat kandidat acara.",
      },
      {
        icon: "sheets",
        title: "Membuat acara dari Google Sheets",
        text: "Kirim URL sheet untuk membaca baris yang terkait shift atau acara, lalu periksa sebelum menyimpan.",
      },
      {
        icon: "route",
        title: "Menghitung waktu perjalanan otomatis",
        text: "Berdasarkan lokasi acara dan titik berangkat, menghitung kapan harus pergi dan membuat acara perjalanan.",
      },
      {
        icon: "calendar",
        title: "Menyimpan ke Google Calendar",
        text: "Acara dan perjalanan yang sudah diperiksa dapat langsung didaftarkan ke Google Calendar.",
      },
    ],
    workflowEyebrow: "Workflow",
    workflowTitle: "Cara pakainya sederhana.",
    workflowBody:
      "Kirim gambar atau sheet, lalu Sigmaris membuat kandidat acara. Karena Anda memeriksa sebelum menyimpan, proses pengecekan jadwal tetap ada.",
    workflow: [
      {
        step: "1",
        title: "Kirim gambar atau URL",
        text: "Kirim gambar tabel shift, URL Sheets, atau catatan jadwal ke chat.",
      },
      {
        step: "2",
        title: "Periksa jadwal yang terbaca",
        text: "Cek nama acara, tanggal, dan waktu sebelum menyimpan.",
      },
      {
        step: "3",
        title: "Tambahkan waktu perjalanan bila perlu",
        text: "Hitung jam berangkat yang tepat berdasarkan titik berangkat dan moda perjalanan.",
      },
      {
        step: "4",
        title: "Periksa di kalender",
        text: "Gunakan tampilan bulan untuk gambaran besar dan timeline harian untuk alur detail.",
      },
    ],
    examplesEyebrow: "Examples",
    examplesTitle: "Misalnya, Anda bisa meminta:",
    examples: [
      "Buat jadwal minggu depan dari gambar tabel shift ini",
      "Baca URL Sheets ini dan jadwalkan hanya shift malam",
      "Tambahkan juga perjalanan naik mobil dari rumah agar tiba untuk acara jam 18.00",
    ],
    audienceTitle: "Cocok untuk orang yang",
    audienceItems: [
      "Selalu memasukkan tabel shift ke kalender secara manual.",
      "Ingin mengelola jam berangkat bersama lokasi acara.",
      "Ingin merapikan detail jadwal lewat chat sebelum mendaftarkannya.",
    ],
  },
  th: {
    tagline: "จัดการตารางและการเดินทางในที่เดียว",
    login: "เข้าสู่ระบบ",
    previewEyebrow: "Timeline preview",
    previewTitle: "ตารางวันที่ 25 เมษายน",
    heroEyebrow: "Chat-first scheduler",
    previewItems: [
      ["08:40", "ออกจากบ้าน", "รถยนต์ / 25 นาที / ถึงก่อน 5 นาที"],
      ["09:10", "กะเช้า", "บันทึกลง Google Calendar"],
      ["17:35", "เดินทางจากร้าน", "สร้างให้เข้ากับนัดถัดไป"],
      ["18:15", "ประชุม", "มีสถานที่ / ตรวจการเดินทางแล้ว"],
    ],
    heroTitle: "แปลงตารางกะและบันทึกนัดหมายให้พร้อมบันทึกลงปฏิทิน",
    heroBody:
      "Sigmaris อ่านตารางจากรูปภาพและ Google Sheets ให้คุณตรวจสอบก่อนบันทึกลง Google Calendar หากนัดหมายมีสถานที่ ระบบยังคำนวณเวลาเดินทางและเวลาออกเดินทางให้ด้วย",
    heroCards: [
      ["อ่านข้อมูล", "รูปภาพและ URL ของ Sheets"],
      ["ตรวจสอบ", "เช็กรายละเอียดนัดหมาย"],
      ["เดินทาง", "คำนวณเวลาออกเดินทาง"],
    ],
    primaryCta: "เริ่มด้วย Google",
    secondaryCta: "ดูฟีเจอร์",
    detailsEyebrow: "What you can do",
    detailsTitle: "ทำให้งานจัดตารางที่ยุ่งยากเป็นอัตโนมัติในที่เดียว",
    detailsBody:
      "จากตารางกะหรือบันทึกนัดหมาย Sigmaris จะสร้างรายการนัดหมายให้โดยอัตโนมัติ คุณตรวจสอบก่อนบันทึกได้ จึงเห็นข้อผิดพลาดจากการอ่านข้อมูลได้ง่ายขึ้นและบันทึกลงปฏิทินได้อย่างมั่นใจ",
    useCases: [
      {
        icon: "image",
        title: "อ่านนัดหมายจากรูปตารางกะ",
        text: "อ่านวันที่ เวลาเริ่ม และเวลาสิ้นสุดจากภาพหน้าจอหรือรูปถ่าย แล้วสร้างรายการนัดหมายให้ตรวจสอบ",
      },
      {
        icon: "sheets",
        title: "สร้างนัดหมายจาก Google Sheets",
        text: "ส่ง URL ของชีตเพื่ออ่านแถวที่เกี่ยวกับกะหรือนัดหมาย แล้วตรวจสอบก่อนบันทึก",
      },
      {
        icon: "route",
        title: "คำนวณเวลาเดินทางอัตโนมัติ",
        text: "ใช้สถานที่ของนัดหมายและจุดออกเดินทางเพื่อคำนวณว่าควรออกกี่โมง และสร้างนัดหมายการเดินทาง",
      },
      {
        icon: "calendar",
        title: "บันทึกลง Google Calendar",
        text: "บันทึกนัดหมายและการเดินทางที่ตรวจสอบแล้วลง Google Calendar ได้โดยตรง",
      },
    ],
    workflowEyebrow: "Workflow",
    workflowTitle: "วิธีใช้งานเรียบง่าย",
    workflowBody:
      "แค่ส่งรูปภาพหรือชีต ระบบจะสร้างรายการนัดหมายให้ คุณตรวจสอบก่อนบันทึก จึงยังมีขั้นตอนเช็กข้อมูลที่จำเป็นต่อการจัดตาราง",
    workflow: [
      {
        step: "1",
        title: "ส่งรูปภาพหรือ URL",
        text: "ส่งรูปตารางกะ, URL ของ Sheets หรือบันทึกนัดหมายในแชต",
      },
      {
        step: "2",
        title: "ตรวจนัดหมายที่อ่านได้",
        text: "ตรวจชื่อ วันที่ และเวลา ก่อนบันทึก",
      },
      {
        step: "3",
        title: "เพิ่มเวลาเดินทางเมื่อจำเป็น",
        text: "คำนวณเวลาออกเดินทางให้ไปถึงทันเวลาเริ่ม จากจุดออกเดินทางและวิธีเดินทาง",
      },
      {
        step: "4",
        title: "ตรวจในปฏิทิน",
        text: "ดูภาพรวมด้วยมุมมองรายเดือน และดูรายละเอียดของวันด้วยไทม์ไลน์รายวัน",
      },
    ],
    examplesEyebrow: "Examples",
    examplesTitle: "ตัวอย่างคำสั่งที่ใช้ได้",
    examples: [
      "สร้างตารางสัปดาห์หน้าจากรูปตารางกะนี้",
      "อ่าน URL ของ Sheets นี้ แล้วทำเฉพาะกะกลางคืนเป็นนัดหมาย",
      "เพิ่มการเดินทางด้วยรถจากบ้านให้ทันนัดเวลา 18:00 ด้วย",
    ],
    audienceTitle: "เหมาะสำหรับคนที่",
    audienceItems: [
      "ต้องกรอกตารางกะลงปฏิทินเองทุกครั้ง",
      "อยากจัดการเวลาออกเดินทางพร้อมกับสถานที่ของนัดหมาย",
      "อยากจัดระเบียบรายละเอียดในแชตก่อนบันทึกนัดหมาย",
    ],
  },
  vi: {
    tagline: "Quản lý lịch và di chuyển cùng một nơi",
    login: "Đăng nhập",
    previewEyebrow: "Timeline preview",
    previewTitle: "Lịch ngày 25 tháng 4",
    heroEyebrow: "Chat-first scheduler",
    previewItems: [
      ["08:40", "Rời khỏi nhà", "Ô tô / 25 phút / đến sớm 5 phút"],
      ["09:10", "Ca sáng", "Đã lưu vào Google Calendar"],
      ["17:35", "Di chuyển từ cửa hàng", "Tạo theo lịch tiếp theo"],
      ["18:15", "Họp", "Có địa điểm / đã kiểm tra di chuyển"],
    ],
    heroTitle: "Chuyển bảng ca và ghi chú lịch thành sự kiện sẵn sàng lưu vào lịch.",
    heroBody:
      "Sigmaris đọc lịch từ hình ảnh và Google Sheets, cho phép bạn kiểm tra rồi lưu vào Google Calendar. Với lịch có địa điểm, ứng dụng cũng tính cả thời gian di chuyển và giờ xuất phát.",
    heroCards: [
      ["Đọc", "Hình ảnh và URL Sheets"],
      ["Kiểm tra", "Xem lại nội dung lịch"],
      ["Di chuyển", "Tính giờ xuất phát"],
    ],
    primaryCta: "Bắt đầu với Google",
    secondaryCta: "Xem tính năng",
    detailsEyebrow: "What you can do",
    detailsTitle: "Tự động hóa phần sắp xếp lịch rườm rà.",
    detailsBody:
      "Dựa trên bảng ca và ghi chú lịch, Sigmaris tự động tạo các lịch đề xuất. Bạn có thể kiểm tra trước khi lưu, dễ phát hiện lỗi đọc dữ liệu và yên tâm đưa vào lịch.",
    useCases: [
      {
        icon: "image",
        title: "Đọc lịch từ ảnh bảng ca",
        text: "Đọc ngày, giờ bắt đầu và giờ kết thúc từ ảnh chụp màn hình hoặc ảnh chụp để tạo lịch đề xuất.",
      },
      {
        icon: "sheets",
        title: "Tạo lịch từ Google Sheets",
        text: "Gửi URL của sheet để đọc các dòng liên quan đến ca làm hoặc lịch, rồi kiểm tra trước khi lưu.",
      },
      {
        icon: "route",
        title: "Tự động tính thời gian di chuyển",
        text: "Dựa trên địa điểm lịch và điểm xuất phát, tính giờ nên khởi hành và tạo lịch di chuyển.",
      },
      {
        icon: "calendar",
        title: "Lưu vào Google Calendar",
        text: "Đăng ký trực tiếp các lịch và lịch di chuyển đã kiểm tra vào Google Calendar.",
      },
    ],
    workflowEyebrow: "Workflow",
    workflowTitle: "Cách dùng rất đơn giản.",
    workflowBody:
      "Chỉ cần gửi ảnh hoặc sheet, Sigmaris sẽ tạo lịch đề xuất. Bạn kiểm tra nội dung rồi mới lưu, nên vẫn giữ được bước kiểm tra cần thiết khi quản lý lịch.",
    workflow: [
      {
        step: "1",
        title: "Gửi hình ảnh hoặc URL",
        text: "Gửi ảnh bảng ca, URL Sheets hoặc ghi chú lịch vào chat.",
      },
      {
        step: "2",
        title: "Kiểm tra lịch đã đọc",
        text: "Kiểm tra tên lịch, ngày và giờ trước khi lưu.",
      },
      {
        step: "3",
        title: "Thêm thời gian di chuyển nếu cần",
        text: "Tính giờ xuất phát kịp giờ bắt đầu dựa trên điểm đi và phương tiện.",
      },
      {
        step: "4",
        title: "Kiểm tra lịch trên calendar",
        text: "Dùng chế độ xem tháng để nắm tổng thể và timeline theo ngày để xem chi tiết.",
      },
    ],
    examplesEyebrow: "Examples",
    examplesTitle: "Ví dụ, bạn có thể yêu cầu:",
    examples: [
      "Tạo lịch tuần sau từ ảnh bảng ca này",
      "Đọc URL Sheets này và chỉ tạo lịch cho ca đêm",
      "Thêm cả lịch di chuyển bằng ô tô từ nhà để kịp lịch lúc 18:00",
    ],
    audienceTitle: "Phù hợp với người",
    audienceItems: [
      "Thường phải nhập bảng ca vào lịch bằng tay.",
      "Muốn quản lý cả giờ xuất phát theo địa điểm của lịch.",
      "Muốn sắp xếp nội dung trong chat trước khi đăng ký lịch.",
    ],
  },
};

