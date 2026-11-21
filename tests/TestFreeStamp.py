# Run: python3 tests/TestFreeStamp.py server   (fake BitcoinZ node, no real coins)
import os, sys, json, tempfile, hashlib
home = tempfile.mkdtemp(); os.environ["P100_HOME"] = home
json.dump({"sender": "zsSENDER"}, open(os.path.join(home, "Proof100Config.json"), "w"))
sys.path.insert(0, sys.argv[1])
import Proof100Core as core
chain = {"n": 0, "notes": {}, "tx": {}, "fail": False}
def fake_cli(*a):
    c = a[0]
    if c == "z_getnewaddress":
        chain["n"] += 1; return "zsADDR%d" % chain["n"]
    if c == "z_sendmany":
        if chain["fail"]: raise RuntimeError("insufficient funds")
        out = json.loads(a[2])[0]; txid = hashlib.sha256(str(chain["n"]).encode()+out["address"].encode()).hexdigest()
        chain["notes"].setdefault(out["address"], []).append({"txid": txid, "amount": out["amount"], "memo": out["memo"] + "00"*20})
        chain["tx"][txid] = {"confirmations": 1, "blockhash": "bh1"}; chain["last"] = txid
        return "opid-" + txid
    if c == "z_getoperationstatus":
        return json.dumps([{"status": "success", "result": {"txid": json.loads(a[1])[0][5:]}}])
    if c == "z_exportviewingkey": return "zxviews" + a[1]
    if c == "z_listreceivedbyaddress": return json.dumps(chain["notes"].get(a[1], []))
    if c == "gettransaction": return json.dumps(chain["tx"][a[1]])
    if c == "getblockheader": return json.dumps({"height": 2000000, "time": 1795254149})
    raise RuntimeError("unexpected " + c)
core.cli = fake_cli
core.time.sleep = lambda s: None
import FreeStamp as F
import Proof100Api as api
ok = 0; bad = 0
def check(name, cond):
    global ok, bad
    if cond: ok += 1
    else: bad += 1; print("FAIL", name)
fp = hashlib.sha256(b"agent output").hexdigest()
r = F.stamp_hash(fp, "1.1.1.1"); check("stamp ok", r["ok"] and r["viewing_key"] and r["free_left_today_for_you"] == 2 and r["free_left_total"] == 99)
c = F.check_stamp(r["txid"], fp); check("check match", c["ok"] and c["result"] == "MATCH" and c["block"] == 2000000 and c["sha256"] == fp and "UTC" in c["date_utc"])
c2 = F.check_stamp(r["txid"], "0"*64); check("no match", c2["result"] == "NO MATCH")
c3 = F.check_stamp(r["txid"].upper()); check("check no sha, upper txid", c3["ok"] and "result" not in c3)
check("unknown txid", not F.check_stamp("a"*64)["ok"])
check("bad txid", not F.check_stamp("xyz")["ok"])
check("bad hash", not F.stamp_hash("abc", "1.1.1.1")["ok"])
check("upper hash ok", F.stamp_hash(fp.upper(), "1.1.1.1")["ok"])
F.stamp_hash(fp, "1.1.1.1")
r4 = F.stamp_hash(fp, "1.1.1.1"); check("per caller cap", not r4["ok"] and "3 free" in r4["error"])
check("other caller ok", F.stamp_hash(fp, "2.2.2.2")["ok"])
chain["fail"] = True
r5 = F.stamp_hash(fp, "3.3.3.3"); check("fail refunds", not r5["ok"] and "nothing was used" in r5["error"])
chain["fail"] = False
check("after fail caller still has 3", F.stamp_hash(fp, "3.3.3.3")["free_left_today_for_you"] == 2)
total, callers, days = F.report(); check("report", total == 5 and callers == 3)
for i in range(4, 40): F.stamp_hash(fp, "9.9.%d.1" % i)
total, callers, days = F.report(); check("daily cap 30", total == 30)
r6 = F.stamp_hash(fp, "8.8.8.8"); check("daily msg", "Today" in r6["error"])
# total cap: pretend older days
con = F._db(); con.execute("UPDATE free_stamps SET day='2026-11-01'"); con.close()
for i in range(100):
    con = F._db(); con.execute("UPDATE free_stamps SET day='2026-11-01'"); con.close()
    F.stamp_hash(fp, "7.7.%d.1" % i)
total, callers, days = F.report(); check("total cap 100", total == 100)
check("total msg", "All 100" in F.stamp_hash(fp, "6.6.6.6")["error"])
check("salt private", oct(os.stat(os.path.join(home, "FreeSalt.txt")).st_mode)[-3:] == "600")
con = F._db(); cols = [r[1] for r in con.execute("PRAGMA table_info(free_stamps)")]; con.close()
check("no fingerprint or caller stored with stamp", cols == ["id", "txid", "address", "day", "created_at"])
# API / MCP
cl = api.app.test_client()
tl = cl.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).get_json()
names = [t["name"] for t in tl["result"]["tools"]]; check("tools listed", names[:2] == ["stamp_hash", "check_stamp"] and len(names) == 5)
con = F._db(); con.execute("DELETE FROM free_stamps"); con.execute("DELETE FROM free_callers"); con.close()
res = cl.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "stamp_hash", "arguments": {"sha256": fp}}}, headers={"X-Real-IP": "5.5.5.5"}).get_json()
body = json.loads(res["result"]["content"][0]["text"]); check("mcp stamp no key", body["ok"] and res["result"]["isError"] is False)
res = cl.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "check_stamp", "arguments": {"txid": body["txid"], "sha256": fp}}}).get_json()
check("mcp check", json.loads(res["result"]["content"][0]["text"])["result"] == "MATCH")
rr = cl.post("/v1/free/stamp", json={"sha256": fp}, headers={"X-Real-IP": "5.5.5.6"}); check("rest stamp", rr.status_code == 200)
rc = cl.get("/v1/free/check?txid=%s&sha256=%s" % (rr.get_json()["txid"], fp)); check("rest check", rc.get_json()["result"] == "MATCH")
check("rest bad", cl.post("/v1/free/stamp", json={"sha256": "x"}).status_code == 400)
res = cl.post("/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "timestamp_fingerprint", "arguments": {"fingerprint": fp}}}).get_json()
check("paid tool still needs key", json.loads(res["result"]["content"][0]["text"])["ok"] is False)
print("%d/%d passed" % (ok, ok + bad))
