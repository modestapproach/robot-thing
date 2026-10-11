"""Fill the <db_password> placeholder in autolab/.env without echoing the password.

  .venv/bin/python scripts/set_db_password.py

Prompts with hidden input, strips stray whitespace, URL-encodes special characters,
replaces the placeholder or any previous password in .env, then pings Atlas.
The password is never printed.
"""
import getpass
import pathlib
import re
import subprocess
import sys
from urllib.parse import quote

ROOT = pathlib.Path(__file__).resolve().parent.parent
env = ROOT / ".env"
text = env.read_text()
m = re.search(r"^MONGODB_URI=(.*)$", text, re.M)
if not m:
    sys.exit("No MONGODB_URI line in autolab/.env")
uri = m.group(1)
# Replace whatever sits between "user:" and "@" (placeholder or an old password).
um = re.match(r"^(mongodb(?:\+srv)?://[^:/@]+):([^@]*)@(.*)$", uri)
if not um:
    sys.exit("MONGODB_URI is not in the form mongodb+srv://user:password@host/...")
pw = getpass.getpass("Password for Atlas database user ted-dessert (input hidden, paste then Enter): ").strip()
if not pw:
    sys.exit("Empty password; nothing changed.")
new_uri = f"{um.group(1)}:{quote(pw, safe='')}@{um.group(3)}"
env.write_text(text.replace(f"MONGODB_URI={uri}", f"MONGODB_URI={new_uri}", 1))
print(f"Saved to autolab/.env (gitignored), {len(pw)} characters.")
sys.exit(subprocess.call([sys.executable, str(ROOT / "scripts" / "check_atlas.py")]))
