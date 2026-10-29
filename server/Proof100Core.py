import sqlite3, secrets, hashlib, subprocess, datetime, json, os
from decimal import Decimal

HOME = os.environ.get("P100_HOME", "/root/proof100")
CLI = ["/root/bitcoinz/src/bitcoinz-cli", "-datadir=/root/.bitcoinz-issuing"]
DB = os.path.join(HOME, "Proof100.db")
PACK_PRICE_ZAT = 50000000000000   # 500,000 BTCZ per pack (set 26 Oct 2026)
PROOFS_PER_PACK = 100
MINCONF = 2
# Free trial (decided 27 Oct 2026): 3 free proofs for new accounts,
# max 13 trial accounts per UTC day, until 27 Nov 2026 (then review).
TRIAL_PROOFS = 3
TRIAL_PER_DAY = 13
TRIAL_END = "2026-11-27"
# t-deposit (decided 29 Oct 2026): every account also gets a transparent
# address, for buyers paying from exchanges or t-only wallets (Coinomi).
# Payments to both addresses add up. Coins received on the t-address are
# moved to the shielded side automatically; the 0.0001 network fee of that
# move is paid by the operator (the buyer is credited the full amount).
SWEEP_FEE = Decimal("0.0001")
SWEEP_MIN = Decimal("0.001")         # don't move dust
T_PRIVACY_NOTE = ("Paying from an exchange or Coinomi? Use the t-address. Your payment will be visible on the blockchain, "
                  "but your proofs stay fully shielded. For a fully private payment, use the zs address.")

def db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS accounts(
        id INTEGER PRIMARY KEY,
        key_hash TEXT UNIQUE NOT NULL,
        deposit_address TEXT UNIQUE NOT NULL,
        proofs_left INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL)""")
    for col in ["received_zat INTEGER NOT NULL DEFAULT 0",
                "packs_credited INTEGER NOT NULL DEFAULT 0",
                "trial INTEGER NOT NULL DEFAULT 0",
                "t_address TEXT",
                "t_received_zat INTEGER NOT NULL DEFAULT 0"]:
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

def create_account(trial=False):
    """Create an account. With trial=True, grant TRIAL_PROOFS free proofs
    if the trial is still running and today's cap is not reached.
    Returns (key, address, free_proofs_granted)."""
    key = "p100_" + secrets.token_urlsafe(32)
    address = cli("z_getnewaddress")
    t_address = cli("getnewaddress")
    con = db()
    stamp = now()
    today = stamp[:10]
    free = 0
    with con:
        if trial and today < TRIAL_END:
            used = con.execute("SELECT COUNT(*) FROM accounts WHERE trial=1 AND substr(created_at,1,10)=?",
                               (today,)).fetchone()[0]
            if used < TRIAL_PER_DAY:
                free = TRIAL_PROOFS
        con.execute("INSERT INTO accounts(key_hash, deposit_address, created_at, proofs_left, trial, t_address) VALUES (?,?,?,?,?,?)",
                    (hash_key(key), address, stamp, free, 1 if free else 0, t_address))
    con.close()
    return key, address, free

def t_address_for(acc_id):
    """The account's t-deposit address; accounts made before 29 Oct get one on first use."""
    con = db()
    row = con.execute("SELECT t_address FROM accounts WHERE id=?", (acc_id,)).fetchone()
    if row and row[0]:
        con.close()
        return row[0]
    t = cli("getnewaddress")
    with con:
        con.execute("UPDATE accounts SET t_address=? WHERE id=? AND t_address IS NULL", (t, acc_id))
    t = con.execute("SELECT t_address FROM accounts WHERE id=?", (acc_id,)).fetchone()[0]
    con.close()
    return t


def zat(amount):
    return int(Decimal(str(amount)) * 100000000)


def sweep(t_address):
    """Move the confirmed coins of one t-deposit address to the shielded side,
    in its own transaction (t-addresses are never combined, so they stay unlinked)."""
    dest = CONFIG.get("sweep_to") or CONFIG["sender"]
    bal = Decimal(cli("z_getbalance", t_address, str(MINCONF)))
    if bal < SWEEP_MIN:
        return None
    opid = cli("z_sendmany", t_address, json.dumps([{"address": dest, "amount": float(bal - SWEEP_FEE)}]),
               str(MINCONF), str(SWEEP_FEE))
    return wait_for_txid(opid)


def check_payments():
    con = db()
    rows = con.execute("SELECT id, deposit_address, received_zat, packs_credited, t_address FROM accounts").fetchall()
    for acc_id, addr, received, credited, t_addr in rows:
        notes = json.loads(cli("z_listreceivedbyaddress", addr, str(MINCONF)), parse_float=Decimal)
        z_total = sum(zat(n["amount"]) for n in notes)
        # getreceivedbyaddress counts everything ever received, so moving the
        # coins out (sweep) does not lower the buyer's credit
        t_total = zat(cli("getreceivedbyaddress", t_addr, str(MINCONF))) if t_addr else 0
        total = z_total + t_total
        packs = total // PACK_PRICE_ZAT
        new_packs = packs - credited
        if total != received or new_packs > 0:
            with con:
                con.execute("UPDATE accounts SET received_zat=?, t_received_zat=?, packs_credited=?, proofs_left=proofs_left+? WHERE id=?",
                            (total, t_total, packs, max(new_packs, 0) * PROOFS_PER_PACK, acc_id))
            print(now(), "account", acc_id, "received", total, "zat (t part", t_total, "), new packs", max(new_packs, 0))
        if t_addr and t_total:
            try:
                tx = sweep(t_addr)
                if tx:
                    print(now(), "account", acc_id, "t-deposit moved to shielded side in", tx)
            except Exception as e:
                print(now(), "account", acc_id, "sweep failed, will retry:", str(e)[:200])
    con.close()

import time
CONFIG = json.load(open(os.path.join(HOME, "Proof100Config.json")))
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
