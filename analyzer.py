import math
import re
from collections import Counter

AXES = ["フック","課題設定","具体性","信頼性","構成","読みやすさ","実行可能性","独自性"]

HOOK_WORDS = ["なぜ","実は","知らない","間違い","勘違い","失敗","やめた","危険","本当","理由","違い","結論"]
PROBLEM_WORDS = ["課題","問題","悩み","困","失敗","できない","うまくいか","詰ま","炎上","遅延","不足"]
ACTION_WORDS = ["方法","手順","やり方","チェック","テンプレ","使い方","ポイント","コツ","実践","明日","まず"]
TRUST_WORDS = ["経験","実務","現場","検証","事例","結果","データ","年","回","件","プロジェクト"]
STRUCTURE_WORDS = ["まとめ","結論","理由","原因","方法","ポイント","ステップ","最後に"]

def clamp(x):
    return max(0, min(10, int(round(x))))

def headings(body):
    lines = [x.strip() for x in body.splitlines() if x.strip()]
    out = []
    for line in lines:
        if len(line) <= 55 and (
            re.match(r"^(#{1,3}\s*)", line) or
            re.match(r"^[0-9０-９一二三四五六七八九十]+[\.．、：: ]", line) or
            line.startswith(("■","▼","◆","【"))
        ):
            out.append(line)
    return out[:40]

def sentence_lengths(text):
    ss = [s.strip() for s in re.split(r"[。！？!?]\s*", text) if s.strip()]
    return [len(s) for s in ss]

def count_any(text, words):
    return sum(text.count(w) for w in words)

def analyze(title, body):
    clean = re.sub(r"\s+", " ", body)
    hs = headings(body)
    sl = sentence_lengths(clean)
    avg_sentence = sum(sl)/len(sl) if sl else 50
    nums = len(re.findall(r"\d+(?:\.\d+)?(?:%|％|件|人|年|回|つ|個|円|分|日|時間)?", clean))
    bullets = len(re.findall(r"(?:^|\n)\s*[-・●✓☑□]", body))
    questions = title.count("?")+title.count("？")+clean[:1200].count("？")
    paragraphs = len([x for x in body.split("\n") if x.strip()])
    title_len = len(title)

    hook_signal = count_any(title, HOOK_WORDS)*1.7 + questions*1.5 + (1 if 14 <= title_len <= 36 else 0)
    problem_signal = count_any(clean[:2500], PROBLEM_WORDS)
    action_signal = count_any(clean, ACTION_WORDS)
    trust_signal = count_any(clean, TRUST_WORDS) + min(nums, 20)*0.35
    structure_signal = len(hs)*0.6 + count_any(" ".join(hs), STRUCTURE_WORDS)*0.8
    concrete_signal = min(nums, 25)*0.28 + bullets*0.35 + min(len(hs), 15)*0.2
    readability_signal = (3 if 20 <= avg_sentence <= 55 else 1) + min(paragraphs/12, 4) + min(bullets/4, 2)
    unique_signal = (
        (2 if "私" in clean[:6000] or "僕" in clean[:6000] else 0)
        + (2 if count_any(clean, ["失敗","気づ","変え","学ん"]) >= 2 else 0)
        + min(len(set(re.findall(r"[ァ-ヶ一-龠]{3,}", title))), 4)
    )

    scores = {
        "フック": clamp(3.5 + hook_signal),
        "課題設定": clamp(3 + min(problem_signal, 12)*0.55),
        "具体性": clamp(2.5 + concrete_signal),
        "信頼性": clamp(2.5 + min(trust_signal, 16)*0.45),
        "構成": clamp(3 + min(structure_signal, 12)*0.55),
        "読みやすさ": clamp(2.5 + readability_signal),
        "実行可能性": clamp(2.5 + min(action_signal, 12)*0.6 + min(bullets, 8)*0.25),
        "独自性": clamp(2.5 + unique_signal),
    }
    total = sum(scores.values())

    patterns = []
    if scores["フック"] >= 7:
        patterns.append({
            "pattern_name":"認識転換フック",
            "abstract_knowledge":"タイトル・冒頭で読者の常識や思い込みに疑問を置き、続きを読む理由を作る。"
        })
    if scores["課題設定"] >= 7:
        patterns.append({
            "pattern_name":"現場課題起点",
            "abstract_knowledge":"定義説明から入らず、読者が遭遇する具体的な困りごとから本題へ入る。"
        })
    if scores["具体性"] >= 7:
        patterns.append({
            "pattern_name":"具体例→抽象化",
            "abstract_knowledge":"数値・事例・手順などの具体物を示した後に、再利用できる判断基準へ抽象化する。"
        })
    if scores["構成"] >= 7:
        patterns.append({
            "pattern_name":"問題→原因→解決",
            "abstract_knowledge":"問題を提示し、原因を分解してから、解決策と実行方法へ段階的につなぐ。"
        })
    if scores["実行可能性"] >= 7:
        patterns.append({
            "pattern_name":"明日使える着地",
            "abstract_knowledge":"読了後の行動を、チェックリスト・手順・判断軸など実行可能な単位まで落とす。"
        })
    if scores["信頼性"] >= 7 and scores["独自性"] >= 6:
        patterns.append({
            "pattern_name":"実務経験による裏付け",
            "abstract_knowledge":"一般論だけでなく、経験・検証・具体的な判断材料を用いて主張を裏付ける。"
        })
    if scores["読みやすさ"] >= 8:
        patterns.append({
            "pattern_name":"短段落＋小見出し",
            "abstract_knowledge":"文章を短い意味単位に区切り、小見出しと箇条書きで読者の認知負荷を下げる。"
        })

    signals = {
        "見出し推定数": len(hs),
        "数値表現数": nums,
        "箇条書き推定数": bullets,
        "平均文長": round(avg_sentence,1),
        "本文文字数": len(clean)
    }
    return {"scores":scores,"total_score":total,"patterns":patterns,"signals":signals}

def keyword_candidates(items, limit=25):
    text = " ".join((x.get("title") or "") for x in items)
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9+.#-]{2,}|[ァ-ヶー]{3,}|[一-龠]{2,}", text)
    stop = {
        "する","して","した","ある","いる","その","この","ため","から","まで","こと","もの",
        "記事","note","解説","紹介","まとめ","方法","理由","自分","考え","使い","使う"
    }
    c = Counter(t for t in tokens if t not in stop and len(t) >= 2)
    return [x for x,_ in c.most_common(limit)]
