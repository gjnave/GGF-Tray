"""Render the public download page and version-specific GitHub release notes."""
import argparse
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPO = "gjnave/GGF-Tray"
ORIGIN = f"https://github.com/{REPO}"
ASSETS = ("GGF-Tray-Windows-x64.zip", "GGF-Tray-OneFile.exe", "SHA256SUMS.txt")


def gh_json(endpoint, *options):
    command = ["gh", "api", *options, f"repos/{REPO}/releases{endpoint}"]
    return json.loads(subprocess.check_output(command, encoding="utf-8"))


def date_label(iso):
    day = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    return f"{day:%B} {day.day}, {day.year}"


def render(template, **values):
    return re.sub(r"@@([A-Z_]+)@@", lambda match: values[match[1]], template)


def release_tag(value):
    if not re.fullmatch(r"v\.?[0-9]+(?:\.[0-9]+)*", value):
        raise ValueError(f"Unexpected release tag: {value!r}")
    return value


def build_site(out):
    latest = gh_json("/latest")
    releases = [r for page in gh_json("?per_page=100", "--paginate", "--slurp") for r in page
                if not r["draft"] and not r["prerelease"]]
    tag = release_tag(latest["tag_name"])
    if latest["id"] not in {r["id"] for r in releases}:
        raise ValueError("The latest release is missing from public history.")
    assets = {a["name"]: a for a in latest["assets"] if a["state"] == "uploaded"}
    for name in ASSETS:
        if assets[name]["browser_download_url"] != f"{ORIGIN}/releases/download/{tag}/{name}":
            raise ValueError(f"Unexpected download address for {name}")
    rows = []
    for r in sorted(releases, key=lambda r: (r["id"] == latest["id"], r["published_at"]), reverse=True):
        version = release_tag(r["tag_name"])
        link = f"{ORIGIN}/releases/tag/{version}"
        badge = '<span class="latest">Latest</span>' if version == tag else ""
        day = escape(r["published_at"][:10])
        rows.append(f'<tr><th scope="row">{version}{badge}</th><td><time datetime="{day}">'
                    f'{date_label(r["published_at"])}</time></td><td><a href="{link}" aria-label="View release {version}">'
                    'View release <span aria-hidden="true">↗</span></a></td></tr>')
    source = ROOT / "downloads"
    text = render((source / "index.html").read_text(encoding="utf-8"), VERSION=tag,
                  DATE=date_label(latest["published_at"]), SIZE=f'{assets[ASSETS[0]]["size"] / 1_000_000:.1f} MB',
                  ZIP=assets[ASSETS[0]]["browser_download_url"], EXE=assets[ASSETS[1]]["browser_download_url"],
                  HASH=assets[ASSETS[2]]["browser_download_url"], LICENSE=f"{ORIGIN}/blob/{tag}/LICENSE.txt",
                  ROWS="\n".join(rows))
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(text, encoding="utf-8")
    for file in (source / "style.css", source / "tray-art.svg", ROOT / "ggf-menu/artwork/ggf-mark.svg"):
        shutil.copyfile(file, out / file.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("site").add_argument("out", type=Path)
    notes = commands.add_parser("notes")
    notes.add_argument("out", type=Path)
    notes.add_argument("--tag", required=True)
    notes.add_argument("--art-ref", required=True)
    notes.add_argument("--published-at", help="Keep the original date when updating an existing release.")
    args = parser.parse_args()
    if args.action == "site":
        build_site(args.out)
    else:
        if not re.fullmatch(r"[a-f0-9]{40}", args.art_ref):
            parser.error("Use a full commit SHA for the release artwork.")
        template = (ROOT / ".github/release-notes.md").read_text(encoding="utf-8")
        published_at = args.published_at or datetime.now(timezone.utc).isoformat()
        args.out.write_text(render(template, TAG=release_tag(args.tag), REF=args.art_ref,
                                   DATE=date_label(published_at)), encoding="utf-8")


if __name__ == "__main__":
    main()
