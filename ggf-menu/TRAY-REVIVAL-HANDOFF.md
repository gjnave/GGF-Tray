# GGF Tray — Revival Handoff

## CURRENT STATUS — v0.12.0 BUILT AND VERIFIED 2026-07-11

The revival is no longer source-only. The current local release is:

- `C:\GGF\ggf-menu\dist_onefile\GGF-Tray-OneFile.exe`
- version `0.12.0`, 252,212,020 bytes
- SHA-256 `88C275C1C784DAC85C5D7634EE69C24C02C67E28108823C607225C3B9930CA9A`
- built locally with Python 3.10.11 + PyInstaller 6.21.0; packaged self-test passed

Two passes were completed. Major changes: first-party GGF login (no Patreon),
DPAPI-protected login cache, bearer tokens moved from URLs to request headers,
live membership rechecks, fail-closed catalog tiers, explicit For Sale handling,
bounded and traversal-safe archive extraction, confirmed installer elevation,
protected recursive deletion, authenticated local IPC, redacted logs, dynamic
catalog/type search, stale-registry cleanup, writable state in LocalAppData, a
new recognizable light brain/exclamation icon, and a local-only verified build
pipeline that never kills unrelated Python processes.

Site files changed: `app-link.php`, `app-auth-check.php`, `download-api.php`, and
`tools/tools-list.json`. A 2026-07-11 live comparison showed production had 166
catalog entries while the local mirror had 154. The 12 live-only entries and two
live edits were merged into the local tree before adding the missing
`chromaspark` slug, so the local catalog now preserves all 166 entries.

Manual deploy bundle: `C:\Users\thena\Downloads\GGF-tray-v012-2026-07-11\`.
The public endpoints did not yet expose the new headers/behavior at verification
time, so upload that bundle rather than assuming auto-sync completed.

Remaining release blocker: the EXE is **not digitally signed**. The hash verifies
integrity, but Windows SmartScreen may warn until a trusted code-signing
certificate is used. Full browser-link + paid/free download testing still needs
a real member login after the four site files are live.

Self-reliance rule (corrected 2026-07-11): **use GitHub for what it's good at —
hosting the repo, clones, and publishing the release binaries — and push code +
releases up there for redundancy.** What we must NOT do is make anything
*GitHub-critical*: the site and the app must never depend on GitHub-hosted
resources at runtime, and the build / deploy / backup / recovery path must always
work end-to-end from **local source + local build tools + local backups** if
GitHub ever pulls the rug. So: mirror everything to GitHub (good redundancy), but
keep the local copy authoritative and fully independent. Same stance as Patreon —
use it, don't depend on it.

---

_Written 2026-07-02 after a full read-through of the tray (`C:\GGF\ggf-menu`) and
the live site code (`E:\Websites\GetGoingFast`). Goal: get the desktop tray app
logging in and downloading GGF tools again._

## ✅ STATUS: BUILT 2026-07-02 — pending deploy + live test

The plan below was **implemented** the same day. What's done:
- **Server (local, staged for deploy):** new `app-link.php` (Stripe-based token
  issuer replacing the dead `patreon-login.php`), `download-api.php` hardened
  (cookie path removed, 14-day token expiry), `app-auth-check.php` expiry aligned.
  Bundle: `C:\Users\thena\Downloads\GGF-tray-revival-2026-07-02\` (mirrors web root,
  has `_DEPLOY-README.txt` + revert notes). **Not deployed to live yet** (no local
  PHP; must be tested on live).
- **Tray (edited in place here in `C:\GGF\ggf-menu`):** `ggf_auth_token.py` +
  `ggf_auth.py` login URL → `app-link.php`, tier map fixed, de-Patreoned;
  `app_search.py` + `ggf-tray.py` wording. All 4 compile clean (`py_compile` OK).
  **Exe not rebuilt yet.**
- **Remaining (owner):** deploy the 3 site files, rebuild the exe, run the
  end-to-end login+download test in the deploy readme.

The sections below are the original spec/rationale — kept for reference and to
explain WHY each change was made.

---

## TL;DR — why it's broken (one root cause)

The tray logs in by opening a browser to **`https://getgoingfast.pro/patreon-login.php?app=tray&app_token=<token>`**. That PHP file **no longer exists on the site** (confirmed missing), and it was built on the **retired Patreon OAuth** system. It was the piece that *wrote* the token into `app_tokens.json`. With it gone:

- No token is ever minted → `app-auth-check.php?token=…` always returns `{"authenticated": false, "error": "Token not found"}`.
- Because auth never succeeds, the tool-download call (`download-api.php?slug=…&token=…`) never has a valid token either.

So the whole tray auth+download chain is dead from that single missing link. Everything else (catalog read, download endpoint, verify endpoint) still exists and basically works. **The fix is to replace the dead Patreon token-writer with a new one built on the site's current Stripe membership login**, then point the tray at it.

---

## The exact tray ⇄ site contract (what talks to what)

| Step | Tray code | Site endpoint | Status |
|------|-----------|---------------|--------|
| 1. Start login | `ggf_auth_token.py:116` `login()` → opens browser | `patreon-login.php?app=tray&app_token=<tok>` | **MISSING — the break** |
| 2. Poll for validation | `ggf_auth_token.py:61` `check_token()` | `app-auth-check.php?token=<tok>` | Exists, works (reads `app_tokens.json`) |
| 3. Download a tool | `app_search.py:561` | `download-api.php?slug=<slug>&token=<tok>` | Exists; token path works, has a weak cookie path to remove |
| 4. Read catalog | `app_search.py:474` | `tools/tools-list.json` | Exists, works |

Token format the tray generates: `ggf_tray_` + `secrets.token_urlsafe(32)` (256-bit, good). Site regex validates `^ggf_tray_[A-Za-z0-9_-]{24,}$`.

`app_tokens.json` record shape the writer must produce (from what the readers expect):
```json
{ "ggf_tray_xx…": { "tier": "farm-hand", "name": "Jim Day", "user_id": "…", "created": 1779089826, "expires": 1779694626 } }
```
`app-auth-check.php` reads `tier`/`name`; `download-api.php` reads `tier` and checks it against the tool's required tier from `tools-list.json`.

Note: `ggf_auth.py` and `ggf_auth_token.py` are **byte-identical**; the tray imports `ggf_auth_token`. Consider deleting one to avoid drift.

---

## Secondary issues to fix while you're in there

1. **Session dies after 24h.** `app-auth-check.php:56` expires a token 24h after `created`, but the tray caches for 14 days and re-verifies hourly — so the user gets logged out after a day. Make the server honor `token_data['expires']` (14 days) instead of a hardcoded 86400.
2. **`download-api.php` weak cookie path.** Its "Method 2" trusts the browser `ggf_auth` cookie's *tier claim* with no DB re-check (a cancelled member with a still-valid 30-day cookie could pull tier files). The website does NOT use `download-api.php` at all (it uses `/wp-json/ggf/v1/get-download`), and the tray uses the *token* path — so the cookie path can be removed entirely. Keep the token path.
3. **Patreon wording everywhere** (`app_search.py:555` "Click 'Login with Patreon'", tray auth labels, `ggf_auth*.py` docstrings/prints). Rename to "Login to GGF". This also matches the site's terminology policy (de-Patreon the brand).
4. **Tier map mismatch.** `ggf_auth_token.py:180` `has_tier_access()` uses `{free, prairie-dog, premium}` but the real tiers are `{free, prairie-dog, farm-hand, rancher, gunslinger}` (`format_tier_name` already lists them). Fix the levels dict so gating is correct.

---

## The fix — Part A: SERVER (`E:\Websites\GetGoingFast`)

> Hard rules: never break the site's Stripe checkout or the website download buttons.
> New code must be **additive + isolated + fail-closed**. There is **no local PHP
> runtime** — test on the live server (or a staging subfolder). Deploy via FTP;
> never upload `wp-config.php`.

### A1. New token-issuer endpoint (replaces `patreon-login.php`)

Create a first-party page, e.g. **`app-link.php`** at the web root. Reuse the
EXISTING Stripe membership auth — do not resurrect Patreon.

Flow:
1. `GET /app-link.php?app_token=ggf_tray_…` (accept the old `&app=tray` too, ignore it).
2. Validate the token format (`^ggf_tray_[A-Za-z0-9_-]{24,}$`); reject otherwise.
3. `require_once wp-load.php` (same as `tool-purchase.php` does) so the membership
   functions are available.
4. Identify the member from the existing signed `ggf_auth` cookie via
   `ggf_downloads_authenticated_member()`. If not logged in, redirect to
   `/member-login.html?return=<url-encoded self, token preserved>` — this reuses the
   working Stripe email-link / email-code login. After login the member lands back here.
5. Render a simple confirm page: "Link the GGF desktop app to this account?" with a
   **POST** button (so a hostile page can't silently link a token via a bare GET).
6. On POST (with a nonce/confirmation): look up the member's **real** tier from the
   membership DB (`ggf_memberships_get_active_by_email($cookie['email'])`), then write
   `app_tokens.json[$token] = ['tier'=>$realTier, 'name'=>$displayName, 'user_id'=>…,
   'created'=>time(), 'expires'=>time()+14*24*3600]` using `LOCK_EX`. Only write for an
   ACTIVE membership; free/none still writes tier `free` (tray shows free features).
7. Show "Done — return to the app." The tray's poll picks it up within ~2s.

Fail closed: no valid member session ⇒ never write a token.

### A2. Harden `download-api.php`
- **Remove Method 2** (the cookie tier path, ~lines 64-78 and the cookie block).
  Keep Method 1 (app_token) only. The website doesn't use this file; the tray only
  uses the token path.
- Keep the existing slug regex + `private/files/` containment (already safe).
- Optional but better: store the member email in the token record and re-check the
  live tier here at download time, so a downgrade/cancel takes effect immediately.

### A3. Align `app-auth-check.php` token lifetime
- Replace the hardcoded `created + 86400` expiry check with the token's own
  `expires` field (14 days), matching the issuer and the tray's cache.
- (Optional) tighten `Access-Control-Allow-Origin: *` — it's a read-only "is this
  token valid" check but it returns tier/name; low risk since it requires knowing a
  valid token, but worth noting.

### A4. `app_tokens.json` hygiene
- It's already web-blocked (root `.htaccess` denies `app_tokens.json` + a new backup
  rule). Keep it that way. A DB table would be more robust than a flat file long-term,
  but the flat file with `LOCK_EX` is acceptable for the current scale.

---

## The fix — Part B: TRAY (`C:\GGF\ggf-menu`)

1. `ggf_auth_token.py:21` (and the identical `ggf_auth.py`): change
   `self.login_url` from `.../patreon-login.php` to `.../app-link.php`. The
   `login()` method already appends `?app=tray&app_token=<token>` — the new endpoint
   accepts that.
2. `ggf_auth_token.py:180` `has_tier_access()`: fix the tier levels to
   `{free:0, prairie-dog:1, farm-hand:2, rancher:3, gunslinger:4}`.
3. De-Patreon the user-facing strings (`app_search.py:555`, tray menu auth label
   `ggf-tray.py:857`, `ggf_auth*.py` docstrings/prints) → "Login to GGF".
4. (Optional) delete the duplicate `ggf_auth.py` (keep `ggf_auth_token.py`).
5. Rebuild the exe: `build-ggf-tray.bat` (or `py-build.bat`) using
   `GGF-Tray-OneFile.spec`. Deps in `requirements.txt` (PyQt6, pystray, yt-dlp,
   Pillow, psutil, certifi, imageio-ffmpeg, numpy, pyaudiowpatch).

---

## End-to-end test plan (needs the live site + a test member)

1. Deploy `app-link.php` + hardened `download-api.php` + `app-auth-check.php` to live.
2. Run the tray from source: `python ggf-tray.py`. Click **Login** → browser opens
   `app-link.php?app_token=…` → log in as a **test member** (email link) → click
   **Link app** → the tray poll should flip to authenticated and show the right tier.
3. In the app-search window, download a tool the member's tier grants → file downloads.
   Try a tool ABOVE their tier → expect 403 "higher membership tier".
4. Log out / use a free (non-member) account → downloads for paid tools denied.
5. Rebuild the exe and repeat steps 2-3 with the built binary.

## Gotchas / constraints (read before touching anything)
- **Do not** change the website's Stripe checkout or the `/wp-json/ggf/v1/get-download`
  button flow. This work is orthogonal — a separate app auth path.
- No local PHP; test PHP on the live server (or a `/staging/` subfolder first).
- Deploy via FTP mirroring the web root; never upload `wp-config.php`.
- Keep `app_tokens.json` web-blocked (it already is).
- Match the site terminology policy: no "Patreon" in user-facing copy.

## Files touched (summary)
- **New:** `app-link.php` (site root).
- **Edit:** `download-api.php`, `app-auth-check.php` (site root).
- **Edit:** `ggf_auth_token.py`, `ggf_auth.py`, `app_search.py`, `ggf-tray.py` (tray).
- **Unchanged/works:** `tools/tools-list.json`, the Stripe membership plugin, the
  website download buttons.
