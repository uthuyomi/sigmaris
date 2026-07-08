from __future__ import annotations

# 役割: Phase C-full(LongMemEval/LoCoMo公開ベンチマーク)の共通データ型。
#
# LongMemEval・LoCoMoは元のJSON形式が大きく異なる(前者は既にuser/assistant
# ロールのchatトランスクript、後者は2話者の対話+数値カテゴリ)ため、
# bench_datasets.py の各ローダーがここで定義する共通の中間表現に正規化し、
# それ以降(bench_pipeline.py・bench_scoring.py・CLIスクリプト)は
# データセット固有の形式を一切意識しない設計にする。

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BenchMessage:
    """1発話。roleはSigmarisの既存パイプライン(memory_extractor.py等)が
    期待する"user"/"assistant"の2値に正規化済み。speakerは元データの話者名
    (LoCoMoの実名等)を保持するためのものでrole判定には使わない。"""

    role: str  # "user" | "assistant"
    content: str
    speaker: str | None = None


@dataclass(frozen=True)
class BenchSession:
    session_id: str
    timestamp: str | None
    messages: tuple[BenchMessage, ...]


@dataclass(frozen=True)
class BenchQuestion:
    question_id: str
    question: str
    gold_answer: str
    category: str  # 正規化済みカテゴリラベル(データセット横断で集計するため)
    raw_category: Any  # 元データのカテゴリ値(数値/文字列、デバッグ用に保持)
    is_adversarial: bool = False  # LoCoMoカテゴリ5相当(偽前提の質問)
    question_date: str | None = None  # LongMemEvalのquestion_date等、時制推論の参考情報


@dataclass(frozen=True)
class BenchInstance:
    """1つの独立した「会話+QA群」。LongMemEvalでは1レコード=1インスタンス
    (haystackセッション+その質問群)、LoCoMoでは1会話(conv-XX)=1インスタンス
    (全セッション+その会話に紐づく質問群)に対応する。

    重要: 異なるインスタンス間で記憶を共有してはならない(bench_pipeline.py
    がインスタンスごとにベンチ用user_idのuser_fact_itemsを洗い流してから
    ingestするのはこのため)。"""

    instance_id: str
    dataset: str  # "longmemeval" | "locomo"
    sessions: tuple[BenchSession, ...]
    questions: tuple[BenchQuestion, ...]
    source_file: str = field(default="", compare=False)
