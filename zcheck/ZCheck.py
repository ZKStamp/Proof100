#!/usr/bin/env python3
"""ZCheck: verify a Proof-100 proof on your own BitcoinZ node.
Stamp it with Z. Before Q.

You need: the transaction ID (txid) and the viewing key you received with the proof,
plus the original file (or its SHA-256 fingerprint), and a synced BitcoinZ node.

Example:
  python3 ZCheck.py --txid <txid> --viewing-key <zxviews...> --file MyFile.pdf
"""
import argparse, datetime, hashlib, json, subprocess, sys

DEFAULT_START = 1862000  # Proof-100 started after this BitcoinZ block
PREFIX = "PROOF100 sha256:"


def run(cli, datadir, *args):
    cmd = [cli] + ([f"-datadir={datadir}"] if datadir else []) + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip())
    return r.stdout.strip()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description="ZCheck: verify a Proof-100 proof on your own BitcoinZ node.")
    p.add_argument("--txid", required=True, help="transaction ID of the proof")
    p.add_argument("--viewing-key", required=True, help="viewing key received with the proof (zxviews...)")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="the original file")
    src.add_argument("--fingerprint", help="or its SHA-256 fingerprint (64 hex characters)")
    p.add_argument("--cli", default="bitcoinz-cli", help="path to bitcoinz-cli")
    p.add_argument("--datadir", default=None, help="BitcoinZ data directory, if not the default")
    p.add_argument("--start-height", type=int, default=DEFAULT_START, help="block to start scanning from")
    a = p.parse_args()

    fp = sha256_file(a.file) if a.file else a.fingerprint.strip().lower()
    print("Fingerprint to check :", fp)

    print("Loading viewing key (first time: scans from block %d, can take a few minutes)..." % a.start_height)
    addr = None
    try:
        res = json.loads(run(a.cli, a.datadir, "z_importviewingkey", a.viewing_key, "yes", str(a.start_height)))
        addr = res.get("address")
    except (RuntimeError, ValueError) as e:
        if "already" not in str(e).lower():
            print("ERROR: could not load the viewing key:", e)
            sys.exit(2)

    try:
        tx = json.loads(run(a.cli, a.datadir, "z_viewtransaction", a.txid))
    except RuntimeError as e:
        print("NOT VALID: this viewing key does not reveal transaction", a.txid, "(" + str(e) + ")")
        sys.exit(1)

    found = None
    for o in tx.get("outputs", []):
        memo = o.get("memoStr", "") or ""
        if memo.startswith(PREFIX) and (addr is None or o.get("address") == addr):
            found = memo[len(PREFIX):].strip().lower()
            break
    if not found:
        print("NOT VALID: no Proof-100 fingerprint for this viewing key in this transaction.")
        sys.exit(1)

    print("Fingerprint on chain :", found)
    info = json.loads(run(a.cli, a.datadir, "gettransaction", a.txid, "true"))
    if not info.get("blockhash"):
        print("WAIT: the transaction is not in a block yet. Try again in a few minutes.")
        sys.exit(3)
    height = json.loads(run(a.cli, a.datadir, "getblockheader", info["blockhash"]))["height"]
    when = datetime.datetime.fromtimestamp(info["blocktime"], datetime.timezone.utc)

    if found == fp:
        print("VALID: this exact fingerprint was written on the BitcoinZ blockchain")
        print("       in block %d, on %s UTC (%d confirmations)." % (height, when.strftime("%d %B %Y, %H:%M"), info.get("confirmations", 0)))
        sys.exit(0)
    print("NOT VALID: the proof exists (block %d, %s UTC) but holds a different fingerprint." % (height, when.strftime("%d %B %Y, %H:%M")))
    sys.exit(1)


if __name__ == "__main__":
    main()
