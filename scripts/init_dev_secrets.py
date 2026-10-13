"""Create the local Compose credential once, without printing or replacing it."""

import os
import secrets
import stat
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
relative_path = ".secrets/postgres_password"
ignored = subprocess.run(
    ["git", "check-ignore", "--quiet", relative_path], cwd=root, check=False
)
tracked = subprocess.run(
    ["git", "ls-files", "--error-unmatch", relative_path],
    cwd=root,
    check=False,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
if ignored.returncode != 0 or tracked.returncode == 0:
    raise SystemExit("Refusing to create a credential unless gitignored and untracked")
directory = root / ".secrets"
if directory.is_symlink():
    raise SystemExit("Refusing to use a symlink for the secrets directory")
directory.mkdir(mode=0o700, exist_ok=True)
directory.chmod(0o700)
path = root / relative_path
if path.exists() or path.is_symlink():
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise SystemExit("Credential path must be a regular file")
    print("Existing local credential preserved")
else:
    # The private parent directory protects the host file; Compose must expose
    # the file read-only to the non-root migration container user.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w") as output:
        os.fchmod(output.fileno(), 0o644)
        output.write(secrets.token_urlsafe(32) + "\n")
    print("Local Compose credential created; its value is not displayed")
