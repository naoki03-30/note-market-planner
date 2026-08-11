from collections import Counter

def pattern_rank(pattern_rows):
    c = Counter(p["pattern_name"] for p in pattern_rows)
    return c.most_common()

def theme_ideas(tag, keywords, patterns, audience):
    kw = [k for k in keywords if k != tag][:8]
    seed = kw[0] if kw else tag
    seed2 = kw[1] if len(kw)>1 else "現場"
    ideas = [
        {
            "theme": f"{tag}で成果が出ない原因",
            "title": f"{tag}をやっているのに成果が出ないのはなぜか",
            "angle": "常識否定・課題起点"
        },
        {
            "theme": f"{tag}の失敗パターン",
            "title": f"{audience}が{tag}でやりがちな5つの失敗",
            "angle": "失敗回避・具体例"
        },
        {
            "theme": f"{tag}の判断基準",
            "title": f"{tag}で迷ったとき、最初に見るべき判断基準",
            "angle": "独自フレーム・実務"
        },
        {
            "theme": f"{seed}と{tag}",
            "title": f"{seed}を変えると、{tag}はどこまで良くなるのか",
            "angle": "市場キーワード掛け合わせ"
        },
        {
            "theme": f"{tag}の実務運用",
            "title": f"{tag}を「管理」で終わらせず、実務で機能させる方法",
            "angle": "問題→原因→解決"
        },
        {
            "theme": f"{seed2}で起きる{tag}のズレ",
            "title": f"{seed2}で{tag}が形骸化する3つの理由",
            "angle": "現場課題・原因分解"
        },
        {
            "theme": f"{tag}のチェックリスト",
            "title": f"明日から使える{tag}チェックリスト",
            "angle": "実行可能性"
        },
        {
            "theme": f"{tag}の初学者向け実践",
            "title": f"初めて{tag}を任された人が最初の1週間でやること",
            "angle": "時系列・手順"
        },
        {
            "theme": f"{tag}の比較",
            "title": f"{tag}が上手い人と、ただ作業している人の決定的な違い",
            "angle": "比較・認識転換"
        },
        {
            "theme": f"{tag}の改善",
            "title": f"{tag}が回らないときに、まず捨てるべきもの",
            "angle": "強いフック・改善"
        }
    ]
    return ideas

def build_plan(tag, audience, selected_theme, selected_title, personal_context, pattern_names):
    use_problem = any("課題" in x or "問題" in x for x in pattern_names) or True
    outline = [
        {
            "section":"冒頭フック",
            "purpose":"読者が自分事化できる状況を示し、一般的な思い込みを一度崩す。",
            "write":"よくある現場の状態を2〜4文で描写し、「問題は○○ではなく△△」という主張につなぐ。",
            "need_from_author":"実際に見た失敗・違和感・困った場面を1つ。"
        },
        {
            "section":"この記事の結論",
            "purpose":"最後まで読む価値を早めに提示する。",
            "write":"この記事で最も伝えたい判断基準を1文で言い切る。",
            "need_from_author":"自分なりに最重要だと思う原則。"
        },
        {
            "section":"なぜうまくいかないのか",
            "purpose":"問題を3〜5個の原因へ分解する。",
            "write":"各原因を『症状→原因→放置時の影響』で説明する。",
            "need_from_author":"過去に起きた失敗例・兆候。"
        },
        {
            "section":"実務で見るべき判断基準",
            "purpose":"一般論ではなく、筆者固有の実務知へ変える。",
            "write":"3〜5個の判断軸を作り、それぞれ『何を見るか／なぜ見るか』を書く。",
            "need_from_author":"普段最初に確認する項目、優先順位の決め方、エスカレーション基準。"
        },
        {
            "section":"具体例",
            "purpose":"抽象論を読者が再現できる形へ落とす。",
            "write":"Before→判断→Action→Afterの順で1ケース示す。機密情報や固有名詞は一般化する。",
            "need_from_author":"改善前後が分かる実例。"
        },
        {
            "section":"明日から使える実行手順",
            "purpose":"読後の行動を明確にする。",
            "write":"3〜7ステップの手順、またはチェックリストとして提示する。",
            "need_from_author":"自分が実際に使っている確認手順。"
        },
        {
            "section":"まとめ",
            "purpose":"主張を再提示し、読者の次の行動につなげる。",
            "write":"3点程度で要約し、まず1つ試す行動を指定する。",
            "need_from_author":"読者に最初に試してほしいこと。"
        }
    ]
    core = f"{selected_theme}について、知識の説明ではなく『現場で判断し、行動するための基準』を読者に渡す。"
    if personal_context.strip():
        core += " 筆者の実体験を根拠として入れ、一般論との差を作る。"
    return {
        "theme": selected_theme,
        "title": selected_title,
        "core_message": core,
        "outline": outline,
        "personal_context": personal_context
    }
