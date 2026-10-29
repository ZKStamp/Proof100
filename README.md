# ZKStamp · Proof-100

**Stamp it with Z. Before Q.**

🎬 **Watch the 60-second demo:** [an AI agent stamps an idea, then ZCheck says VALID, and NOT VALID with one letter changed](https://youtu.be/t2G2CUKyamo)

Proof-100 writes the SHA-256 fingerprint of any file to the BitcoinZ blockchain in a shielded (zk-SNARK) transaction. You get a dated proof that the file existed, and nobody on the blockchain can see the fingerprint or who made it.

- **ZKStamp** is the brand.
- **Proof-100** is what you buy: a pack of 100 proofs.
- **ZCheck** is how you check: a small script that verifies a proof on your own BitcoinZ node.

Service: `https://proof.zketernity.app` · For AI agents: [`/llms.txt`](https://proof.zketernity.app/llms.txt)

---

## How it works

1. You send a **fingerprint** (SHA-256, 64 hex characters). Your file never leaves your machine.
2. The server writes `PROOF100 sha256:<fingerprint>` into the encrypted memo of a shielded BitcoinZ transaction, sent to a **brand-new address** made for this one proof.
3. You get back the **transaction ID** and that address's **viewing key**.
4. The block's timestamp dates your proof.
5. To prove it later, give someone the **transaction ID + viewing key**. With ZCheck, they read the fingerprint straight from the blockchain and compare it with your file. They see **this one proof and nothing else**.

**Keep your viewing key.** Without it, that proof cannot be revealed.

---

## Quick start (API)

Base URL: `https://proof.zketernity.app`

**1. Create an account** (your key is shown once, so save it):

```bash
curl -s -X POST https://proof.zketernity.app/v1/account
```

Returns `key` (starts with `p100_`), `deposit_address` (shielded, `zs`) and `t_deposit_address` (transparent, `t`).

**Free trial:** new accounts get **3 free proofs**, no payment needed (limited to 13 new trial accounts per day, until 27 November 2026). The response shows `free_proofs`.

**2. Buy proofs:** send **500,000 BTCZ** to either address, or split it across both. After 2 confirmations, **100 proofs** are credited automatically.

- `deposit_address` (`zs`): **fully private** payment.
- `t_deposit_address` (`t`): for exchanges and t-only wallets like Coinomi. Your payment is visible on the blockchain, but your proofs stay fully shielded. The server moves these coins to the shielded side by itself (the operator pays that 0.0001 BTCZ fee).

**3. Check your balance:**

```bash
curl -s https://proof.zketernity.app/v1/balance -H "Authorization: Bearer YOUR_KEY"
```

**4. Make a proof:**

```bash
FP=$(sha256sum MyFile.pdf | cut -d' ' -f1)
curl -s -X POST https://proof.zketernity.app/v1/proof \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"fingerprint\": \"$FP\"}"
```

Returns `txid`, `viewing_key` and `proofs_left`. A proof takes about 10 to 60 seconds.

The key is accepted as `Authorization: Bearer <key>` (with or without the space) or as `X-API-Key: <key>`.

---

## For AI agents (MCP)

Proof-100 speaks MCP at:

```
https://proof.zketernity.app/mcp
```

Tools:

| Tool | What it does |
|---|---|
| `timestamp_fingerprint` | Timestamp a SHA-256 fingerprint. Returns txid + viewing key. |
| `timestamp_text` | The server hashes a short text (the text is not stored) and timestamps the fingerprint. |
| `check_balance` | Proofs left and your deposit address. |

In Claude: add a custom connector with that URL, choose no sign-in, and add the request header `Authorization` = `Bearer YOUR_KEY`.

---

## Verify a proof with ZCheck

You need a synced BitcoinZ node, Python 3, the original file, the txid and the viewing key.

```bash
python3 zcheck/ZCheck.py --txid <txid> --viewing-key <zxviews...> --file MyFile.pdf
```

Answers:

- `VALID: this exact fingerprint was written on the BitcoinZ blockchain in block N, on <date> UTC`
- `NOT VALID: ... holds a different fingerprint` (the file was changed)

The first run scans the chain from block 1,862,000 for that viewing key, which can take a few minutes. Options: `--cli` (path to `bitcoinz-cli`), `--datadir`, `--start-height`, or `--fingerprint` instead of `--file`.

---

## Price

**500,000 BTCZ for 100 proofs**, paid in BTCZ only. No card, no email, no account name. One proof costs 5,000 BTCZ: a fraction of the price of a €2 coffee. ☕

**Coming from an exchange, or from a wallet that only sends to t-addresses (like Coinomi)?** Pay your `t_deposit_address` directly. For a fully private payment, send your BTCZ to the free [Z-TEXT](https://z-text.com/downloads) wallet first: it shields them automatically. Then pay from Z-TEXT to your `zs` deposit address.

Questions, or no BTCZ yet? Write to contact@z-text.com. We'll help you find where to get BTCZ.

---

## Trust model and honest limits

- **What the blockchain hides:** the fingerprint, the addresses and the amounts are inside a shielded transaction. Block explorers show only that a transaction exists.
- **What the server sees:** the operator's server receives your fingerprint (and, for `timestamp_text`, your text) when you submit it. It does not log fingerprints or texts, and it does not store which proof belongs to which account. You can read the code in this repository.
- **One operator, one server:** if the server is down, no new proofs can be made. Existing proofs stay on the blockchain and remain verifiable with ZCheck on any BitcoinZ node.
- **Quantum:** the SHA-256 fingerprint and its date are expected to hold up well against quantum computers. The privacy of shielded transactions relies on today's zk-SNARK cryptography, which is **not** post-quantum. A future quantum computer could, in theory, read old memos, which would reveal fingerprints (never files).
- **BitcoinZ** is a small chain with thin trading volume. Factor that in for high-stakes uses.

---

## Self-hosting

- `server/`: the code that runs the service (Python 3, Flask).
  - `Proof100Core.py`: accounts, payment watch, making proofs
  - `Proof100Api.py`: REST API and MCP endpoint (listens on 127.0.0.1:5100)
  - `CheckPayments.py`, `CreateAccount.py`, `HealthCheck.py`
  - `GrantProofs.py`: operator tool, creates an account with free proofs (for testers)
- `deploy/`: example systemd units, nginx site and config templates.
- `zcheck/ZCheck.py`: the verifier.

Requirements: a synced BitcoinZ node (2.3.1 or later) with a funded shielded address, Python 3 with `flask` and `requests`, and nginx with a TLS certificate. Never commit `Proof100Config.json`, the database, or any key.

---

## Related

**[I Am Wallet](https://github.com/ZKStamp/AgentWallet)**: shielded BitcoinZ wallets for AI agents, same operator. Agents pay and send private messages to each other, by themselves ([llms.txt](https://proof.zketernity.app/agent/llms.txt)).

---

## Contact

contact@z-text.com (Z-TEXT LLC)

---

## License

MIT. See [LICENSE](LICENSE).
