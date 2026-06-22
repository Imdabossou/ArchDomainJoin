#!/usr/bin/env python3
"""
join_domain.py — Arch Linux Active Directory Integration
Joins the machine to a Windows AD domain and configures
Plasma Login Manager for domain account login. Run with sudo.
"""

import os
import sys
import subprocess
import shutil
import time
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
    die("Please run with sudo:  sudo python3 join_domain.py")

# ── Detect the real (non-root) user ──────────────────────────────────────────
SUDO_USER = os.environ.get("SUDO_USER", "")
if SUDO_USER and SUDO_USER != "root":
    REAL_USER = SUDO_USER
else:
    # Fall back to lowest-uid human account
    import pwd
    candidates = [p for p in pwd.getpwall() if 1000 <= p.pw_uid < 65534]
    if not candidates:
        die("Could not determine a non-root user.")
    REAL_USER = sorted(candidates, key=lambda p: p.pw_uid)[0].pw_name

REAL_UID = int(subprocess.check_output(["id", "-u", REAL_USER]).strip())
info(f"Local user detected: {REAL_USER} (uid {REAL_UID})")

# ── Helper: run a shell command ───────────────────────────────────────────────
def run(cmd, check=True, capture=False, as_user=None):
    if as_user:
        cmd = ["sudo", "-u", as_user] + (cmd if isinstance(cmd, list) else cmd.split())
    kwargs = dict(check=check)
    if capture:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if isinstance(cmd, str) and not as_user:
        kwargs["shell"] = True
    return subprocess.run(cmd, **kwargs)

def run_ok(cmd, as_user=None):
    """Return True if command exits 0, False otherwise."""
    r = run(cmd if isinstance(cmd, list) else cmd.split(),
            check=False, capture=True, as_user=as_user)
    return r.returncode == 0

def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)

def backup(path):
    if os.path.isfile(path):
        shutil.copy2(path, path + ".bak")
        info(f"Backed up: {path}")

# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 1 — Gather settings
# ─────────────────────────────────────────────────────────────────────────────
header("Phase 1 — Domain Settings")

def ask(prompt, default):
    val = input(f"  {prompt} [{default}]: ").strip()
    return val if val else default

domain      = ask("Windows AD Domain (e.g. CORP.EXAMPLE.COM)", "MSHOME.NET").upper()
domain_l    = domain.lower()
default_nb  = domain.split(".")[0]
netbios     = ask("NetBIOS / Workgroup name", default_nb).upper()
dc_ip       = ask("Domain Controller IP", "172.20.192.1")
dc_fqdn     = ask("Domain Controller hostname (FQDN)", f"dc1.{domain_l}").upper()
ad_user     = ask("AD username to join domain", "Administrator")
ad_pass     = getpass.getpass(f"  Password for {ad_user}@{domain}: ")

print()
info(f"Domain      : {domain}")
info(f"NetBIOS     : {netbios}")
info(f"DC IP       : {dc_ip}")
info(f"DC FQDN     : {dc_fqdn}")
info(f"AD user     : {ad_user}")

confirm = input("\n  Proceed? [Y/n]: ").strip().lower()
if confirm == "n":
    die("Aborted.")

# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 2 — Install packages
# ─────────────────────────────────────────────────────────────────────────────
header("Phase 2 — Installing Packages")

pkgs = ["samba", "krb5", "smbclient"]
info(f"Installing: {' '.join(pkgs)}")
run(f"pacman -Sy --noconfirm --needed {' '.join(pkgs)}")
ok("Packages up to date.")

# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 3 — Generate & deploy config files
# ─────────────────────────────────────────────────────────────────────────────
header("Phase 3 — Generating & Deploying Configuration Files")

# ── krb5.conf ────────────────────────────────────────────
krb5 = f"""[libdefaults]
    default_realm = {domain}
    dns_lookup_realm = false
    dns_lookup_kdc = true
    default_ccache_name = /run/user/%{{uid}}/krb5cc

[realms]
    {domain} = {{
        kdc = {dc_fqdn}
        default_domain = {domain}
        admin_server = {dc_fqdn}
    }}
    {netbios} = {{
        kdc = {dc_fqdn}
        default_domain = {domain}
        admin_server = {dc_fqdn}
    }}

[domain_realm]
    .{domain_l} = {domain}
    {domain_l} = {domain}

[appdefaults]
    pam = {{
        ticket_lifetime = 1d
        renew_lifetime = 1d
        forwardable = true
        proxiable = false
        minimum_uid = 1
    }}
"""

# ── smb.conf ─────────────────────────────────────────────
smb = f"""[global]
   workgroup = {netbios}
   security = ADS
   realm = {domain}
   server string = %h Arch Linux Host

   winbind refresh tickets = Yes
   winbind use default domain = yes
   winbind offline logon = yes

   dedicated keytab file = /etc/krb5.keytab
   kerberos method = secrets and keytab

   vfs objects = acl_xattr
   map acl inherit = Yes
   store dos attributes = Yes

   idmap config * : backend = tdb
   idmap config * : range = 3000-7999
   idmap config {netbios} : backend = rid
   idmap config {netbios} : range = 10000-999999

   template shell = /bin/bash
   template homedir = /home/%U

   load printers = no
   printing = bsd
   printcap name = /dev/null
   disable spoolss = yes
"""

# ── pam_winbind.conf ──────────────────────────────────────
pam_winbind = """[Global]
   debug = no
   debug_state = no
   try_first_pass = yes
   krb5_auth = yes
   krb5_ccache_type = FILE:/run/user/%u/krb5cc
   cached_login = yes
   silent = no
   mkhomedir = yes
"""

# ── resolv.conf ───────────────────────────────────────────
resolv = f"""# Generated for Active Directory resolution
nameserver {dc_ip}
search {domain_l}
"""

# ── nsswitch.conf ─────────────────────────────────────────
nsswitch = """# NSS — Active Directory via winbind
passwd:   files winbind systemd
group:    files [SUCCESS=merge] winbind systemd
shadow:   files systemd
gshadow:  files systemd
publickey: files
hosts:    mymachines resolve [!UNAVAIL=return] files myhostname dns
networks: files
protocols: files
services:  files
ethers:    files
rpc:       files
netgroup:  files
"""

# ── system-auth (PAM) ────────────────────────────────────
system_auth = """#%PAM-1.0

auth       required                    pam_faillock.so      preauth
-auth      [success=3 default=ignore]  pam_systemd_home.so
auth       [success=2 default=ignore]  pam_winbind.so
auth       [success=1 default=bad]     pam_unix.so          try_first_pass nullok
auth       [default=die]               pam_faillock.so      authfail
auth       optional                    pam_permit.so
auth       required                    pam_env.so
auth       required                    pam_faillock.so      authsucc

-account   [success=2 default=ignore]  pam_systemd_home.so
account    [success=1 default=ignore]  pam_winbind.so
account    required                    pam_unix.so
account    optional                    pam_permit.so
account    required                    pam_time.so

-password  [success=2 default=ignore]  pam_systemd_home.so
password   [success=1 default=ignore]  pam_winbind.so
password   required                    pam_unix.so          try_first_pass nullok shadow sha512
password   optional                    pam_permit.so

-session   optional                    pam_systemd_home.so
session    required                    pam_mkhomedir.so     skel=/etc/skel/ umask=0022
session    required                    pam_limits.so
session    optional                    pam_systemd.so
session    required                    pam_winbind.so
session    required                    pam_unix.so
session    optional                    pam_permit.so
"""

# ── su (PAM) ──────────────────────────────────────────────
su_pam = """#%PAM-1.0
auth            sufficient      pam_rootok.so
auth            sufficient      pam_winbind.so
auth            required        pam_unix.so
account         sufficient      pam_winbind.so
account         required        pam_unix.so
session         optional        pam_systemd.so
session         sufficient      pam_winbind.so
session         required        pam_unix.so
password        include         system-auth
"""

# ── Plasma Login Manager PAM ──────────────────────────────
plasmalogin_pam = """#%PAM-1.0

auth       include      system-auth

account    include      system-auth

password   include      system-auth

-session   optional     pam_systemd_home.so
session    required     pam_mkhomedir.so     skel=/etc/skel/ umask=0022
session    optional     pam_keyinit.so       force revoke
session    include      system-auth
session    optional     pam_systemd.so
"""

# ── Deploy everything ────────────────────────────────────
configs = {
    "/etc/krb5.conf":                    krb5,
    "/etc/samba/smb.conf":               smb,
    "/etc/security/pam_winbind.conf":    pam_winbind,
    "/etc/resolv.conf":                  resolv,
    "/etc/nsswitch.conf":                nsswitch,
    "/etc/pam.d/system-auth":            system_auth,
    "/etc/pam.d/su":                     su_pam,
    "/etc/pam.d/plasmalogin":            plasmalogin_pam,
}

for path, content in configs.items():
    backup(path)
    write(path, content)
    ok(f"Deployed: {path}")

# ── Plasma Login Manager config — raise UID ceiling for domain accounts ──
plasma_login_conf = """[Users]
MinimumUid=1000
MaximumUid=999999
HideUsers=
HideShells=
"""
write("/etc/plasmalogin.conf.d/ad.conf", plasma_login_conf)
ok("Deployed: /etc/plasmalogin.conf.d/ad.conf  (UID range for domain users)")

# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 4 — Time synchronisation (critical for Kerberos)
# ─────────────────────────────────────────────────────────────────────────────
header("Phase 4 — Time Synchronisation")

write("/etc/systemd/timesyncd.conf.d/ad.conf",
      f"[Time]\nNTP={dc_ip}\n")
ok(f"NTP server set to DC: {dc_ip}")

run("systemctl daemon-reload")
run("systemctl enable --now systemd-timesyncd.service")
run("systemctl restart systemd-timesyncd.service")

info("Waiting for time sync (up to 30 s)...")
for i in range(15):
    r = run(["timedatectl", "show", "--property=NTPSynchronized", "--value"],
            capture=True, check=False)
    if r.stdout.strip() == "yes":
        ok("Time synchronised.")
        break
    time.sleep(2)
else:
    warn("Time sync not confirmed. Kerberos may fail — check: timedatectl status")

# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 5 — Kerberos ticket & domain join
# ─────────────────────────────────────────────────────────────────────────────
header("Phase 5 — Kerberos Ticket & Domain Join")

import tempfile, stat

tmp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".pw")
tmp.write(ad_pass + "\n")
tmp.flush()
tmp.close()
os.chmod(tmp.name, stat.S_IRUSR)

try:
    info(f"Obtaining Kerberos ticket for {ad_user}@{domain}...")
    result = run(
        f"kinit {ad_user}@{domain} < {tmp.name}",
        check=False
    )
    if result.returncode != 0:
        die(f"kinit failed. Check the password and that the DC is reachable at {dc_fqdn}.")
    ok("Kerberos ticket obtained.")

    info(f"Joining domain {domain}...")
    result = run(
        f"net ads join -U {ad_user}%{ad_pass}",
        check=False
    )
    if result.returncode != 0:
        die("net ads join failed. Check credentials and network connectivity to the DC.")
    ok("Domain join successful.")
finally:
    os.unlink(tmp.name)

# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 6 — Enable services
# ─────────────────────────────────────────────────────────────────────────────
header("Phase 6 — Enabling Services")

for svc in ["smb.service", "winbind.service"]:
    run(f"systemctl enable --now {svc}")
    ok(f"Enabled & started: {svc}")

time.sleep(3)

# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 7 — Verification
# ─────────────────────────────────────────────────────────────────────────────
header("Phase 7 — Verification")

checks = [
    ("Winbind DC ping",                ["wbinfo", "--ping-dc"]),
    ("List domain users",              ["wbinfo", "-u"]),
    ("List domain groups",             ["wbinfo", "-g"]),
    ("NSS resolves AD users",          ["getent", "passwd"]),
    ("Plasma Login PAM file present",  ["test", "-f", "/etc/pam.d/plasmalogin"]),
    ("Plasma Login conf deployed",     ["test", "-f", "/etc/plasmalogin.conf.d/ad.conf"]),
]

passed = 0
failed = 0
for label, cmd in checks:
    if run_ok(cmd):
        ok(label)
        passed += 1
    else:
        err(label)
        failed += 1

# ─────────────────────────────────────────────────────────────────────────────
#  Summary & Instructions
# ─────────────────────────────────────────────────────────────────────────────
header("Complete")
print(f"  {G}{BO}{passed} checks passed{W}", end="")
if failed:
    print(f"  {R}{failed} failed{W}")
    print()
    warn("Troubleshooting:")
    info("  journalctl -xe | grep -E 'winbind|smb|krb5|plasmalogin'")
    info("  net ads info")
    info("  wbinfo --ping-dc")
else:
    print(f"  —  all good!\n")

print(f"""  {BO}To log in via Plasma Login Manager:{W}
    Username:  {ad_user}  (or DOMAIN\\\\username)
    Password:  your AD password

  Home directories are created automatically on first login.
  If login fails, check: journalctl -u plasmalogin -f
""")

# ─────────────────────────────────────────────────────────────────────────────
#  PHASE 8 — Restart Plasma Login Manager
# ─────────────────────────────────────────────────────────────────────────────
header("Phase 8 — Restarting Plasma Login Manager")

warn("Plasma Login Manager will restart now.")
warn("Your graphical session will close immediately.")
input("  Press Enter to restart and log out (or Ctrl-C to skip and exit safely)...")

run("systemctl restart plasmalogin.service", check=False)
