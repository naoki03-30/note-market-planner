import os, tempfile, importlib

tmp=tempfile.NamedTemporaryFile(suffix=".db",delete=False)
os.environ["NOTE_DB_PATH"]=tmp.name

import db
importlib.reload(db)
from analyzer import analyze
from planner import build_plan

x=analyze(
    "課題管理をしているのに炎上する3つの理由",
    """現場では課題管理表を更新していても問題が残ります。
1. 次アクションがない
2. 意思決定者が不明
私は3つのプロジェクトでこの問題を経験しました。
まず影響度を確認します。次に担当者と期限を決めます。
最後にチェックリストで確認します。"""
)
assert set(x["scores"].keys()) == set(["フック","課題設定","具体性","信頼性","構成","読みやすさ","実行可能性","独自性"])
ids=db.save_patterns("https://note.com/x/n/nx","PM",65,x["scores"],[
    {"pattern_name":"現場課題起点","abstract_knowledge":"現場の問題から始める"}
],x["signals"])
assert ids
p=build_plan("PM","若手PM","PMの失敗","若手PMがやりがちな失敗","実体験あり",["現場課題起点"])
pid=db.save_plan("PM","若手PM",p,ids)
db.record_result(pid,"https://note.com/me/n/nx",50,3,2940)
perf=db.performance_by_pattern()
assert perf and perf[0]["total_revenue_yen"]==2940
print("smoke test passed")
