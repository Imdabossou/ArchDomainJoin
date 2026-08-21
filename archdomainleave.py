#!/usr/bin/env python3
"""
leave_domain.py — Arch Linux Active Directory Removal
Reverts everything done by join_domain.py: leaves the AD domain,
restores original config files (or deletes ones that had none),
disables the services/timers it enabled, and restarts Plasma
Login Manager. Run with sudo.
"""

import os
import sys
import subprocess
import shutil
import getpass

# ── Colour helpers ────────────────────────────────────────────────────────────
R  = "\033[31m"; G  = "\033[32m"; Y  = "\033[33m"
B  = "\033[34m"; W  = "\033[0m";  BO = "\033[1m"

def ok(msg):    print(f"  {G}[✓]{W} {msg}")
def err(msg):   print(f"  {R}[✗]{W} {msg}")
def warn(msg):  print(f"  {Y}[!]{W} {msg}")
def info(msg):  print(f"  {B}[·]{W} {msg}")
def header(t):  print(f"\n{BO}{'='*60}\n  {t}\n{'='*60}{W}")

def die(msg):
    err(msg)
    sys.exit(1)

# ── Privilege check ───────────────────────────────────────────────────────────
if os.geteuid() != 0:
    die("Please run with sudo:  sudo python3 leave_domain.py")

def run(cmd, check=True, capture=False):
    kwargs = dict(check=check)
    if capture:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if isinstance(cmd, str):
        kwargs["shell"] = True
    return subprocess.run(cmd, **kwargs)

def run_ok(cmd):
    r = run(cmd if isinstance(cmd, list) else cmd.split(), check=False, capture=True)
    return r.returncode == 0

# The exact set of files join_domain.py backs up before overwriting,
# plus files it writes fresh (no backup possible/expected).
BACKED_UP_FILES = [
    "/etc/krb5.conf",
    "/etc/samba/smb.conf",
    "/etc/security/pam_winbind.conf",
    "/etc/resolv.conf",
    "/etc/nsswitch.conf",
    "/etc/pam.d/system-auth",
    "/etc/pam.d/su",
    "/etc/pam.d/plasmalogin",
]

# Files join_domain.py created that did not exist before (new drop-ins),
# so on revert they should just be removed.
NEW_FILES = [
    "/etc/plasmalogin.conf.d/ad.conf",
    "/etc/systemd/timesyncd.conf.d/ad.conf",
]

def restore_or_remove(path):
    bak = path + ".bak"
    if os.path.isfile(bak):
        shutil.copy2(bak, path)
        os.remove(bak)
        ok(f"Restored original: {path}")
    elif os.path.isfile(path):
        os.remove(path)
        warn(f"No backup found for {path} — removed instead (was likely created fresh).")
    else:
        info(f"Nothing to do for {path} (not present).")

def remove_file(path):
    if os.path.isfile(path):
        os.remove(path)
        ok(f"Removed: {path}")
    else:
        info(f"Already absent: {path}")

# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 1 — Confirm
# ─────────────────────────────────────────────────────────────────────────────
header("Phase 1 — Confirm")

warn("This will leave the AD domain, restore pre-join config files")
warn("(from the .bak backups made at join time), and disable the")
warn("services/timesync settings that join_domain.py enabled.")

confirm = input("\n  Proceed? [y/N]: ").strip().lower()
if confirm != "y":
    die("Aborted.")

# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 2 — Leave the domain (best-effort, needs AD credentials)
# ─────────────────────────────────────────────────────────────────────────────
header("Phase 2 — Leaving Domain")

if run_ok(["which", "net"]):
    do_leave = input("  Attempt 'net ads leave' now? Requires AD admin creds [Y/n]: ").strip().lower()
    if do_leave != "n":
        ad_user = input("  AD username with rights to unjoin (blank to skip): ").strip()
        if ad_user:
            ad_pass = getpass.getpass(f"  Password for {ad_user}: ")
            result = run(["net", "ads", "leave", "-U", f"{ad_user}%{ad_pass}"], check=False)
            if result.returncode == 0:
                ok("Left the domain (computer account removed from AD).")
            else:
                warn("net ads leave failed — the computer account may need to be")
                warn("removed manually from AD. Continuing with local cleanup anyway.")
        else:
            info("Skipped 'net ads leave'. You may need to remove the computer")
            info("account from Active Directory manually.")
    else:
        info("Skipped 'net ads leave'.")
else:
    warn("'net' command not found — skipping domain leave, continuing with local cleanup.")

# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 3 — Stop & disable services
# ─────────────────────────────────────────────────────────────────────────────
header("Phase 3 — Disabling Services")

for svc in ["winbind.service", "smb.service"]:
    run(f"systemctl disable --now {svc}", check=False)
    ok(f"Disabled & stopped: {svc}")

# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 4 — Restore / remove config files
# ─────────────────────────────────────────────────────────────────────────────
header("Phase 4 — Restoring Configuration Files")

for path in BACKED_UP_FILES:
    restore_or_remove(path)

for path in NEW_FILES:
    remove_file(path)

# Clean up empty drop-in dirs that join_domain.py may have created
for d in ["/etc/plasmalogin.conf.d", "/etc/systemd/timesyncd.conf.d"]:
    if os.path.isdir(d) and not os.listdir(d):
        os.rmdir(d)
        ok(f"Removed empty directory: {d}")

run("systemctl daemon-reload")
run("systemctl restart systemd-timesyncd.service", check=False)

# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 5 — Optional: remove packages
# ─────────────────────────────────────────────────────────────────────────────
header("Phase 5 — Packages")

rm_pkgs = input("  Remove samba/krb5/smbclient packages too? [y/N]: ").strip().lower()
if rm_pkgs == "y":
    run("pacman -Rns --noconfirm samba krb5 smbclient", check=False)
    ok("Packages removed.")
else:
    info("Left packages installed.")

# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 6 — Verification
# ─────────────────────────────────────────────────────────────────────────────
header("Phase 6 — Verification")

checks = [
    ("winbind.service inactive", ["bash", "-c", "! systemctl is-active --quiet winbind.service"]),
    ("smb.service inactive",     ["bash", "-c", "! systemctl is-active --quiet smb.service"]),
    ("No AD drop-in for plasmalogin", ["bash", "-c", "! test -f /etc/plasmalogin.conf.d/ad.conf"]),
    ("No AD drop-in for timesyncd",   ["bash", "-c", "! test -f /etc/systemd/timesyncd.conf.d/ad.conf"]),
]

passed = failed = 0
for label, cmd in checks:
    if run_ok(cmd):
        ok(label)
        passed += 1
    else:
        err(label)
        failed += 1

header("Complete")
print(f"  {G}{BO}{passed} checks passed{W}", end="")
if failed:
    print(f"  {R}{failed} failed{W}\n")
else:
    print("  —  all good!\n")

print(f"""  {BO}Notes:{W}
    - /etc/resolv.conf now points back at your original DNS (or was
      removed if there was no prior version — you may want to set it
      manually or re-enable your DHCP client / NetworkManager DNS).
    - If 'net ads leave' was skipped or failed, remove the computer
      object from Active Directory manually.
    - PAM/login config has been restored, so only local accounts
      should be able to log in now.
""")

# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 7 — Restart Plasma Login Manager
# ─────────────────────────────────────────────────────────────────────────────
header("Phase 7 — Restarting Plasma Login Manager")

warn("Plasma Login Manager will restart now.")
warn("Your graphical session will close immediately.")
input("  Press Enter to restart and log out (or Ctrl-C to skip and exit safely)...")

run("systemctl restart plasmalogin.service", check=False)
