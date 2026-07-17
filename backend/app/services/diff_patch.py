# 役割: Phase F-3「承認フロー、及び、承認後のプルリクエスト作成」の一部
# ——F-1が生成した統一diffのテキストを、対象ファイルの実際の内容に対して
# 適用し、パッチ後の内容を計算する、純粋関数(I/Oなし)。
#
# 【なぜ、独自実装が必要か】backend/pyproject.tomlに、diff適用ライブラリ
# (例: `unidiff`、`patch`)は依存関係として存在しない。旧self_improvement.py
# (削除済み、git履歴 bea3ada~1 で参照可能)の_create_github_pr()は、実は
# 統一diffを一切適用しておらず、proposal.proposed_changeのテキストを、
# 対象ファイルの末尾にHTMLコメット付きで追記するだけだった——これは
# 「diffの適用」ではない。F-3は、F-1が実際に生成する統一diff形式を、
# 正しく対象ファイルへ適用する必要があるため、本モジュールを新設した。
#
# 【絶対原則、このファイルにも実装しないこと】
# 本モジュールは、渡された文字列(original_content, diff_text)に対する
# 純粋な文字列演算のみを行う。**ファイルの読み書き・git操作・ネットワーク
# 呼び出しは、一切行わない。** `subprocess`・`git`コマンド・ファイル
# システムへのI/Oは、このファイルのどこにも存在しない——読み書きは、
# 呼び出し元(github_pr_publisher.py)の責務。
#
# 【fail-closed方針】対象ファイルの内容が、diff生成時点から変化している
# 可能性がある(生成から承認までの間に、mainが進む等)。コンテキスト行・
# 削除行が、実際のファイル内容と一致しない場合、silent(不正確な結果を
# 黙って返す)ではなく、DiffApplyErrorを送出して失敗する——中途半端な
# 破損したファイル内容をコミットすることは、絶対に避けなければならない。

from __future__ import annotations

import re
from dataclasses import dataclass

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class DiffApplyError(Exception):
    """diffの適用に失敗した(コンテキスト不一致等)。呼び出し元は、この
    例外を握りつぶさず、PR作成そのものを中断すること。"""


@dataclass
class ParsedHunk:
    old_start: int  # 1-indexed
    old_count: int
    new_start: int
    new_count: int
    lines: list[str]  # 各行の先頭1文字が ' '/'-'/'+'、以降が本文


def _parse_hunks(diff_text: str) -> list[ParsedHunk]:
    """統一diffのテキストから、`--- a/...`/`+++ b/...`のファイルヘッダー
    行を無視し、`@@ ... @@`ハンク以降のみを解析する(複数ハンク対応)。"""
    lines = diff_text.splitlines()
    hunks: list[ParsedHunk] = []
    i = 0
    current: ParsedHunk | None = None
    while i < len(lines):
        line = lines[i]
        match = _HUNK_HEADER_RE.match(line)
        if match:
            if current is not None:
                hunks.append(current)
            old_start = int(match.group(1))
            old_count = int(match.group(2)) if match.group(2) is not None else 1
            new_start = int(match.group(3))
            new_count = int(match.group(4)) if match.group(4) is not None else 1
            current = ParsedHunk(old_start=old_start, old_count=old_count, new_start=new_start, new_count=new_count, lines=[])
        elif current is not None and line and line[0] in (" ", "-", "+"):
            current.lines.append(line)
        elif current is not None and line == "":
            # 空のコンテキスト行(先頭スペースが省略されたケース)
            current.lines.append(" ")
        # `--- a/...`・`+++ b/...`・`\ No newline at end of file`等は無視
        i += 1
    if current is not None:
        hunks.append(current)
    return hunks


def apply_unified_diff(original_content: str, diff_text: str) -> str:
    """original_contentに、diff_text(統一diff形式)を適用した結果を返す。

    対象ファイルの内容が、diff生成時点から変化しており、コンテキスト行・
    削除行が一致しない場合は、DiffApplyErrorを送出する(fail-closed、
    モジュールdocstring参照)。ハンクが1つも無い場合もDiffApplyError。
    """
    hunks = _parse_hunks(diff_text)
    if not hunks:
        raise DiffApplyError("diff_textに、有効なハンク(@@ ... @@)が1つも見つからない")

    original_lines = original_content.splitlines(keepends=True)
    # 末尾に改行が無い最終行も、splitlines(keepends=True)は正しく1要素として保持する

    result_lines: list[str] = []
    cursor = 0  # original_linesの、次にコピーすべき位置(0-indexed)

    for hunk in hunks:
        hunk_old_start_0 = hunk.old_start - 1  # 0-indexed
        if hunk_old_start_0 < cursor:
            raise DiffApplyError(
                f"ハンクの適用順序が不正、またはハンクが重複している(old_start={hunk.old_start})"
            )
        if hunk_old_start_0 > len(original_lines):
            raise DiffApplyError(
                f"ハンクの開始位置(行{hunk.old_start})が、対象ファイルの行数({len(original_lines)})を超えている"
            )

        # ハンク開始位置までは、そのままコピー
        result_lines.extend(original_lines[cursor:hunk_old_start_0])
        cursor = hunk_old_start_0

        for raw_line in hunk.lines:
            marker, body = raw_line[0], raw_line[1:]
            expected_with_nl = body + "\n"
            expected_no_nl = body

            if marker == " ":
                if cursor >= len(original_lines):
                    raise DiffApplyError(f"コンテキスト行が、ファイル末尾を超えて参照されている: {body!r}")
                actual = original_lines[cursor]
                if actual.rstrip("\n") != body:
                    raise DiffApplyError(
                        f"コンテキスト行が一致しない(行{cursor + 1}): 期待={body!r}, 実際={actual.rstrip(chr(10))!r}"
                    )
                result_lines.append(actual)
                cursor += 1
            elif marker == "-":
                if cursor >= len(original_lines):
                    raise DiffApplyError(f"削除行が、ファイル末尾を超えて参照されている: {body!r}")
                actual = original_lines[cursor]
                if actual.rstrip("\n") != body:
                    raise DiffApplyError(
                        f"削除行が一致しない(行{cursor + 1}): 期待={body!r}, 実際={actual.rstrip(chr(10))!r}"
                    )
                cursor += 1
            elif marker == "+":
                # 追加行は、末尾に改行を付与する(最終行の改行有無は、
                # 元ファイルの末尾スタイルに委ねる——下記の最終正規化を参照)
                result_lines.append(expected_with_nl)
            else:
                raise DiffApplyError(f"不明なdiff行のマーカー: {raw_line!r}")

    # 残りの行を、そのままコピー
    result_lines.extend(original_lines[cursor:])

    patched = "".join(result_lines)

    # 元ファイルが末尾改行を持たない場合、パッチ後の末尾に余計な改行が
    # 付与されないよう正規化する(最後の行が、追加行 or 元ファイルの
    # 最終行そのものであるケースの両方に対応)。
    if original_content and not original_content.endswith("\n") and patched.endswith("\n"):
        last_hunk_lines = hunks[-1].lines if hunks else []
        last_is_addition_or_context = bool(last_hunk_lines) and last_hunk_lines[-1][0] in (" ", "+")
        original_last_had_no_newline = not original_content.endswith("\n")
        if last_is_addition_or_context and original_last_had_no_newline and cursor >= len(original_lines):
            patched = patched[:-1]

    return patched
