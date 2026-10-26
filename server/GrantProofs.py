import sys
from Proof100Core import create_account, db

n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
key, addr = create_account()
con = db()
with con:
    con.execute("UPDATE accounts SET proofs_left = proofs_left + ? WHERE deposit_address=?", (n, addr))
con.close()
print("FREE TESTER PACK:", n, "proofs")
print("SECRET KEY (shown once):", key)
print("DEPOSIT ADDRESS:", addr)
