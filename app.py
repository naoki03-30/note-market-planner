import json
import os

from dotenv import load_dotenv
load_dotenv()

import streamlit as st

from collector import collect
from analyzer import analyze, aggregate_market_patterns, keyword_candidates
from planner import pattern_rank, theme_ideas, build_plan
from llm import generate_first_pass, revise_second_pass
from db import (
    save_patterns, get_patterns, save_plan, list_plans, record_result,
    performance_by_pattern, export_all, save_generated_article, list_generated_articles
)

st.set_page_config(
    page_title="note Market Planner",
    page_icon="📈",
    layout="centered",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
.block-container{max-width:760px;padding-top:1rem;padding-bottom:6rem}
h1{font-size:1.8rem!important}
h2{font-size:1.35rem!important}
h3{font-size:1.15rem!important}
.stButton>button,.stDownloadButton>button{
 width:100%;min-height:48px;border-radius:12px;font-size:1rem
}
textarea,input{font-size:16px!important}
[data-testid="stMetricValue"]{font-size:1.35rem}
small,.stCaption{line-height:1.5}
</style>
""", unsafe_allow_html=True)

st.title("📈 note Market Planner")
st.caption("note市場を分析して、伸びやすいテーマと記事構成を作る")

for k,v in {
    "last_result":None,
    "analysis_rows":[],
    "selected_tag":"",
    "theme_candidates":[],
    "market_patterns":[]
}.items():
    if k not in st.session_state:
        st.session_state[k]=v

tab1,tab2,tab3,tab4,tab5,tab6 = st.tabs(["分析","勝ち型","企画","記事生成","実績","設定"])

with tab1:
    st.subheader("1. 市場を分析する")
    tag = st.text_input(
        "調べるnoteタグ",
        value=st.session_state.selected_tag or "プロジェクトマネジメント"
    )
    c1,c2 = st.columns(2)
    days = c1.selectbox("対象期間", [7,14,30], index=2)
    max_articles = c2.selectbox("取得記事数", [20,40,60,80,100], index=2)

    st.caption(
        "直近記事を取得し、30スキ以上またはタグ内上位20%の記事を分析します。"
    )

    if st.button("市場分析を実行", type="primary"):
        try:
            with st.spinner("note市場を分析しています"):
                result = collect(tag, int(days), int(max_articles))

                rows=[]
                for art in result["qualified"]:
                    x=analyze(art["title"],art["body"])
                    rows.append({
                        "url":art["url"],
                        "title":art["title"],
                        "likes":art["likes"],
                        **x
                    })

                    if x["patterns"]:
                        signals = dict(x["signals"])
                        signals["selection_basis"] = "top20pct_or_30likes"
                        signals["absolute_quality_60plus"] = x["total_score"] >= 60
                        save_patterns(
                            art["url"], tag, x["total_score"],
                            x["scores"], x["patterns"], signals
                        )

                    art["body"]=None

                result["qualified"]=[
                    {k:v for k,v in a.items() if k!="body"}
                    for a in result["qualified"]
                ]

                market_patterns = aggregate_market_patterns(rows, top_k=5)

                st.session_state.last_result=result
                st.session_state.analysis_rows=rows
                st.session_state.market_patterns=market_patterns
                st.session_state.selected_tag=tag

            st.success("市場分析が完了しました。")

        except Exception:
            st.error(
                "市場分析に失敗しました。少し時間を空けて再実行してください。"
            )

    r=st.session_state.last_result
    if r:
        c1,c2,c3 = st.columns(3)
        c1.metric("取得",r["found"])
        c2.metric("中央値",int(r["median_likes"]))
        c3.metric("分析対象",len(r["qualified"]))
        st.caption(
            f"絶対条件：30スキ以上 / 相対条件：上位{r.get('top_percent',20)}% "
            f"（境界 {r.get('relative_cutoff',0)}スキ）"
        )

        market_patterns = st.session_state.get("market_patterns", [])
        if market_patterns:
            st.markdown("### 市場の勝ち型TOP5")
            for i,p in enumerate(market_patterns,1):
                st.write(
                    f"**{i}. {p['pattern_name']}** — "
                    f"{p['count']}/{len(st.session_state.analysis_rows)}記事 "
                    f"({p['rate']}%)"
                )

        rows=st.session_state.analysis_rows
        if rows:
            st.markdown("### 市場上位記事")
            for x in sorted(rows,key=lambda z:(z["total_score"],z["likes"] or 0),reverse=True):
                with st.expander(f"{x['total_score']}点｜{x['likes']}スキ｜{x['title'][:45]}"):
                    st.write(x["scores"])
                    st.caption("抽象化した型："+" / ".join(p["pattern_name"] for p in x["patterns"]) if x["patterns"] else "型抽出なし")
                    st.caption(x["url"])
        else:
            st.warning("今回の条件では分析対象の記事が見つかりませんでした。期間または取得記事数を広げて再実行してください。")

with tab2:
    st.subheader("2. 勝ちパターン")
    st.caption("直近の分析対象記事を横断し、同じ型が何記事に現れたかで順位付けします。")

    market_patterns = st.session_state.get("market_patterns", [])
    analyzed_count = len(st.session_state.get("analysis_rows", []))

    if market_patterns:
        st.markdown("### 勝ち型TOP5")
        for i,p in enumerate(market_patterns,1):
            with st.expander(
                f"{i}. {p['pattern_name']}｜{p['count']}/{analyzed_count}記事（{p['rate']}%）",
                expanded=(i <= 3)
            ):
                st.write(p["abstract_knowledge"])
                st.caption(
                    f"該当記事の平均スキ：{p['avg_likes']} / "
                    f"平均8観点スコア：{p['avg_article_score']}"
                )
    else:
        st.info("市場分析を実行すると、上位記事群の共通パターンTOP5が表示されます。")

    ptag=st.text_input("保存済み知見をタグで絞る",value=st.session_state.selected_tag,key="pattern_filter")
    pats=get_patterns(ptag or None,200)
    if pats:
        st.markdown("### 保存された抽象知見")
        shown=set()
        for p in pats:
            key=(p["pattern_name"],p["abstract_knowledge"])
            if key in shown: continue
            shown.add(key)
            with st.expander(f"{p['pattern_name']}｜元記事 {p['total_score']}点"):
                st.write(p["abstract_knowledge"])
                st.caption("元本文は保存していません。")

with tab3:
    st.subheader("3. 記事企画を作る")
    st.caption("市場の勝ち型TOP5を優先して、テーマ・タイトル・記事構成を作ります。")
    tagp=st.text_input("テーマ領域",value=st.session_state.selected_tag or "プロジェクトマネジメント",key="plan_tag")
    audience=st.text_input("想定読者",value="若手PM・SE")
    personal=st.text_area(
        "今回使えそうな自分の経験・主張",
        height=130,
        placeholder="例：大規模PJで課題管理表が形骸化。担当・期限だけでなく次アクションと意思決定者を見るように変えた。"
    )
    source_rows=st.session_state.analysis_rows
    keywords=keyword_candidates(source_rows)
    patterns=get_patterns(tagp or None,100)
    market_patterns=st.session_state.get("market_patterns", [])
    top_pattern_names=[p["pattern_name"] for p in market_patterns[:5]]
    pattern_names=top_pattern_names or [p["pattern_name"] for p in patterns]
    ideas=theme_ideas(tagp,keywords,pattern_names,audience)

    st.markdown("### おすすめテーマ")
    labels=[f"{i+1}. {x['title']}" for i,x in enumerate(ideas)]
    choice=st.radio("書くテーマを選ぶ",labels,index=0)
    ix=labels.index(choice)
    selected=ideas[ix]
    st.caption(f"狙い：{selected['angle']}")

    if keywords:
        st.caption("市場タイトルから見えた頻出語："+" / ".join(keywords[:10]))

    if st.button("記事の土台を作る",type="primary"):
        plan=build_plan(
            tagp,audience,selected["theme"],selected["title"],
            personal,pattern_names
        )
        if top_pattern_names:
            preferred = [p for p in patterns if p["pattern_name"] in set(top_pattern_names)]
            used_ids=[p["id"] for p in preferred[:12]]
        else:
            used_ids=[p["id"] for p in patterns[:12]]
        plan_id=save_plan(tagp,audience,plan,used_ids)
        st.session_state["current_plan"]=(plan_id,plan,used_ids)

    if "current_plan" in st.session_state:
        pid,plan,used_ids=st.session_state["current_plan"]
        st.success(f"企画 #{pid} を保存しました。")
        st.markdown(f"### {plan['title']}")
        st.markdown(f"**コアメッセージ**  \n{plan['core_message']}")
        st.markdown("### 記事構成")
        for i,s in enumerate(plan["outline"],1):
            with st.expander(f"{i}. {s['section']}",expanded=(i<=2)):
                st.markdown(f"**役割**  \n{s['purpose']}")
                st.markdown(f"**書く内容**  \n{s['write']}")
                st.markdown(f"**あなたから必要な材料**  \n{s['need_from_author']}")
        if used_ids:
            st.caption("使用した勝ち型ID：" + ", ".join(map(str,used_ids)))


with tab4:
    st.subheader("4. 記事を自動生成")
    st.caption("保存済みの企画と勝ち型を使って、第1稿→自己レビュー→第2稿まで自動生成します。")

    plans = list_plans()
    if not plans:
        st.info("先に「企画」タブで記事企画を保存してください。")
    else:
        plan_labels = {f"#{p['id']} {p['title']}": p for p in plans}
        selected_label = st.selectbox("使う記事企画", list(plan_labels.keys()), key="writer_plan")
        selected_plan_row = plan_labels[selected_label]

        try:
            selected_outline = json.loads(selected_plan_row["outline_json"])
        except Exception:
            selected_outline = []

        selected_plan = {
            "theme": selected_plan_row["theme"],
            "title": selected_plan_row["title"],
            "core_message": selected_plan_row["core_message"],
            "outline": selected_outline,
        }

        st.markdown(f"### {selected_plan['title']}")
        st.caption(selected_plan["core_message"])

        st.markdown("#### あなたの実体験・主張")
        st.caption("ここを具体的に入れるほど、一般論ではない記事になります。空欄でも生成できます。")

        experience_1 = st.text_area(
            "実際に見た失敗・違和感",
            height=100,
            placeholder="例：課題管理表は更新されていたが、次アクションと意思決定者が曖昧で期限超過が続いた。"
        )
        experience_2 = st.text_area(
            "自分が最重要だと思う原則・判断基準",
            height=100,
            placeholder="例：課題は件数ではなく、意思決定が止まっているかで見る。"
        )
        experience_3 = st.text_area(
            "改善前→改善後が分かる具体例",
            height=120,
            placeholder="Before / 何を判断したか / Action / After"
        )
        experience_4 = st.text_area(
            "普段使っている確認手順・チェック項目",
            height=100
        )

        c1,c2 = st.columns(2)
        target_chars = c1.selectbox(
            "目標文字数",
            [3000,4000,5000,6000],
            index=1
        )
        paid_type = c2.selectbox(
            "公開形式",
            ["全編無料","前半無料・後半有料"],
            index=1
        )

        if paid_type == "前半無料・後半有料":
            paid_boundary = st.text_input(
                "有料に切り替える位置",
                value="原因・問題提起までは無料。具体的な判断基準・実務手順から有料。"
            )
        else:
            paid_boundary = "全編無料"

        market_patterns = st.session_state.get("market_patterns", [])

        if st.button("第1稿→第2稿まで自動生成", type="primary"):
            experiences = {
                "失敗・違和感": experience_1,
                "最重要原則・判断基準": experience_2,
                "改善前後の具体例": experience_3,
                "確認手順・チェック項目": experience_4,
            }

            try:
                with st.spinner("第1稿を生成しています"):
                    first_pass = generate_first_pass(
                        selected_plan, experiences, market_patterns,
                        int(target_chars), paid_boundary
                    )

                with st.spinner("全文を読み直して第2稿に修正しています"):
                    final_pass = revise_second_pass(
                        selected_plan, first_pass, market_patterns,
                        int(target_chars)
                    )

                article_id = save_generated_article(
                    selected_plan_row["id"],
                    first_pass,
                    final_pass,
                    experiences,
                    market_patterns[:5],
                    int(target_chars),
                    paid_boundary
                )

                st.session_state["generated_article"] = {
                    "id": article_id,
                    "first_pass": first_pass,
                    "final_pass": final_pass,
                    "title": selected_plan["title"],
                }
                st.success(f"記事 #{article_id} を生成・保存しました。")

            except Exception as e:
                st.error("記事生成に失敗しました。APIキー・API残高・モデル設定を確認してください。")
                st.caption(str(e))

        article = st.session_state.get("generated_article")
        if article:
            st.markdown("### 完成稿")
            st.markdown(article["final_pass"])

            st.download_button(
                "Markdownで保存",
                article["final_pass"],
                file_name=f"note_article_{article['id']}.md",
                mime="text/markdown"
            )

            with st.expander("第1稿を見る"):
                st.markdown(article["first_pass"])

    generated = list_generated_articles(10)
    if generated:
        st.markdown("### 最近生成した記事")
        for g in generated:
            with st.expander(f"#{g['id']} {g['title']}"):
                st.markdown(g["final_pass"])


with tab5:
    st.subheader("5. 公開後の結果")
    plans=list_plans()
    if plans:
        labels={f"#{p['id']} {p['title']}":p["id"] for p in plans}
        sel=st.selectbox("記事企画",list(labels.keys()))
        url=st.text_input("公開URL")
        c1,c2=st.columns(2)
        likes=c1.number_input("スキ数",min_value=0,step=1)
        sales=c2.number_input("販売数",min_value=0,step=1)
        revenue=st.number_input("売上（円）",min_value=0,step=100)
        if st.button("実績を記録",type="primary"):
            record_result(labels[sel],url,int(likes),int(sales),int(revenue))
            st.success("記録しました。")
    else:
        st.info("企画がまだありません。")

    perf=performance_by_pattern()
    if perf:
        st.markdown("### 自分の記事で効いた型")
        for x in perf[:15]:
            st.write(
                f"**{x['pattern_name']}** — "
                f"平均{x['avg_likes']}スキ / 販売{x['total_sales']} / "
                f"売上¥{x['total_revenue_yen']:,} / 使用{x['uses']}回"
            )

with tab6:
    st.subheader("6. 設定・バックアップ")
    st.markdown("### AI記事生成")
    if os.getenv("OPENAI_API_KEY"):
        st.success(f"OpenAI API：設定済み / モデル：{os.getenv('OPENAI_MODEL','gpt-5-mini')}")
    else:
        st.warning("OpenAI APIキーが未設定です。記事自動生成を使うにはStreamlit Secretsへ設定してください。")

    st.info("分析結果や実績は、定期的にバックアップしておくと安心です。")
    backup=json.dumps(export_all(),ensure_ascii=False,indent=2)
    st.download_button(
        "バックアップJSONを保存",
        backup,
        file_name="note_market_planner_backup.json",
        mime="application/json"
    )
    st.markdown("### プライバシー")
    st.write("・他者記事の本文\n・長文引用\n・有料部分の本文")
