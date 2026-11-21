# Free stamp_hash: one-call, no-key timestamps for AI agents (decided 21 Nov 2026).
# The operator pays. Caps (Eric, 21 Nov): 100 free stamps in total,
# max 3 per caller per UTC day, max 30 per UTC day overall.
#
# Privacy design:
# - The caller is identified only by a salted hash of its IP (salt in FreeSalt.txt,
#   chmod 600). It is kept in free_callers, with a per-day counter, and never
#   linked to a stamp.
# - free_stamps keeps txid + the one-time address, so check_stamp can read the
#   memo back. It does not store the fingerprint or who made the stamp.
import os, json, secrets, hashlib, sqlite3, datetime
import Proof100Core as core

FREE_TOTAL = 100
FREE_PER_CALLER_DAY = 3
FREE_PER_DAY = 30
FREE_FEE_NOTE = ("Free stamp paid by the operator (Z-TEXT LLC). No key, no wallet, no coin needed. "
                 "Free stamps are limited: %d in total, %d per caller per day, %d per day overall."
                 % (FREE_TOTAL, FREE_PER_CALLER_DAY, FREE_PER_DAY))


def _salt():
    path = os.path.join(core.HOME, "FreeSalt.txt")
    if not os.path.exists(path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    return open(path).read().strip()


def caller_id(ip):
    return hashlib.sha256((_salt() + "|" + (ip or "unknown")).encode()).hexdigest()


def _db():
    con = sqlite3.connect(core.DB, timeout=30, isolation_level=None)
    con.execute("""CREATE TABLE IF NOT EXISTS free_stamps(
        id INTEGER PRIMARY KEY,
        txid TEXT UNIQUE,
        address TEXT,
        day TEXT NOT NULL,
        created_at TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS free_callers(
        caller TEXT NOT NULL,
        day TEXT NOT NULL,
        used INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (caller, day))""")
    return con


def _clean_fp(fp):
    fp = str(fp or "").strip().lower()
    if len(fp) != 64 or any(c not in "0123456789abcdef" for c in fp):
        return None
    return fp


def _reserve(caller):
    """Check the 3 caps and reserve one slot atomically. Returns (row_id, None) or (None, error)."""
    stamp = core.now()
    day = stamp[:10]
    con = _db()
    try:
        con.execute("BEGIN IMMEDIATE")
        total = con.execute("SELECT COUNT(*) FROM free_stamps").fetchone()[0]
        if total >= FREE_TOTAL:
            con.execute("ROLLBACK")
            return None, ("All %d free stamps are used. Paid proofs: create an account at "
                          "https://proof.zketernity.app/v1/account (3 free trial proofs while the trial runs)." % FREE_TOTAL)
        today = con.execute("SELECT COUNT(*) FROM free_stamps WHERE day=?", (day,)).fetchone()[0]
        if today >= FREE_PER_DAY:
            con.execute("ROLLBACK")
            return None, "Today's %d free stamps are used. Try again after 00:00 UTC." % FREE_PER_DAY
        row = con.execute("SELECT used FROM free_callers WHERE caller=? AND day=?", (caller, day)).fetchone()
        if row and row[0] >= FREE_PER_CALLER_DAY:
            con.execute("ROLLBACK")
            return None, "You used your %d free stamps for today. Try again after 00:00 UTC." % FREE_PER_CALLER_DAY
        con.execute("INSERT OR IGNORE INTO free_callers(caller, day, used) VALUES (?,?,0)", (caller, day))
        con.execute("UPDATE free_callers SET used=used+1 WHERE caller=? AND day=?", (caller, day))
        cur = con.execute("INSERT INTO free_stamps(day, created_at) VALUES (?,?)", (day, stamp))
        con.execute("COMMIT")
        return cur.lastrowid, None
    finally:
        con.close()


def _release(row_id, caller):
    con = _db()
    try:
        con.execute("BEGIN IMMEDIATE")
        day = con.execute("SELECT day FROM free_stamps WHERE id=?", (row_id,)).fetchone()
        con.execute("DELETE FROM free_stamps WHERE id=?", (row_id,))
        if day:
            con.execute("UPDATE free_callers SET used=used-1 WHERE caller=? AND day=? AND used>0", (caller, day[0]))
        con.execute("COMMIT")
    finally:
        con.close()


def _left(caller):
    day = core.now()[:10]
    con = _db()
    total = con.execute("SELECT COUNT(*) FROM free_stamps").fetchone()[0]
    row = con.execute("SELECT used FROM free_callers WHERE caller=? AND day=?", (caller, day)).fetchone()
    con.close()
    return max(FREE_TOTAL - total, 0), max(FREE_PER_CALLER_DAY - (row[0] if row else 0), 0)


def stamp_hash(sha256, ip):
    fp = _clean_fp(sha256)
    if not fp:
        return {"ok": False, "error": "sha256 must be a 64-character SHA-256 hex string"}
    caller = caller_id(ip)
    row_id, error = _reserve(caller)
    if error:
        return {"ok": False, "error": error}
    memo = ("PROOF100 sha256:" + fp).encode().hex()
    try:
        dest = core.cli("z_getnewaddress")
        opid = core.cli("z_sendmany", core.CONFIG["sender"],
                        json.dumps([{"address": dest, "amount": core.PROOF_AMOUNT, "memo": memo}]),
                        "1", core.PROOF_FEE)
        txid = core.wait_for_txid(opid)
    except Exception as e:
        _release(row_id, caller)
        return {"ok": False, "error": "send failed, nothing was used: " + str(e)[:200]}
    con = _db()
    con.execute("UPDATE free_stamps SET txid=?, address=? WHERE id=?", (txid, dest, row_id))
    con.close()
    try:
        vk = core.cli("z_exportviewingkey", dest)
    except Exception:
        vk = None
    total_left, today_left = _left(caller)
    return {"ok": True, "sha256": fp, "txid": txid,
            "explorer": "https://explorer.btcz.rocks/tx/" + txid,
            "viewing_key": vk,
            "status": "sent; dated when the next BitcoinZ block includes it (about 2.5 minutes on average)",
            "check": "Call check_stamp with this txid (and the sha256) to see the block date and a MATCH. "
                     "For a check that does not trust us, use ZCheck with the txid and viewing_key: "
                     "https://github.com/ZKStamp/Proof100/blob/main/zcheck/ZCheck.py",
            "note": "Keep the txid and viewing_key. Together they reveal this one stamp and nothing else.",
            "free_left_today_for_you": today_left, "free_left_total": total_left,
            "about": FREE_FEE_NOTE}


def check_stamp(txid, sha256=None):
    txid = str(txid or "").strip().lower()
    if len(txid) != 64 or any(c not in "0123456789abcdef" for c in txid):
        return {"ok": False, "error": "txid must be 64 hex characters"}
    con = _db()
    row = con.execute("SELECT address FROM free_stamps WHERE txid=?", (txid,)).fetchone()
    con.close()
    if not row:
        return {"ok": False, "error": "unknown txid: check_stamp only knows free stamps. "
                                      "For paid proofs, use ZCheck with the txid and viewing key."}
    notes = json.loads(core.cli("z_listreceivedbyaddress", row[0], "0"))
    memo_fp = None
    for n in notes:
        if n.get("txid") == txid:
            raw = bytes.fromhex(n.get("memo", "")).rstrip(b"\x00").decode("utf-8", "replace")
            if raw.startswith("PROOF100 sha256:"):
                memo_fp = raw[len("PROOF100 sha256:"):].strip()
    if not memo_fp:
        return {"ok": False, "error": "stamp not readable yet, try again in a minute"}
    tx = json.loads(core.cli("gettransaction", txid))
    conf = int(tx.get("confirmations", 0))
    out = {"ok": True, "txid": txid, "sha256": memo_fp, "confirmations": conf}
    if conf > 0 and tx.get("blockhash"):
        hdr = json.loads(core.cli("getblockheader", tx["blockhash"]))
        out["block"] = hdr.get("height")
        out["date_utc"] = datetime.datetime.fromtimestamp(int(hdr.get("time", tx.get("blocktime", 0))),
                                                          datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        out["status"] = "dated in block %s" % out["block"]
    else:
        out["status"] = "sent, waiting for the next block (about 2.5 minutes on average)"
    if sha256 is not None and str(sha256).strip():
        fp = _clean_fp(sha256)
        out["result"] = "MATCH" if fp == memo_fp else "NO MATCH"
    out["trust_note"] = ("This answer comes from our server. To check without trusting us, "
                         "run ZCheck with the txid and the viewing key on any BitcoinZ node.")
    return out


def report():
    con = _db()
    total = con.execute("SELECT COUNT(*) FROM free_stamps WHERE txid IS NOT NULL").fetchone()[0]
    callers = con.execute("SELECT COUNT(DISTINCT caller) FROM free_callers WHERE used>0").fetchone()[0]
    days = con.execute("SELECT day, COUNT(*) FROM free_stamps WHERE txid IS NOT NULL "
                       "GROUP BY day ORDER BY day DESC LIMIT 14").fetchall()
    con.close()
    return total, callers, days
