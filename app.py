import json
import os

from dotenv import load_dotenv
load_dotenv()

import streamlit as st

from collector import collect
from analyzer import analyze, keyword_candidates
from planner import pattern_rank, theme_ideas, build_plan
from db import (
    save_patterns, get_patterns, save_plan, list_plans, record_result,
    performance_by_pattern, export_all
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
st.caption("市場分析 → 勝ちパターン → テーマ → 記事の土台。iPhone / API追加課金なし版")

for k,v in {
    "last_result":None,
    "analysis_rows":[],
    "selected_tag":"",
    "theme_candidates":[]
}.items():
    if k not in st.session_state:
        st.session_state[k]=v

tab1,tab2,tab3,tab4,tab5 = st.tabs(["市場分析","勝ち型","企画","実績","データ"])

with tab1:
    st.subheader("1. 市場を分析する")
    tag = st.text_input("調べるnoteタグ", value="プロジェクトマネジメント")
    c1,c2 = st.columns(2)
    days = c1.selectbox("期間", [7,14,30], index=2)
    max_articles = c2.selectbox("候補数上限", [20,40,60,80,100], index=2)
    st.info("直近記事を取得し、スキ中央値以上かつ30スキ以上だけを詳細分析します。")
    if st.button("分析を開始", type="primary"):
        try:
            with st.spinner("note市場を集計しています"):
                result = collect(tag, int(days), int(max_articles))
                rows=[]
                for art in result["qualified"]:
                    x=analyze(art["title"],art["body"])
                    rows.append({
                        "url":art["url"],"title":art["title"],"likes":art["likes"],
                        **x
                    })
                    if x["total_score"]>=60 and x["patterns"]:
                        save_patterns(
                            art["url"],tag,x["total_score"],
                            x["scores"],x["patterns"],x["signals"]
                        )
                    art["body"]=None
                result["qualified"]=[
                    {k:v for k,v in a.items() if k!="body"} for a in result["qualified"]
                ]
                st.session_state.last_result=result
                st.session_state.analysis_rows=rows
                st.session_state.selected_tag=tag
        except Exception as e:
            st.error("収集に失敗しました。note側の画面構造変更や一時的なアクセス制限の可能性があります。")
            st.exception(e)

    r=st.session_state.last_result
    if r:
        c1,c2,c3 = st.columns(3)
        c1.metric("取得",r["found"])
        c2.metric("中央値",int(r["median_likes"]))
        c3.metric("分析対象",len(r["qualified"]))
        st.caption(f"採用スキ閾値：{int(r['threshold'])}")
        st.caption(
            f"URL検出：{r.get('discovered_urls', 0)} / "
            f"スキ取得：{r.get('likes_count', 0)} / "
            f"取得エラー：{r.get('fetch_errors', 0)} / "
            f"6時間制限スキップ：{r.get('skipped_cooldown', 0)}"
        )

        rows=st.session_state.analysis_rows
        if rows:
            st.markdown("### 高評価記事")
            for x in sorted(rows,key=lambda z:(z["total_score"],z["likes"] or 0),reverse=True):
                with st.expander(f"{x['total_score']}点｜{x['likes']}スキ｜{x['title'][:45]}"):
                    st.write(x["scores"])
                    st.caption("抽象化した型："+" / ".join(p["pattern_name"] for p in x["patterns"]) if x["patterns"] else "型抽出なし")
                    st.caption(x["url"])
        else:
            st.warning("条件を満たす記事を取得できませんでした。上の「URL検出」「スキ取得」「取得エラー」を確認してください。")

with tab2:
    st.subheader("2. 勝ちパターン")
    ptag=st.text_input("タグで絞る",value=st.session_state.selected_tag,key="pattern_filter")
    pats=get_patterns(ptag or None,200)
    if pats:
        ranked=pattern_rank(pats)
        st.markdown("### よく出る型")
        for name,count in ranked[:8]:
            st.write(f"**{name}** — {count}回")
        st.markdown("### 保存された抽象知見")
        shown=set()
        for p in pats:
            key=(p["pattern_name"],p["abstract_knowledge"])
            if key in shown: continue
            shown.add(key)
            with st.expander(f"{p['pattern_name']}｜元記事 {p['total_score']}点"):
                st.write(p["abstract_knowledge"])
                st.caption("元本文は保存していません。")
    else:
        st.info("まだ勝ちパターンがありません。「市場分析」を実行してください。")

with tab3:
    st.subheader("3. 記事企画を作る")
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
    pattern_names=[p["pattern_name"] for p in patterns]
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
    st.subheader("4. 公開後の結果")
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

with tab5:
    st.subheader("5. データ管理")
    st.warning("無料ホスティングではローカルDBが消える場合があります。定期的なバックアップを推奨します。")
    backup=json.dumps(export_all(),ensure_ascii=False,indent=2)
    st.download_button(
        "バックアップJSONを保存",
        backup,
        file_name="note_market_planner_backup.json",
        mime="application/json"
    )
    st.markdown("### このツールが保存しないもの")
    st.write("・他者記事の本文\n・長文引用\n・有料部分の本文")
