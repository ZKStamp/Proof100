import json, hashlib
from flask import Flask, request, jsonify
from Proof100Core import make_proof, create_account, db, hash_key, t_address_for, T_PRIVACY_NOTE

app = Flask(__name__)

FUNDING_TIP = "Paying from an exchange or a t-only wallet (like Coinomi)? Send to your t_deposit_address directly. For a fully private payment, send your BTCZ to the free Z-TEXT wallet first (https://z-text.com/downloads): it shields them automatically. Then pay from Z-TEXT to your zs deposit_address."

def get_key():
    h = (request.headers.get("Authorization", "") or request.headers.get("X-API-Key", "")).strip()
    while h.lower().startswith("bearer"):
        h = h[6:].strip()
    return h

def balance_dict(key):
    con = db()
    row = con.execute("SELECT proofs_left, deposit_address, id FROM accounts WHERE key_hash=?",
                      (hash_key(key),)).fetchone()
    con.close()
    if not row:
        return {"ok": False, "error": "invalid key"}
    try:
        t_addr = t_address_for(row[2])
    except Exception:
        t_addr = None
    out = {"ok": True, "proofs_left": row[0], "deposit_address": row[1]}
    if t_addr:
        out.update({"t_deposit_address": t_addr, "t_deposit_note": T_PRIVACY_NOTE})
    out["funding_tip"] = FUNDING_TIP
    return out

@app.route("/v1/proof", methods=["POST"])
def proof():
    data = request.get_json(silent=True) or {}
    r = make_proof(get_key(), str(data.get("fingerprint", "")))
    return jsonify(r), (200 if r["ok"] else 400)

@app.route("/v1/balance", methods=["GET"])
def balance():
    r = balance_dict(get_key())
    return jsonify(r), (200 if r["ok"] else 401)

@app.route("/v1/account", methods=["POST"])
def account():
    key, addr, free = create_account(trial=True)
    note = "Save your key now: it is shown only once."
    if free:
        note += " Free trial: %d proofs credited, no payment needed." % free
    b = balance_dict(key)
    return jsonify({"ok": True, "key": key, "deposit_address": addr,
                    "t_deposit_address": b.get("t_deposit_address"), "t_deposit_note": T_PRIVACY_NOTE,
                    "payment": "500,000 BTCZ to either address (or both together) = 100 proofs, credited after 2 confirmations. One proof costs 5,000 BTCZ: a fraction of the price of a €2 coffee.",
                    "free_proofs": free, "note": note, "funding_tip": FUNDING_TIP})

TOOLS = [
    {"name": "timestamp_fingerprint",
     "description": "Create a private, dated proof that a file or data existed, without sending the data. Use this when you already have the SHA-256 fingerprint (hash) of a file; for a short text, use timestamp_text instead. Compute the hash locally over the exact bytes (for example: sha256sum MyFile.pdf) and pass the 64-character hex string. The fingerprint is written into the encrypted memo of a shielded (zk-SNARK) BitcoinZ transaction, sent to a new address made for this proof only; the block timestamp dates it. Takes about 10 to 60 seconds and uses 1 proof from the account (requires the account key in the Authorization header). Returns ok, txid, viewing_key, explorer link and proofs_left. Tell the user to keep the txid and viewing_key: together they let anyone verify this one proof with ZCheck, and reveal nothing else. On error (invalid fingerprint, invalid key, no proofs left, send failed) no proof is used.",
     "inputSchema": {"type": "object",
                     "properties": {"fingerprint": {"type": "string",
                                                    "description": "SHA-256 hash of the file, as 64 hexadecimal characters (case-insensitive), e.g. 968c796b7f8c9259ee92d7168d882df2f347d9711a51da90182c98d69139cdb7",
                                                    "pattern": "^[0-9a-fA-F]{64}$"}},
                     "required": ["fingerprint"]}},
    {"name": "timestamp_text",
     "description": "Compute the SHA-256 fingerprint of a short text on the Proof-100 server (the text is not stored), then write that fingerprint privately on the BitcoinZ blockchain. Returns the fingerprint, the transaction ID and a viewing key for this one proof. Keep the viewing key: with the txid it reveals this proof only. Uses 1 proof.",
     "inputSchema": {"type": "object",
                     "properties": {"text": {"type": "string", "description": "The exact text to timestamp"}},
                     "required": ["text"]}},
    {"name": "check_balance",
     "description": "Show how many Proof-100 proofs are left and the two BTCZ deposit addresses for buying more: deposit_address (shielded zs, fully private) and t_deposit_address (transparent, for exchanges and t-only wallets like Coinomi; the payment is visible on the blockchain, the proofs stay shielded). 500,000 BTCZ to either (or both together) = 100 proofs after 2 confirmations.",
     "inputSchema": {"type": "object", "properties": {}}},
]

@app.route("/mcp", methods=["POST"])
def mcp():
    msg = request.get_json(silent=True)
    if not isinstance(msg, dict):
        return jsonify({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}), 400
    mid, method = msg.get("id"), msg.get("method", "")
    if mid is None:
        return "", 202
    def ok(result):
        return jsonify({"jsonrpc": "2.0", "id": mid, "result": result})
    def err(code, text):
        return jsonify({"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}})
    if method == "initialize":
        pv = (msg.get("params") or {}).get("protocolVersion", "2025-03-26")
        return ok({"protocolVersion": pv, "capabilities": {"tools": {}},
                   "serverInfo": {"name": "Proof-100", "version": "0.1"}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        p = msg.get("params") or {}
        name, args, key = p.get("name"), p.get("arguments") or {}, get_key()
        if name == "timestamp_fingerprint":
            r = make_proof(key, str(args.get("fingerprint", "")))
        elif name == "timestamp_text":
            fp = hashlib.sha256(str(args.get("text", "")).encode("utf-8")).hexdigest()
            r = make_proof(key, fp)
            r["fingerprint"] = fp
        elif name == "check_balance":
            r = balance_dict(key)
        else:
            return err(-32602, "Unknown tool")
        return ok({"content": [{"type": "text", "text": json.dumps(r)}], "isError": not r.get("ok", False)})
    return err(-32601, "Method not found")

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5100)
