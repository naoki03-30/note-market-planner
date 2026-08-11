import os
from openai import OpenAI

MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")

def _client():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY が設定されていません。Streamlit Secrets に設定してください。")
    return OpenAI(api_key=key)

def _ask(prompt: str) -> str:
    client = _client()
    response = client.responses.create(
        model=MODEL,
        input=prompt,
    )
    return response.output_text.strip()

def generate_first_pass(plan: dict, experiences: dict, market_patterns: list[dict], target_chars: int, paid_boundary: str) -> str:
    patterns = "\n".join(
        f"- {p.get('pattern_name')}: {p.get('abstract_knowledge','')} "
        f"(出現率 {p.get('rate','-')}%)"
        for p in market_patterns[:5]
    ) or "- 特定の勝ち型なし"

    outline = "\n".join(
        f"{i+1}. {s.get('section')}\n"
        f"   役割: {s.get('purpose')}\n"
        f"   書く内容: {s.get('write')}"
        for i, s in enumerate(plan.get("outline", []))
    )

    exp = "\n".join(
        f"- {k}: {v}" for k, v in experiences.items() if str(v).strip()
    ) or "- 追加の実体験情報なし"

    return _ask(f"""
あなたは日本語のnote記事を専門に編集するライターです。
以下の企画・市場パターン・筆者本人の実体験を使い、約{target_chars}字の第1稿を書いてください。

【タイトル】
{plan.get('title','')}

【コアメッセージ】
{plan.get('core_message','')}

【市場の勝ち型】
{patterns}

【記事構成】
{outline}

【筆者本人の実体験・主張】
{exp}

【無料/有料の境界】
{paid_boundary or '全編無料'}

厳守:
- 市場分析した他者記事の文章・固有表現を模倣しない。
- 他者記事の本文を引用しない。
- 筆者が入力していない経歴、数字、成功談、失敗談を捏造しない。
- 実体験情報が不足する箇所は、一般論で無理に埋めず、自然な範囲で説明する。
- 冒頭3段落で読者の課題と読む価値を明確にする。
- タイトルと本文内容を一致させる。
- タイトルが「5つ」なら本文も必ず5項目にするなど、数の整合性を守る。
- PM/SE向けの記事では、抽象論だけでなく判断基準・具体例・実行手順まで落とす。
- noteで読みやすい短めの段落と見出しを使う。
- 有料境界を指定した場合、その直前で無料部分だけでも価値を感じられるようにする。
- Markdown形式の完成記事だけ返す。
""")

def revise_second_pass(plan: dict, first_pass: str, market_patterns: list[dict], target_chars: int) -> str:
    patterns = "\n".join(
        f"- {p.get('pattern_name')}: {p.get('abstract_knowledge','')}"
        for p in market_patterns[:5]
    ) or "- 特定の勝ち型なし"

    return _ask(f"""
あなたはnoteの編集長です。
以下の第1稿を最初から最後まで読み直し、第2稿として完成度を上げてください。

【タイトル】
{plan.get('title','')}

【コアメッセージ】
{plan.get('core_message','')}

【市場分析で得た勝ち型】
{patterns}

【第1稿】
{first_pass}

レビュー観点:
1. タイトルと本文の約束が一致しているか
2. 冒頭3段落で続きを読みたくなるか
3. 読者の課題が具体的か
4. 実務経験と一般論が区別されているか
5. 根拠のない数字・経歴・体験が追加されていないか
6. 問題→原因→判断→行動の流れが自然か
7. 各見出しの役割が重複していないか
8. 具体性・信頼性・実行可能性が十分か
9. 冗長表現を削り、約{target_chars}字を目安に整える
10. 他者記事の表現を模倣していないか
11. 「5つ」「3つ」などタイトルの数字と本文の項目数が一致しているか
12. 読後に読者が何をすればよいか明確か

第1稿への講評は出力せず、修正後のMarkdown完成記事だけ返してください。
""")
