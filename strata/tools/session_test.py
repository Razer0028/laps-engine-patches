"""実機の確かめ: 保存 → （エンジンの起動し直し）→ 復元 → 続きの読み込みを比べる。 使い方: session_test.py pre|post <名前> [規則の数]"""
import json, sys, time, urllib.request, urllib.error
import os
B = os.environ.get("STRATA_URL", "http://127.0.0.1:8741")
mode, name = sys.argv[1], sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 2400
sysmsg = f"You are a helper. Session {name}. " + " ".join(f"Rule {i}: keep answers short and factual, item {i*7919%1000}." for i in range(n))
Q1, Q2 = "What is item number for Rule 7? Answer with the number only.", "And for Rule 11? Answer with the number only."
def chat(messages):
    body = {"model": "default", "messages": messages, "stream": True, "max_tokens": 80, "cache_prompt": True, "temperature": 0,
            "stream_options": {"include_usage": True}, "reasoning_budget_tokens": 64}
    t0 = time.time()
    r = urllib.request.urlopen(urllib.request.Request(B + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=1800)
    tm, text = {}, ""
    for line in r:
        line = line.decode().strip()
        if line.startswith("data: ") and line != "data: [DONE]":
            o = json.loads(line[6:])
            if isinstance(o.get("timings"), dict): tm = o["timings"]
            for c in o.get("choices") or []: text += (c.get("delta") or {}).get("content") or ""
    return {"read": tm.get("prompt_n"), "cache": tm.get("cache_n"), "read_ms": round(tm.get("prompt_ms") or 0), "wall": round(time.time() - t0, 1), "text": text.strip()}
def slot(action):
    t0 = time.time()
    try:
        r = urllib.request.urlopen(urllib.request.Request(B + f"/slots/0?action={action}", json.dumps({"filename": name + ".bin"}).encode(), {"Content-Type": "application/json"}), timeout=1800)
        return {"http": r.status, "wall": round(time.time() - t0, 2), **json.loads(r.read())}
    except urllib.error.HTTPError as e:
        return {"http": e.code, "wall": round(time.time() - t0, 2), "body": e.read().decode()[:400]}
S = f"state-{name}.json"
if mode == "pre":
    a = chat([{"role": "system", "content": sysmsg}, {"role": "user", "content": Q1}]); print("1 回目      ", a, flush=True)
    sv = slot("save"); print("保存        ", sv, flush=True)
    b = chat([{"role": "system", "content": sysmsg}, {"role": "user", "content": Q1}, {"role": "assistant", "content": a["text"]}, {"role": "user", "content": Q2}]); print("続き（基準）", b, flush=True)
    json.dump({"a": a, "b": b, "save": sv}, open(S, "w"), ensure_ascii=False)
else:
    st = json.load(open(S))
    rs = {"http": 200} if mode == "cont" else slot("restore"); print("復元        ", rs, flush=True)
    if rs["http"] == 200:
        b = chat([{"role": "system", "content": sysmsg}, {"role": "user", "content": Q1}, {"role": "assistant", "content": st["a"]["text"]}, {"role": "user", "content": Q2}]); print("続き（復元後）", b, flush=True)
        print("基準        ", st["b"]); print("答えが同じ  ", b["text"] == st["b"]["text"])
