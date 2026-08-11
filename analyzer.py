import re
from collections import Counter, defaultdict

AXES = ["フック","課題設定","具体性","信頼性","構成","読みやすさ","実行可能性","独自性"]

HOOK_WORDS = ["なぜ","実は","知らない","間違い","勘違い","失敗","やめた","危険","本当","理由","違い","結論","でも","ではない"]
PROBLEM_WORDS = ["課題","問題","悩み","困","失敗","できない","うまくいか","詰ま","炎上","遅延","不足","危険"]
ACTION_WORDS = ["方法","手順","やり方","チェック","テンプレ","使い方","ポイント","コツ","実践","明日","まず","改善","解決"]
TRUST_WORDS = ["経験","実務","現場","検証","事例","結果","データ","年","回","件","プロジェクト","実際"]
STRUCTURE_WORDS = ["まとめ","結論","理由","原因","方法","ポイント","ステップ","最後に","対策","解決"]

PATTERN_KNOWLEDGE = {
    "認識転換フック":"タイトル・冒頭で読者の常識や思い込みに疑問を置き、続きを読む理由を作る。",
    "数字入りタイトル":"数字や件数をタイトルに置き、記事で得られる情報量や具体性を直感的に伝える。",
    "現場課題起点":"定義説明から入らず、読者が遭遇する具体的な困りごとから本題へ入る。",
    "実体験起点":"筆者自身の経験・失敗・気づきを起点にし、一般論ではなく一次情報として語る。",
    "問題→原因→解決":"問題を提示し、原因を分解してから、解決策と実行方法へ段階的につなぐ。",
    "具体例→抽象化":"数値・事例・ケースを示した後に、他の場面でも使える判断基準へ抽象化する。",
    "明日使える着地":"読了後の行動を、チェックリスト・手順・判断軸など実行可能な単位まで落とす。",
    "短段落＋小見出し":"文章を短い意味単位に区切り、小見出しや箇条書きで認知負荷を下げる。",
    "比較・対比型":"AとB、できる人とできない人、Before/Afterなどの対比で違いを明確にする。",
}

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

def _pattern_candidates(title, body, hs, nums, bullets, avg_sentence):
    clean = re.sub(r"\s+", " ", body)
    intro = clean[:1800]
    title_l = title.lower()
    names = []

    def add(name):
        if name not in names:
            names.append(name)

    # タイトル・冒頭の認識転換
    if (
        any(w in title for w in HOOK_WORDS)
        or "？" in title or "?" in title
        or any(x in title for x in ["ではない","なのか","違い","でも"])
    ):
        add("認識転換フック")

    # 数字入りタイトル
    if re.search(r"[0-9０-９]+", title):
        add("数字入りタイトル")

    # 現場課題起点
    if count_any(title + intro, PROBLEM_WORDS) >= 2:
        add("現場課題起点")

    # 実体験
    first_person = any(x in intro for x in ["私は","僕は","自分は","私が","僕が"])
    experience = count_any(intro, ["経験","現場","実際","失敗","気づ","学ん","やってき"])
    if first_person and experience >= 1:
        add("実体験起点")

    # 問題→原因→解決
    has_problem = count_any(clean[:5000], PROBLEM_WORDS) >= 2
    has_reason = count_any(clean[:5000], ["原因","理由","なぜ","背景"]) >= 1
    has_solution = count_any(clean, ACTION_WORDS) >= 2
    if has_problem and (has_reason or has_solution):
        add("問題→原因→解決")

    # 具体例→抽象化
    concrete = nums >= 3 or count_any(clean, ["例えば","具体例","事例","ケース","実際"]) >= 2
    abstract = count_any(clean, ["ポイント","判断","共通","つまり","重要","原則","基準"]) >= 2
    if concrete and abstract:
        add("具体例→抽象化")

    # 実行可能性
    if bullets >= 2 or count_any(clean, ["チェックリスト","手順","ステップ","まず","次に","最後に"]) >= 2:
        add("明日使える着地")

    # 読みやすさ
    if len(hs) >= 3 or bullets >= 3 or avg_sentence <= 45:
        add("短段落＋小見出し")

    # 比較・対比
    if (
        re.search(r"(vs|VS|と.*の違い|できる.*できない|Before|After|ビフォー|アフター)", title + clean[:2500], re.I)
        or count_any(title, ["違い","比較"]) >= 1
    ):
        add("比較・対比型")

    return [
        {"pattern_name": name, "abstract_knowledge": PATTERN_KNOWLEDGE[name]}
        for name in names
    ]

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

    patterns = _pattern_candidates(title, body, hs, nums, bullets, avg_sentence)

    signals = {
        "見出し推定数": len(hs),
        "数値表現数": nums,
        "箇条書き推定数": bullets,
        "平均文長": round(avg_sentence,1),
        "本文文字数": len(clean),
        "pattern_names": [p["pattern_name"] for p in patterns],
    }
    return {"scores":scores,"total_score":total,"patterns":patterns,"signals":signals}

def aggregate_market_patterns(rows, top_k=5):
    """
    分析対象記事群を横断して、何記事に同じ型が出たかを集計。
    同一記事内で同じ型は1回として数える。
    """
    total_articles = len(rows)
    counts = Counter()
    score_sum = defaultdict(float)
    likes_sum = defaultdict(float)

    for row in rows:
        names = {
            p.get("pattern_name")
            for p in row.get("patterns", [])
            if p.get("pattern_name")
        }
        for name in names:
            counts[name] += 1
            score_sum[name] += row.get("total_score", 0) or 0
            likes_sum[name] += row.get("likes", 0) or 0

    results = []
    for name, count in counts.items():
        results.append({
            "pattern_name": name,
            "count": count,
            "rate": round((count / total_articles * 100), 1) if total_articles else 0,
            "abstract_knowledge": PATTERN_KNOWLEDGE.get(name, ""),
            "avg_article_score": round(score_sum[name] / count, 1),
            "avg_likes": round(likes_sum[name] / count, 1),
        })

    results.sort(
        key=lambda x: (x["count"], x["avg_likes"], x["avg_article_score"]),
        reverse=True
    )
    return results[:top_k]

def keyword_candidates(items, limit=25):
    text = " ".join((x.get("title") or "") for x in items)
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9+.#-]{2,}|[ァ-ヶー]{3,}|[一-龠]{2,}", text)
    stop = {
        "する","して","した","ある","いる","その","この","ため","から","まで","こと","もの",
        "記事","note","解説","紹介","まとめ","方法","理由","自分","考え","使い","使う"
    }
    c = Counter(t for t in tokens if t not in stop and len(t) >= 2)
    return [x for x,_ in c.most_common(limit)]
