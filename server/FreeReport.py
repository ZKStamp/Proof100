# Free stamp_hash report. Run on the server: python3 /root/proof100/FreeReport.py
# Success goal (21 Nov 2026): 10 different outside callers in 7 days.
# Your own test calls count as one caller (or more if you test from several networks).
import FreeStamp

total, callers, days = FreeStamp.report()
print("Free stamps made:     %d of %d" % (total, FreeStamp.FREE_TOTAL))
print("Different callers:    %d (goal: 10 outside callers)" % callers)
print("Free stamps per day (last 14 days):")
for day, n in days:
    print("  ", day, n)
