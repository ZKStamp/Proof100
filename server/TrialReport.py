# Free trial report: how many trial accounts, and how many paying accounts.
# Run on the server: python3 /root/proof100/TrialReport.py
from Proof100Core import db, TRIAL_PROOFS, TRIAL_PER_DAY, TRIAL_END

c = db()
total = c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
trial = c.execute("SELECT COUNT(*) FROM accounts WHERE trial=1").fetchone()[0]
paying = c.execute("SELECT COUNT(*) FROM accounts WHERE packs_credited>0").fetchone()[0]
both = c.execute("SELECT COUNT(*) FROM accounts WHERE trial=1 AND packs_credited>0").fetchone()[0]
print("Free trial:", TRIAL_PROOFS, "proofs,", TRIAL_PER_DAY, "accounts/day, until", TRIAL_END)
print("All accounts:     ", total)
print("Trial accounts:   ", trial)
print("Paying accounts:  ", paying)
print("Trial then paid:  ", both)
print("Trial accounts per day (last 14 days):")
for day, n in c.execute("SELECT substr(created_at,1,10) d, COUNT(*) FROM accounts WHERE trial=1 "
                        "GROUP BY d ORDER BY d DESC LIMIT 14"):
    print("  ", day, n)
