"""
Safely add a Divar routing rule to FlyFrog Happ.

Why this exists
---------------
`divar.ir` is SNI-filtered on some networks. Happ routes `.ir` domains
`direct`, so Divar traffic bypasses the tunnel, reaches the ISP unencrypted,
and is dropped -> ConnectTimeout. A fetch relay confirms divar.ir itself is
reachable from outside the country, so the site is fine; only the route is wrong.

This tool adds a rule so Divar rides the tunnel instead:

    {"type": "field", "domain": ["divar.ir"], "outboundTag": "proxy"}

That rule must come BEFORE any geoip/geosite:"ir" -> direct rule, because
xray evaluates rules top-down and stops at the first match.

Safety
------
* Refuses to write unless you pass --apply (dry-run by default).
* Timestamped backup of routing.json next to the original.
* Validates that the result is valid JSON and that a routing profile was found.
* Never touches subs.db or config.json.
* --rollback restores the newest backup.
* Happ must be CLOSED while applying, or it will overwrite the file on exit.

Usage
-----
    python tools/happ_routing.py            # dry run, prints what would change
    python tools/happ_routing.py --apply    # back up + write
    python tools/happ_routing.py --rollback # undo
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROUTING_JSON = Path(os.environ.get("LOCALAPPDATA", "")) / "Happ" / "routing.json"

DIVAR_RULE = {"type": "field", "domain": ["divar.ir"], "outboundTag": "proxy"}
BACKUP_SUFFIX = ".bak.{ts}"


def log(msg: str) -> None:
    print(msg, flush=True)


def is_happ_running() -> bool:
    """Happ rewrites routing.json when it exits, so it must not be running."""
    if sys.platform != "win32":
        return False
    try:
        import subprocess
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Happ.exe"],
                             capture_output=True, text=True, timeout=10).stdout
        return "Happ.exe" in out
    except Exception:
        return False


def backup(path: Path) -> Path:
    ts = time.strftime("%Y%m%d-%H%M%S")
    dest = path.with_name(path.name + BACKUP_SUFFIX.format(ts=ts))
    shutil.copy2(path, dest)
    log(f"  backup -> {dest}")
    return dest


def already_present(cfg: dict) -> bool:
    for profile in cfg.get("routings") or []:
        for rule in (profile.get("routing", profile).get("rules") or []):
            if DIVAR_RULE in [rule] or (
                    rule.get("outboundTag") == "proxy"
                    and "divar.ir" in (rule.get("domain") or [])):
                return True
    return False


def _is_ir_direct(rule: dict) -> bool:
    """True if this rule sends Iranian traffic out the `direct` (un-tunnelled) path."""
    if rule.get("outboundTag") != "direct":
        return False
    values = []
    for key in ("geoip", "geosite", "domain", "ip"):
        values += [str(x).strip().lower() for x in (rule.get(key) or [])]
    return any(v in ("ir", "geoip:ir", "geosite:ir", "category-ir",
                     "category-ir!", "geolocation-ir") for v in values)


def _first_ir_direct_index(rules: list) -> int | None:
    for ri, rule in enumerate(rules):
        if isinstance(rule, dict) and _is_ir_direct(rule):
            return ri
    return None


def apply_rule(cfg: dict) -> tuple[dict, str]:
    """Insert DIVAR_RULE into the active profile, ahead of any .ir direct rule."""
    cfg = json.loads(json.dumps(cfg))                     # deep copy
    profiles = cfg.get("routings") or []
    if not profiles:
        raise SystemExit(
            "No routing profiles in routing.json ('routings' is empty).\n"
            "Happ stores profiles per-subscription and yours has none, so there is\n"
            "nothing to prepend to. Create a routing profile in the Happ UI first,\n"
            "or use a proxy that exits abroad via DIVAR_PROXIES.")

    active = cfg.get("activeRoutingName") or ""
    target = None
    for profile in profiles:
        if profile.get("name") == active:
            target = profile
            break
    if target is None:
        target = profiles[0]

    routing = target.get("routing")
    if not isinstance(routing, dict):
        routing = {"domainStrategy": "AsIs", "rules": []}
        target["routing"] = routing

    rules = routing.setdefault("rules", [])
    # Insert ahead of the first rule that would send .ir traffic direct.
    # Happ writes these as {"geoip": ["ir"]} or {"geosite": ["category-ir"]},
    # and subscription profiles often use "geoip:ir" / "geosite:ir" strings.
    before = _first_ir_direct_index(rules)
    rules.insert(before if before is not None else 0, dict(DIVAR_RULE))
    where = f"before rule #{before}" if before is not None else "at the top (index 0)"
    return cfg, where
    rules.insert(before if before is not None else 0, dict(DIVAR_RULE))
    where = f"before rule #{before}" if before is not None else "at the top (index 0)"
    return cfg, where


def rollback() -> int:
    backups = sorted(ROUTING_JSON.parent.glob(ROUTING_JSON.name + ".bak.*"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    if not backups:
        log("No backups found.")
        return 1
    src = backups[0]
    log(f"Restoring {src} -> {ROUTING_JSON}")
    shutil.copy2(src, ROUTING_JSON)
    log("Done. Restart Happ to pick it up.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="actually write the change (default: dry run)")
    ap.add_argument("--rollback", action="store_true",
                    help="restore the newest backup and exit")
    args = ap.parse_args()

    if args.rollback:
        return rollback()

    if not ROUTING_JSON.exists():
        log(f"Not found: {ROUTING_JSON}")
        return 1

    cfg = json.loads(ROUTING_JSON.read_text(encoding="utf-8"))
    log(f"routing.json : {ROUTING_JSON}")
    log(f"profiles     : {len(cfg.get('routings') or [])}"
        f"   active: {cfg.get('activeRoutingName') or '(none)'}")

    if already_present(cfg):
        log("\nA divar -> proxy rule is already present. Nothing to do.")
        return 0

    if is_happ_running():
        log("\nWARNING: Happ.exe is RUNNING. It rewrites routing.json on exit and")
        log("         will overwrite this change. Close Happ (disconnect the VPN")
        log("         first), re-run, then restart it.")

    try:
        new_cfg, where = apply_rule(cfg)
    except SystemExit as exc:
        log(f"\n{exc}")
        return 1

    profiles = new_cfg.get("routings") or []
    active = new_cfg.get("activeRoutingName") or ""
    target = next((p for p in profiles if p.get("name") == active), profiles[0])
    rules = (target.get("routing") or target).get("rules") or []
    log(f"\nWould insert {json.dumps(DIVAR_RULE)} {where}")
    log("New rule order (first 6):")
    for i, r in enumerate(rules[:6]):
        tag = r.get("outboundTag")
        marker = "  <== inserted" if r == DIVAR_RULE else ""
        log(f"  {i}. outboundTag={tag}{marker}")

    if not args.apply:
        log("\nDry run. Re-run with --apply to back up and write.")
        return 0

    if is_happ_running():
        log("\nRefusing to write while Happ is running. Close it first.")
        return 1

    backup(ROUTING_JSON)
    ROUTING_JSON.write_text(json.dumps(new_cfg, indent=4), encoding="utf-8")
    # verify we can read back valid JSON with the rule present
    check = json.loads(ROUTING_JSON.read_text(encoding="utf-8"))
    if not already_present(check):
        log("Verification FAILED - rule missing after write. Restoring backup.")
        rollback()
        return 1
    log("Written and verified.")
    log("Restart Happ, then run:  python main.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
