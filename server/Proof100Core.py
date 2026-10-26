import sqlite3, secrets, hashlib, subprocess, datetime, json
from decimal import Decimal

CLI = ["/root/bitcoinz/src/bitcoinz-cli", "-datadir=/root/.bitcoinz-issuing"]
DB = "/root/proof100/Proof100.db"
PACK_PRICE_ZAT = 50000000000000   # 500,000 BTCZ per pack (set 26 Oct 2026)
PROOFS_PER_PACK = 100
MINCONF = 2

def db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS accounts(
        id INTEGER PRIMARY KEY,
        key_hash TEXT UNIQUE NOT NULL,
        deposit_address TEXT UNIQUE NOT NULL,
        proofs_left INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL)""")
    for col in ["received_zat INTEGER NOT NULL DEFAULT 0",
                "packs_credited INTEGER NOT NULL DEFAULT 0"]:
        try:
            con.execute("ALTER TABLE accounts ADD COLUMN " + col)
        except sqlite3.OperationalError:
            pass
    return con

def cli(*args):
    r = subprocess.run(CLI + list(args), capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout.strip()

def hash_key(key):
    return hashlib.sha256(key.encode()).hexdigest()

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

def create_account():
    key = "p100_" + secrets.token_urlsafe(32)
    address = cli("z_getnewaddress")
    con = db()
    with con:
        con.execute("INSERT INTO accounts(key_hash, deposit_address, created_at) VALUES (?,?,?)",
                    (hash_key(key), address, now()))
    con.close()
    return key, address

def check_payments():
    con = db()
    rows = con.execute("SELECT id, deposit_address, received_zat, packs_credited FROM accounts").fetchall()
    for acc_id, addr, received, credited in rows:
        notes = json.loads(cli("z_listreceivedbyaddress", addr, str(MINCONF)), parse_float=Decimal)
        total = sum(int(Decimal(str(n["amount"])) * 100000000) for n in notes)
        packs = total // PACK_PRICE_ZAT
        new_packs = packs - credited
        if total != received or new_packs > 0:
            with con:
                con.execute("UPDATE accounts SET received_zat=?, packs_credited=?, proofs_left=proofs_left+? WHERE id=?",
                            (total, packs, max(new_packs, 0) * PROOFS_PER_PACK, acc_id))
            print(now(), "account", acc_id, "received", total, "zat, new packs", max(new_packs, 0))
    con.close()

import time
CONFIG = json.load(open("/root/proof100/Proof100Config.json"))
PROOF_AMOUNT = 0.0001
PROOF_FEE = "0.00001"

def wait_for_txid(opid, timeout=180):
    waited = 0
    while waited < timeout:
        st = json.loads(cli("z_getoperationstatus", json.dumps([opid])))
        if st and st[0]["status"] == "success":
            return st[0]["result"]["txid"]
        if st and st[0]["status"] == "failed":
            raise RuntimeError(st[0].get("error", {}).get("message", "send failed"))
        time.sleep(2)
        waited += 2
    raise RuntimeError("timeout waiting for transaction")

def make_proof(key, fingerprint):
    fp = fingerprint.strip().lower()
    if len(fp) != 64 or any(c not in "0123456789abcdef" for c in fp):
        return {"ok": False, "error": "fingerprint must be a 64-character SHA-256 hex string"}
    kh = hash_key(key)
    con = db()
    with con:
        cur = con.execute("UPDATE accounts SET proofs_left = proofs_left - 1 WHERE key_hash=? AND proofs_left > 0", (kh,))
    if cur.rowcount != 1:
        con.close()
        return {"ok": False, "error": "invalid key or no proofs left"}
    memo = ("PROOF100 sha256:" + fp).encode().hex()
    try:
        dest = cli("z_getnewaddress")
        opid = cli("z_sendmany", CONFIG["sender"],
                   json.dumps([{"address": dest, "amount": PROOF_AMOUNT, "memo": memo}]),
                   "1", PROOF_FEE)
        txid = wait_for_txid(opid)
    except Exception as e:
        with con:
            con.execute("UPDATE accounts SET proofs_left = proofs_left + 1 WHERE key_hash=?", (kh,))
        con.close()
        return {"ok": False, "error": "send failed, proof not used: " + str(e)[:200]}
    left = con.execute("SELECT proofs_left FROM accounts WHERE key_hash=?", (kh,)).fetchone()[0]
    con.close()
    try:
        vk = cli("z_exportviewingkey", dest)
    except Exception:
        vk = None
    return {"ok": True, "txid": txid, "explorer": "https://explorer.btcz.rocks/tx/" + txid,
            "viewing_key": vk,
            "note": "Keep the viewing_key. With the txid, it reveals this one proof and nothing else.",
            "proofs_left": left}
