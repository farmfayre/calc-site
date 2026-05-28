#!/usr/bin/env python3
"""Email the weekly report (PDF + JSON archives) as attachments via the
existing msmtp/Postmark relay, for a Power Automate flow to file into the
team's OneDrive folder.

Design intent: the VM holds NO cloud-storage credential. Its only capability
is 'send an email from the verified sender'. That is the whole security win -
a compromise of this box cannot reach OneDrive, only send mail.
"""
import argparse, subprocess, sys, mimetypes, os
from email.message import EmailMessage

FROM_ADDR = os.environ.get("REPORT_EMAIL_FROM", "tech@farmfayre.com")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True)
    ap.add_argument("--week", required=True)
    ap.add_argument("--attach", action="append", default=[])
    args = ap.parse_args()

    msg = EmailMessage()
    msg["From"] = FROM_ADDR
    msg["To"] = args.to
    msg["Subject"] = f"[FF-REPORT] Weekly Cattle Prices - week ending {args.week}"
    msg.set_content(
        f"Automated Farm Fayre weekly market report for week ending {args.week}.\n\n"
        f"Attached: PDF report, public JSON, and internal JSON archive.\n"
        f"This message is filed to OneDrive automatically by Power Automate.\n"
        f"Do not reply."
    )

    attached = 0
    for path in args.attach:
        if not path or not os.path.isfile(path):
            print(f"[email] WARN: attachment missing, skipping: {path}", file=sys.stderr)
            continue
        ctype, _ = mimetypes.guess_type(path)
        maintype, subtype = (ctype.split("/", 1) if ctype else ("application", "octet-stream"))
        with open(path, "rb") as f:
            msg.add_attachment(f.read(), maintype=maintype, subtype=subtype,
                               filename=os.path.basename(path))
        attached += 1

    if attached == 0:
        print("[email] ERROR: no attachments found, refusing to send", file=sys.stderr)
        return 2

    try:
        p = subprocess.run(["msmtp", "-f", FROM_ADDR, args.to],
                           input=msg.as_bytes(), timeout=120)
    except FileNotFoundError:
        print("[email] ERROR: msmtp not found", file=sys.stderr); return 3
    except subprocess.TimeoutExpired:
        print("[email] ERROR: msmtp timed out", file=sys.stderr); return 4
    if p.returncode != 0:
        print(f"[email] ERROR: msmtp exited {p.returncode}", file=sys.stderr); return 5

    print(f"[email] Sent {attached} attachment(s) to {args.to} (week {args.week})")
    return 0

if __name__ == "__main__":
    sys.exit(main())
