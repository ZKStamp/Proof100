import json, subprocess, time, sys, requests

STATE = "/root/proof100/HealthState.json"
CLI = ["/root/bitcoinz/src/bitcoinz-cli", "-datadir=/root/.bitcoinz-issuing"]
SENDER = json.load(open("/root/proof100/Proof100Config.json"))["sender"]
ALERT_TO = "contact@z-text.com"
MIN_BALANCE = 1.0
STALE_SECONDS = 1800
ALERT_EVERY = 6 * 3600

def brevo_key():
    for line in open("/etc/zketernity/env"):
        if line.startswith("BREVO_API_KEY="):
            return line.split("=", 1)[1].strip()

def send_email(subject, text):
    r = requests.post("https://api.brevo.com/v3/smtp/email",
        headers={"api-key": brevo_key(), "content-type": "application/json"},
        json={"sender": {"name": "Z-TEXT Server", "email": "contact@z-text.com"},
              "to": [{"email": ALERT_TO}], "subject": subject, "textContent": text},
        timeout=30)
    print("email:", r.status_code)

def cli(*a):
    r = subprocess.run(CLI + list(a), capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:200])
    return r.stdout.strip()

try:
    st = json.load(open(STATE))
except Exception:
    st = {}
now = time.time()
problems = []

for svc in ["bitcoinzd", "zketernity", "Proof100Api", "Proof100Payments.timer"]:
    s = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True).stdout.strip()
    if s != "active":
        problems.append(f"Service {svc} is {s}")

try:
    info = json.loads(cli("getblockchaininfo"))
    blocks, headers = info["blocks"], info["headers"]
    if headers - blocks > 10:
        problems.append(f"Node behind: {blocks} of {headers} blocks")
    if blocks != st.get("last_height"):
        st["last_height"] = blocks
        st["last_change"] = now
    elif now - st.get("last_change", now) > STALE_SECONDS:
        problems.append(f"Chain not moving: stuck at block {blocks} for {int((now - st['last_change']) / 60)} min")
    bal = float(cli("z_getbalance", SENDER))
    if bal < MIN_BALANCE:
        problems.append(f"Low balance on paying address: {bal} BTCZ")
except Exception as e:
    problems.append(f"Node not answering: {e}")

if "test" in sys.argv:
    send_email("Z-TEXT server alarm: TEST",
               "This is a test of the server alarm.\nCurrent problems: " + ("; ".join(problems) or "none"))
elif problems and now - st.get("last_alert", 0) > ALERT_EVERY:
    send_email("Z-TEXT server alarm",
               "Problems found on the Zketernity / Proof-100 server:\n\n- " + "\n- ".join(problems)
               + "\n\nLog in: ssh root@107.189.22.109")
    st["last_alert"] = now

json.dump(st, open(STATE, "w"))
print("problems:", problems or "none")
