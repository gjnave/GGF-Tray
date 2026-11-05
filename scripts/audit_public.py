"""Review the committed public tree before pushing and again on the Windows runner."""
from pathlib import PurePosixPath
import re
import subprocess
import sys

forbidden_names = {"app_tokens.json", "auth_desktop_v2.dat", "auth_cache.dat",
                   "auth_cache.json", "app_search_log.txt", "wp-config.php", ".env"}
forbidden_dirs = {"private", "desktop-server", "desktop-tests", "backup", "_backups", ".ssh"}
forbidden_ext = {".php", ".sql", ".sqlite", ".sqlite3", ".pfx", ".pem", ".winscp", ".log"}
text_ext = {".py", ".js", ".bat", ".cmd", ".md", ".txt", ".yml", ".json", ".ps1", ".spec"}
secret = re.compile(rb"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----|"
                    rb"(?:ghp_|github_pat_|sk_live_|AKIA|ASIA)[A-Za-z0-9_]{16,}|"
                    rb"ggf_(?:desktop|tray)_[A-Za-z0-9_-]{24,}")

def git(*args):
    return subprocess.check_output(["git", *args])

def main():
    failures = []
    for entry in git("ls-tree", "-rz", "--name-only", "HEAD").decode().split("\0"):
        if not entry:
            continue
        path = PurePosixPath(entry.lower())
        if (path.name in forbidden_names or path.name.startswith(".env.") or
                path.suffix in forbidden_ext or forbidden_dirs.intersection(path.parts)):
            failures.append(entry)
        elif path.suffix in text_ext and secret.search(git("show", "HEAD:" + entry)):
            failures.append(entry)
    if failures:
        print("Review before publication. Sensitive paths or credential patterns in:", *failures, sep="\n")
        return 1
    print("Public tree passed the backend-file and credential-pattern checks.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
