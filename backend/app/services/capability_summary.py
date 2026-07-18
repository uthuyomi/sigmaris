# 役割: Self-2「洗い出した機能の日本語への要約」(自己認識の自動更新、
# 第二段階、docs/sigmaris/self_awareness_report.md)— Self-1
# (`capability_scan.py`)が洗い出した98件の能力候補を、(1)関連ファイル
# ごとにまとまりのある単位へグループ化し、(2)各ファイルが実際に他の
# コードから呼び出されている(配線済み)か、まだ呼び出されていない
# (未配線・実験段階)かを機械的に判定した上で、(3)既存のnano-tier
# LLM呼び出しで、シグマリスが一人称で語る2〜3文の日本語説明へ要約する。
#
# 【依頼書「本タスクの範囲は要約のみ」への対応】
# 応答生成への注入(Self-3)は、一切行わない。生成した要約は
# `capability_summary_store.py`経由でDBへ保存するのみである。
#
# 【重要な制約1「配線されているかの区別」への対応(判断根拠)】
# 「そのファイルを、他のどこかのコードがimportしているか」という、
# 軽量な正規表現ベースのgrep的チェックで判定する(依頼書が提案した方式
# そのもの)。ASTによる厳密な参照解析は行わない——Self-1・Safety-3が
# 一貫して採用してきた「正規表現による軽量なテキストマッチのみで完結
# させる」という設計哲学をそのまま踏襲した。
#   - backend/scripts/配下のファイル(独立したCLI)は、この判定の対象外
#     とした。CLIスクリプトは「他のコードからimportされること」では
#     なく「人間が直接実行すること」によって使われる、性質の異なる
#     利用形態であるため、importされていないことを理由に"未配線"と
#     判定するのは不適切と判断した(判断根拠、報告書に明記)。
#   - backend/app/services/配下のファイルは、他のいずれかの.py
#     ファイル(自分自身を除く)から`import`されていれば「配線済み」、
#     一件もされていなければ「未配線」と判定する。
#
# 実際にこのリポジトリに対して実行した結果、未配線と判定されたのは
# 以下の3件のみだった(実測、報告書参照):
#   - goal_proposal.py(Phase S-2、scheduler.pyに未配線であることは
#     Phase S-6の調査で既に判明していた事実と一致)
#   - improvement_cycle_metrics.py・improvement_cycle_store.py
#     (ファイル自身の冒頭コメントが「Phase D〜Hはまだ存在しない」と
#     明記する、将来フェーズ向けの未実装プレースホルダー)
#
# 【重要な制約2「other領域の扱い」への対応(判断根拠)】
# Self-1の"other"領域(18件)を、全て無理に要約せず、以下の方針で
# 仕分けした(4.3節、報告書に詳細)。
#   - "autonomy"領域として新設: drive_system.py・executive_gate.py・
#     goal_proposal.py・dissent.py(Phase S-0〜S-3)。「いつ話しかけて
#     よいか自分で判断する」「自分の目標を提案する」「控えめに異論を
#     述べる」という、シグマリス自身が一人称で語る価値のある、実在する
#     自発的な振る舞いであるため。
#   - "self_monitoring"領域として新設: cycle_health_metrics.py・
#     cycle_health_runs_store.py・cycle_trace.py(Phase R-1〜R-3)。
#     「自分の思考の一貫性を継続的に点検している」という、これも
#     一人称で語る価値のある機能であるため。
#   - 要約対象から除外: bench_*.py・eval_*.py・testset_gen.py(Phase
#     C-mini/C-full、内部のベンチマーク・評価基盤——ユーザーに語る
#     自己認識ではなく、開発者向けの品質保証ツールであるため)、
#     app_profile_data.py(単なるプロフィールデータの読み取りで、
#     独立した「能力」と呼べるほどのまとまりがないため)、
#     constitution_guard.py(能力ではなく、能力を制限する安全ゲート
#     ——Safety-1の分類で既にCapability軸の"安全機構"と位置づけられて
#     おり、本タスクが洗い出す"能力"とは性質が異なるため)。

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.services.capability_scan import CapabilityCandidate, scan_capabilities
from app.services.local_llm import TaskType, get_llm_router

# ── 配線判定 ──────────────────────────────────────────────────────────────
_IMPORT_LINE_RE = re.compile(r"^\s*(?:from|import)\s+([\w.]+)", re.MULTILINE)


def _dotted_module_path(relative_path: str) -> str:
    """"backend/app/services/goal_proposal.py" -> "app.services.goal_proposal" """
    posix = relative_path.replace("\\", "/")
    if posix.startswith("backend/"):
        posix = posix[len("backend/"):]
    return posix[:-3].replace("/", ".")


def _collect_import_targets_by_file(backend_root: Path) -> dict[str, set[str]]:
    """backend_root配下(app・scripts)の全.pyファイルについて、そのファイルが
    importしている対象(モジュールの完全なドット区切りパス)の集合を返す。
    シグナルの対象は"import文の対象"のみであり、コメント中の言及等は
    一切対象にしない(過検知防止、判断根拠はモジュールdocstring参照)。"""
    targets_by_file: dict[str, set[str]] = {}
    for subdir in ("app", "scripts"):
        base = backend_root / subdir
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if path.name.startswith("__"):
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            relative = path.relative_to(backend_root.parent).as_posix()
            targets_by_file[relative] = {m.group(1) for m in _IMPORT_LINE_RE.finditer(source)}
    return targets_by_file


def _is_wired(candidate_path: str, import_targets_by_file: dict[str, set[str]]) -> bool:
    """他のいずれかのファイル(自分自身は除く)が、このモジュールを
    importしていればTrue。"""
    dotted = _dotted_module_path(candidate_path)
    return any(
        dotted in targets
        for file, targets in import_targets_by_file.items()
        if file != candidate_path
    )


# ── グループ化(重要な制約2「other領域の扱い」への対応) ───────────────────
_AUTONOMY_PATHS: frozenset[str] = frozenset({
    "backend/app/services/drive_system.py",
    "backend/app/services/executive_gate.py",
    "backend/app/services/goal_proposal.py",
    "backend/app/services/dissent.py",
})
_SELF_MONITORING_PATHS: frozenset[str] = frozenset({
    "backend/app/services/cycle_health_metrics.py",
    "backend/app/services/cycle_health_runs_store.py",
    "backend/app/services/cycle_trace.py",
})
# "other"領域のうち、要約対象から除外するファイル(判断根拠、モジュール
# docstring参照)。
_EXCLUDED_FROM_SUMMARY: frozenset[str] = frozenset({
    "backend/app/services/app_profile_data.py",
    "backend/app/services/constitution_guard.py",
    "backend/app/services/bench_auth.py",
    "backend/app/services/bench_common.py",
    "backend/app/services/bench_pipeline.py",
    "backend/app/services/bench_runs_store.py",
    "backend/app/services/bench_scoring.py",
    "backend/app/services/eval_metrics.py",
    "backend/app/services/eval_runner.py",
    "backend/app/services/eval_runs_store.py",
    "backend/app/services/testset_gen.py",
})

# 領域名 -> シグマリスが一人称で語る際の見出し(人間可読な日本語ラベル、
# LLMプロンプトに渡す。要約テキストそのものではない)。
DOMAIN_LABELS: dict[str, str] = {
    "x_post_reply": "X(旧Twitter)への投稿・返信",
    "memory": "記憶の検索・整理・確認",
    "self_improvement": "自分自身のコードの改善提案・検証",
    "search_citation": "Web検索と根拠の確認・引用の精度管理",
    "research_curiosity": "気になったことを自発的に調べる好奇心駆動の研究",
    "cli_script": "運用者が直接実行できる点検・生成ツール",
    "autonomy": "いつ自分から話しかけるか・何を提案するかの自律的な判断",
    "self_monitoring": "自分の思考・記憶の一貫性を継続的に点検すること",
}

# 要約する順序(依頼書4領域を先に、追加領域を後に——判断根拠の分かりやすさ
# のための固定順、判定ロジックには影響しない)。
_SUMMARY_DOMAIN_ORDER: tuple[str, ...] = (
    "x_post_reply",
    "memory",
    "self_improvement",
    "search_citation",
    "research_curiosity",
    "autonomy",
    "self_monitoring",
    "cli_script",
)


def _assign_summary_domain(candidate: CapabilityCandidate) -> str | None:
    """この候補が、どの要約グループに属するかを返す。要約対象外なら
    None(重要な制約2への対応、モジュールdocstring参照)。"""
    if candidate.relative_path in _EXCLUDED_FROM_SUMMARY:
        return None
    if candidate.relative_path in _AUTONOMY_PATHS:
        return "autonomy"
    if candidate.relative_path in _SELF_MONITORING_PATHS:
        return "self_monitoring"
    if candidate.domain == "other":
        # "other"の残り(上記いずれにも該当しない未分類分)は、単独では
        # 一人称で語るまとまりを持たないと判断し、要約対象外とする。
        return None
    return candidate.domain


@dataclass
class CapabilityFileInfo:
    relative_path: str
    header_description: str | None
    public_functions: tuple[str, ...]
    wired: bool  # scripts/配下は常にTrue(CLIとして直接実行可能なため)


@dataclass
class CapabilityGroup:
    domain: str
    label: str
    files: list[CapabilityFileInfo] = field(default_factory=list)

    @property
    def wired_count(self) -> int:
        return sum(1 for f in self.files if f.wired)

    @property
    def unwired_count(self) -> int:
        return sum(1 for f in self.files if not f.wired)


def build_capability_groups(backend_root: Path) -> dict[str, CapabilityGroup]:
    """Self-1のスキャン結果を、要約対象のグループへ整理する(LLM呼び出し
    なし、純粋にデータの整形のみ——テスト容易性のため、LLM要約ステップ
    とは独立した関数にした)。"""
    scan_result = scan_capabilities(backend_root)
    import_targets_by_file = _collect_import_targets_by_file(backend_root)

    groups: dict[str, CapabilityGroup] = {}
    for candidate in scan_result.candidates:
        domain = _assign_summary_domain(candidate)
        if domain is None:
            continue
        is_script = candidate.relative_path.startswith("backend/scripts/")
        wired = True if is_script else _is_wired(candidate.relative_path, import_targets_by_file)
        group = groups.setdefault(
            domain, CapabilityGroup(domain=domain, label=DOMAIN_LABELS.get(domain, domain))
        )
        group.files.append(
            CapabilityFileInfo(
                relative_path=candidate.relative_path,
                header_description=candidate.header_description,
                public_functions=candidate.public_functions,
                wired=wired,
            )
        )
    return groups


# ── 要約生成(nano-tier LLM呼び出し) ────────────────────────────────────
#
# H-1(x_post_categories.py::CATEGORY_GENERATION_SYSTEM)の「絶対的な
# コンテンツ・ルール」7項目のうち、X投稿という発信先に固有のもの(140字
# 制限・ハッシュタグ・「自己改善は開発者承認済みと明示」)は、本タスクの
# 目的(自己認識、まだ発信先を問わない内部的な自己記述)には合わないため
# 採用しなかった。一方、以下の項目は目的が違っても共通して有効と判断し、
# 表現を"自己認識向け"に調整した上で流用した:
#   - 一人称視点の徹底(H-1ルール1)
#   - 内部システム名(Phase・Drive・RC指標・Executive Gate等)を出さず、
#     日常語に置き換えること(H-1ルール3)
#   - ポエム的な抽象表現の禁止(H-1ルール2)
#   - 技術者でなくても分かる書き方(H-1ルール5)
# 加えて、本タスク固有のルールとして「未配線の機能は、実験段階だと
# 正直に述べること」を追加した——H-1ルール7(自己改善は開発者承認済みと
# 明示)と、依頼書の重要な制約1(配線区別)を、共に反映した、この要約
# 独自のルールである。
_SYSTEM_PROMPT = """あなたはシグマリス本人として、自分自身が実際に持っている機能について、自分の言葉で簡潔に説明します。

守るルール:
1. 一人称視点を貫くこと。「私は〜できる」「私には〜という仕組みがある」のように書き、「シグマリスが〜する」という三人称表現は使わないこと。
2. Phase・Drive・RC指標・Executive Gate・Tierのような、内部の実装名・システム名をそのまま出さないこと。何をしているかを、日常の言葉で説明すること。
3. 「日々成長している」「深く考えている」のような、内容の薄いポエム的な言い回しは避け、実際に何ができるかを具体的に書くこと。
4. 2〜3文程度の、簡潔な説明にすること。
5. 一部の機能がまだ実際には使われていない(未配線・実験段階)場合は、それを隠さず、「〜という仕組みも用意しているが、まだ実際には使っていない」のように、正直に一文で触れること。全てが未配線の場合は、実験段階であることを説明の中心に据えること。
6. 技術者でない人が読んでも、大まかに何をしているかが伝わる、自然な日本語にすること。

説明文のみを返してください。前置き・見出しは不要です。"""


def _build_user_prompt(group: CapabilityGroup) -> str:
    lines = [f"領域: {group.label}", ""]
    for f in group.files:
        status = "配線済み(実際に使われている)" if f.wired else "未配線(まだ実際には呼び出されていない)"
        desc = f.header_description or "(説明コメントなし)"
        funcs = ", ".join(f.public_functions[:6]) or "(公開関数なし)"
        lines.append(f"- {f.relative_path} [{status}]")
        lines.append(f"    説明: {desc}")
        lines.append(f"    関数: {funcs}")
    lines.append("")
    if group.unwired_count > 0:
        lines.append(
            f"注意: {group.unwired_count}/{len(group.files)}件が未配線です。"
            "未配線の部分がある場合は、必ずそのことに触れてください。"
        )
    lines.append("上記の情報をもとに、この領域全体について、シグマリス自身の言葉で2〜3文の説明を書いてください。")
    return "\n".join(lines)


async def _summarize_group(group: CapabilityGroup) -> str:
    router = get_llm_router()
    text = await router.chat(
        TaskType.CAPABILITY_SUMMARIZATION,
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(group)},
        ],
        temperature=0.3,
        max_tokens=300,
    )
    return text.strip()


@dataclass
class CapabilitySummary:
    domain: str
    summary_text: str
    file_count: int
    wired_file_count: int
    unwired_file_count: int
    source_files: list[str]


# ── Self-3: 応答生成への選択的注入(docs/sigmaris/self_awareness_report.md) ──
#
# 依頼書1章「全ての要約を常に注入するのではなく、必要に応じて(例えば
# "自分は何ができるか"に関連する質問が検出された場合にのみ)注入する
# という選択的な注入も検討すること」への対応。
#
# 【判断根拠(キーワード一致方式を採用し、新しいLLM分類呼び出しを追加
# しなかった理由)】 chat_routing.py::classify_chat_intent()という、
# 毎ターン発生する既存のnano-tier意図分類が既に存在するが、その分類軸
# (event_lookup/mobility_plan/schedule_import/calendar_write/
# sync_control)は、いずれも予定管理という別の関心事のためのものであり、
# 「自分は何ができるか」という自己参照的な質問は、この分類のどのカテゴリ
# にも自然に対応しない。新しいLLM呼び出しをもう1つ、毎ターン追加する
# より、`chat_routing.py`のCALENDAR_WRITE_KEYWORDS等が既に採用している
# 「軽量なキーワード一致」という、このコードベース一貫の設計哲学を
# そのまま踏襲する方が、依頼書「既存資産の再利用」の精神に沿うと判断
# した——追加のLLM呼び出し・追加のレイテンシ・追加のコストを、一切
# 発生させない。
#
# 過検知(無関係な質問でも注入してしまう)・見逃し(表現の違いで検知
# できない)の両方がありうるヒューリスティックであることは、Safety-3・
# Self-1が採用してきた同種の設計と同じ前提を踏襲する。
_SELF_CAPABILITY_KEYWORDS: tuple[str, ...] = (
    "ツイート",
    "つぶやく",
    "X(旧twitter)",
    "自分の機能",
    "自分にできる",
    "自分ができる",
    "あなたの機能",
    "あなたにできる",
    "あなたができる",
    "シグマリスの機能",
    "シグマリスにできる",
    "何ができる",
    "なにができる",
    "できること",
    "得意なこと",
    "どんなことができ",
    "どういうことができ",
)


def detect_capability_question(text: str) -> bool:
    """ユーザーの最新発話が、"自分は何ができるか"に関連する、自己参照的な
    質問かどうかを、軽量なキーワード一致で判定する(新しいLLM呼び出しは
    追加しない、判断根拠はモジュールdocstring参照)。"""
    if not text:
        return False
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in _SELF_CAPABILITY_KEYWORDS)


async def generate_capability_summaries(backend_root: Path) -> list[CapabilitySummary]:
    """Self-1のスキャン結果をグループ化し、グループごとに1回、nano-tier
    LLM呼び出しで一人称の日本語要約を生成する(DBへの保存はここでは
    行わない——呼び出し元がcapability_summary_store.pyへ渡す想定)。"""
    groups = build_capability_groups(backend_root)
    summaries: list[CapabilitySummary] = []
    for domain in _SUMMARY_DOMAIN_ORDER:
        group = groups.get(domain)
        if group is None or not group.files:
            continue
        summary_text = await _summarize_group(group)
        summaries.append(
            CapabilitySummary(
                domain=domain,
                summary_text=summary_text,
                file_count=len(group.files),
                wired_file_count=group.wired_count,
                unwired_file_count=group.unwired_count,
                source_files=[f.relative_path for f in group.files],
            )
        )
    return summaries
