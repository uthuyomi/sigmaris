from __future__ import annotations

# 役割: LongMemEval・LoCoMoの公開データセットファイルを、bench_common.py の
# 共通中間表現(BenchInstance)へ変換するローダー。
#
# 【重要】ここで変換するのは「データの形式」のみであり、質問文・正解・
# 会話内容そのものは一切生成・改変しない(公開データセットをそのまま使う、
# という要件そのもの)。データの入手方法・ライセンスは
# docs/sigmaris/phase_c_full_report.md 1章を参照。
#
# LongMemEval: 公式配布はSigmarisのuser/assistantロールと同じ形式
# (`{"role": "user"/"assistant", "content": "..."}`)のため、ロール変換は
# 不要でほぼそのまま取り込める。
#
# LoCoMo: 2話者(speaker_a/speaker_b、いずれも実在の人物名)の対話であり、
# Sigmarisの「ユーザー1人+シグマリス」という前提と構造が異なる。両話者の
# 発話をrole="user"として取り込み、発話本文の先頭に話者名を明示的に付与する
# ことで、抽出プロンプト側で話者を区別できるようにしている(判断根拠は
# 報告書2章に詳述)。

import json
import re
from pathlib import Path

from app.services.bench_common import BenchInstance, BenchMessage, BenchQuestion, BenchSession

# LongMemEvalのquestion_typeは元データが既に人間可読な文字列(ハイフン区切り)
# なので、アンダースコア区切りへ正規化するだけで独自のラベルは付けない。
_LONGMEMEVAL_ABSTENTION_TYPES = frozenset({"abstention"})

# LoCoMoの数値カテゴリ→ラベル対応表。
#
# 【出典・裏付け】LoCoMo公式リポジトリ(snap-research/locomo)の
# task_eval/evaluation.py の採点分岐(category==1のみ多段階回答の分割評価、
# category in [2,3,4]は単純F1評価、category==5は「no information
# available」等の拒否表現の有無で判定)と、公開されている集計値
# (category別の総設問数: 1=282件, 2=321件, 3=96件, 4=830件, 5=445件)を、
# 実際にダウンロードしたlocomo10.json内の1会話(conv-26)のカテゴリ分布
# (1=32, 2=37, 3=13, 4=70, 5=47 — 4が最多・3が最少という相対順序が全体集計
# と一致)と突き合わせて確認した。論文本文の説明文だけでは1〜5の数値と
# ラベルの対応が特定できなかった(カテゴリ名の列挙順と数値が一致しない)ため、
# コード上の分岐ロジック+実データの分布という2つの独立した根拠から特定した。
_LOCOMO_CATEGORY_MAP: dict[int, str] = {
    1: "multi_hop",
    2: "temporal_reasoning",
    3: "open_domain",
    4: "single_hop",
    5: "adversarial",
}

_SESSION_KEY_RE = re.compile(r"^session_(\d+)$")


def load_longmemeval_file(path: str | Path) -> list[BenchInstance]:
    """LongMemEvalの配布JSON(oracle/s/m、いずれも同一スキーマ)を読み込む。

    公式スキーマでは1レコード=1質問+その質問専用のhaystackセッション群
    (`docs/sigmaris/phase_c_full_report.md`1章参照)であり、複数レコードで
    haystackが共有される場合でも、本ローダーはレコード単位で独立した
    BenchInstanceとして扱う(2章の「インスタンス間で記憶を混在させない」
    設計と整合させるため、意図的に統合しない)。
    """
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Unexpected LongMemEval file shape (expected a JSON list): {path}")

    instances: list[BenchInstance] = []
    for entry in raw:
        session_ids = entry.get("haystack_session_ids") or []
        session_turns_list = entry.get("haystack_sessions") or []
        session_dates = entry.get("haystack_dates") or [None] * len(session_ids)

        # 日付文字列は "YYYY/MM/DD (Mon) HH:MM" 形式でゼロ埋め・固定幅のため、
        # 文字列としての辞書順ソートがそのまま時系列順になる(専用の日付
        # パーサは不要 — 実データで確認済み)。提供順は時系列順ではないため、
        # 明示的にソートする(知識更新カテゴリで新しい情報を後から投入する
        # 順序が重要なため)。
        triples = sorted(
            zip(session_ids, session_turns_list, session_dates, strict=False),
            key=lambda t: t[2] or "",
        )

        sessions: list[BenchSession] = []
        for session_id, turns, date in triples:
            messages = tuple(
                BenchMessage(
                    role=str(turn.get("role") or "user"),
                    content=str(turn.get("content") or "").strip(),
                )
                for turn in (turns or [])
                if str(turn.get("content") or "").strip()
            )
            if messages:
                sessions.append(BenchSession(session_id=str(session_id), timestamp=date, messages=messages))

        question_type = str(entry.get("question_type") or "unknown")
        category = question_type.replace("-", "_")
        question = BenchQuestion(
            question_id=str(entry["question_id"]),
            question=str(entry.get("question") or ""),
            gold_answer=str(entry.get("answer") or ""),
            category=category,
            raw_category=question_type,
            is_adversarial=question_type in _LONGMEMEVAL_ABSTENTION_TYPES,
            question_date=entry.get("question_date"),
        )

        instances.append(
            BenchInstance(
                instance_id=str(entry["question_id"]),
                dataset="longmemeval",
                sessions=tuple(sessions),
                questions=(question,),
                source_file=str(path),
            )
        )
    return instances


def load_locomo_file(path: str | Path) -> list[BenchInstance]:
    """LoCoMoの配布JSON(locomo10.json、全10会話)を読み込む。

    1会話(`sample_id`)=1BenchInstance。その会話に紐づく全QA
    (`qa`フィールド)が同じインスタンスの質問群になる — LongMemEvalとは
    異なり、1インスタンスに数十〜約200件の質問が対応する。
    """
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Unexpected LoCoMo file shape (expected a JSON list): {path}")

    instances: list[BenchInstance] = []
    for conv_entry in raw:
        conv = conv_entry.get("conversation") or {}
        sample_id = str(conv_entry.get("sample_id") or f"locomo_{len(instances)}")

        session_keys = sorted(
            (key for key in conv if _SESSION_KEY_RE.match(key)),
            key=lambda key: int(_SESSION_KEY_RE.match(key).group(1)),  # type: ignore[union-attr]
        )

        sessions: list[BenchSession] = []
        for key in session_keys:
            turns = conv.get(key) or []
            timestamp = conv.get(f"{key}_date_time")
            messages = tuple(
                BenchMessage(
                    role="user",  # 2章参照: LoCoMoに"assistant"に相当する話者はいない
                    content=f"{turn.get('speaker', '')}: {turn.get('text', '')}".strip(": ").strip(),
                    speaker=turn.get("speaker"),
                )
                for turn in turns
                if str(turn.get("text") or "").strip()
            )
            if messages:
                sessions.append(BenchSession(session_id=key, timestamp=timestamp, messages=messages))

        questions: list[BenchQuestion] = []
        for idx, qa in enumerate(conv_entry.get("qa") or []):
            raw_category = qa.get("category")
            is_adversarial = raw_category == 5
            if "answer" in qa:
                gold_answer = str(qa["answer"])
            else:
                # カテゴリ5(adversarial)の大半はここ — "adversarial_answer"は
                # 正解ではなく「システムが確証してはいけない偽の主張」であり、
                # 採点(bench_pipeline.py)側でis_adversarialを見て扱いを変える。
                gold_answer = str(qa.get("adversarial_answer") or "")
            category = _LOCOMO_CATEGORY_MAP.get(raw_category, f"unknown_{raw_category}")
            questions.append(
                BenchQuestion(
                    question_id=f"{sample_id}_q{idx}",
                    question=str(qa.get("question") or ""),
                    gold_answer=gold_answer,
                    category=category,
                    raw_category=raw_category,
                    is_adversarial=is_adversarial,
                )
            )

        instances.append(
            BenchInstance(
                instance_id=sample_id,
                dataset="locomo",
                sessions=tuple(sessions),
                questions=tuple(questions),
                source_file=str(path),
            )
        )
    return instances
