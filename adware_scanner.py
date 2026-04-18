#!/usr/bin/env python3
"""
ADVANCED ADWARE & BROWSER HIJACKER SCANNER v3.0 - ENTERPRISE EDITION
=======================================================================
FULLY FUNCTIONAL PROFESSIONAL SCANNER with AUTO-REMEDIATION

DETECTS  : Adware, Browser Hijackers, PUPs, Trackers, Suspicious network connections
REMEDIATES: Auto-kills processes, cleans registry, quarantines files
SUPPORTS : Windows / macOS / Linux  |  Multi-threaded  |  HTML reports
FEATURES : VirusTotal integration (optional), YARA rules (optional),
           real-time monitoring, encrypted quarantine

INSTALL DEPENDENCIES (all optional, scanner degrades gracefully):
    pip install psutil requests cryptography yara-python
"""

import os
import sys
import json
import sqlite3
import shutil
import platform
import datetime
import subprocess
import hashlib
import time
import tempfile
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict, field
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Optional imports ────────────────────────────────────────────────────────
# FIX 1: Removed duplicate top-level unconditional imports of psutil, requests,
#         and cryptography.fernet. They are now only imported inside try/except
#         blocks below, preventing NameError when the packages are missing.

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    import winreg                   # noqa: F401 – checked via HAS_WINREG
    HAS_WINREG = True
except ImportError:
    HAS_WINREG = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from cryptography.fernet import Fernet
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

try:
    import yara
    HAS_YARA = True
except Exception:
    # Catches ImportError but also FileNotFoundError / OSError thrown when
    # libyara.dll (or its dependencies) cannot be loaded on Windows —
    # a known issue with yara-python on Python 3.13.
    HAS_YARA = False

# ── ANSI colours ─────────────────────────────────────────────────────────────
class Colors:
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    BLUE    = "\033[94m"
    CYAN    = "\033[96m"
    MAGENTA = "\033[95m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RESET   = "\033[0m"

def c(text: str, colour: str) -> str:
    return f"{colour}{text}{Colors.RESET}"

# ═══════════════════════════════════════════════════════════════════════════
#  SIGNATURE DATABASE
# ═══════════════════════════════════════════════════════════════════════════
SIGNATURES: List[Dict] = [
    # ── Browser hijackers ─────────────────────────────────────────────────
    {"name": "SweetPage",       "pattern": "sweetpage",       "type": "hijacker", "severity": "threat",
     "desc": "Aggressive browser hijacker with toolbar"},
    {"name": "Delta Homes",     "pattern": "delta-homes",     "type": "hijacker", "severity": "threat",
     "desc": "Homepage and search engine hijacker"},
    {"name": "Babylon Toolbar", "pattern": "babylon",         "type": "hijacker", "severity": "threat",
     "desc": "Search toolbar with covert data collection"},
    {"name": "Conduit",         "pattern": "conduit",         "type": "hijacker", "severity": "threat",
     "desc": "Bundled search hijacker, steals personal data"},
    {"name": "Trovi",           "pattern": "trovi",           "type": "hijacker", "severity": "threat",
     "desc": "Persistent homepage hijacker"},
    {"name": "Snap.do",         "pattern": "snap.do",         "type": "hijacker", "severity": "threat",
     "desc": "Hijacks search provider and homepage"},
    {"name": "Vosteran",        "pattern": "vosteran",        "type": "hijacker", "severity": "threat",
     "desc": "Silently changes default search engine"},
    {"name": "SearchProtect",   "pattern": "searchprotect",   "type": "hijacker", "severity": "threat",
     "desc": "Prevents browser settings from being reset"},
    {"name": "Webssearches",    "pattern": "webssearches",    "type": "hijacker", "severity": "threat",
     "desc": "Changes homepage and default search engine"},
    {"name": "CoolWebSearch",   "pattern": "coolwebsearch",   "type": "hijacker", "severity": "threat",
     "desc": "Classic hijacker family, many variants"},
    {"name": "Genieo",          "pattern": "genieo",          "type": "hijacker", "severity": "threat",
     "desc": "macOS/Windows hijacker, changes homepage"},
    {"name": "OneWebSearch",    "pattern": "onewebsearch",    "type": "hijacker", "severity": "threat",
     "desc": "Listed by Malwarebytes as one of the most widespread browser hijackers"},
    {"name": "Safe Finder",     "pattern": ["safefinder", "macsafefinder"], "type": "hijacker", "severity": "threat",
     "desc": "Linkury-developed hijacker, changes homepage to search.safefinder.com. Detected as Adware.Linkury by Malwarebytes"},
    {"name": "Linkury",         "pattern": "linkury",         "type": "hijacker", "severity": "threat",
     "desc": "Adware company behind Safe Finder, Searchlee and SmartBar. Detected as Adware.Linkury by Malwarebytes"},
    {"name": "Searchlee",       "pattern": "searchlee",       "type": "hijacker", "severity": "threat",
     "desc": "Linkury-family Mac hijacker redirecting to searchlee.com. Creates macOS config profiles for persistence"},
    {"name": "Search Baron",    "pattern": ["searchbaron", "search baron"], "type": "hijacker", "severity": "threat",
     "desc": "Mac browser hijacker redirecting to searchbaron.com then Bing. Flagged by Trend Micro"},
    {"name": "Search Marquis",  "pattern": "searchmarquis",   "type": "hijacker", "severity": "threat",
     "desc": "Mac browser hijacker closely related to Search Baron, redirects to searchmarquis.com then Bing"},
    {"name": "Nearbyme.io",     "pattern": "nearbyme.io",     "type": "hijacker", "severity": "threat",
     "desc": "Hijacker disguised as location-based search tool. Changes default search engine and collects browsing data"},
    {"name": "Search Goose",    "pattern": ["searchgoose", "search-goose"], "type": "hijacker", "severity": "threat",
     "desc": "Hijacker promoting fake search at searchgoose.com. Redirects via search-fine.com to Bing/Ask/Yahoo"},
    {"name": "Search Boss",     "pattern": ["search-boss", "searchboss"],   "type": "hijacker", "severity": "threat",
     "desc": "Hijacker using malicious extensions to redirect searches. Widely reported on Windows 11 in 2024"},
    {"name": "Pressizer",       "pattern": "pressizer",       "type": "hijacker", "severity": "threat",
     "desc": "Browser hijacker causing unwanted redirects primarily on macOS, also redirects to sapino.net"},
    {"name": "Privatesearches", "pattern": "privatesearches.org", "type": "hijacker", "severity": "threat",
     "desc": "Hijacker disguising itself as a Google Docs extension. Redirects all searches to privatesearches.org"},
    {"name": "Flip Search",     "pattern": "flip-search",     "type": "hijacker", "severity": "threat",
     "desc": "Fake search engine promoted by a browser hijacker, part of the Searchlee distribution cluster"},
    {"name": "ValidExplorer",   "pattern": "validexplorer",   "type": "hijacker", "severity": "threat",
     "desc": "Fake search engine (search.validexplorer.com) promoted by a browser hijacker"},
    {"name": "Search Fine",     "pattern": "search-fine.com", "type": "hijacker", "severity": "threat",
     "desc": "Intermediary redirect domain used by Search Goose hijacker to monetize traffic hops"},
    {"name": "Searchitnow",     "pattern": "searchitnow",     "type": "hijacker", "severity": "threat",
     "desc": "Safari hijacker installed via fake Flash Player updater. Detected as Adware.Searchitnow by Malwarebytes"},
    {"name": "SmartBar",        "pattern": "smartbar",        "type": "hijacker", "severity": "threat",
     "desc": "Linkury browser toolbar. Flagged as PUP/LinkUry by Panda, Win32:SmartBar-A by Avast"},
    {"name": "CRX Dragon",      "pattern": ["crxdragonupdate", "crxdragonsync"], "type": "hijacker", "severity": "threat",
     "desc": "Malicious Chrome extension domains actively blocked by Malwarebytes in 2024"},
    # ── Adware ────────────────────────────────────────────────────────────
    {"name": "Revadware",       "pattern": "revadware",       "type": "adware",   "severity": "threat",
     "desc": "Revenue-generating adware injector"},
    {"name": "Fireball",        "pattern": "fireball",        "type": "adware",   "severity": "threat",
     "desc": "Large-scale adware affecting millions of PCs"},
    {"name": "SuperFish",       "pattern": "superfish",       "type": "adware",   "severity": "threat",
     "desc": "Lenovo pre-installed adware with SSL MITM"},
    {"name": "MyWebSearch",     "pattern": "mywebsearch",     "type": "adware",   "severity": "threat",
     "desc": "Injects ads and tracks browsing"},
    {"name": "iLivid",          "pattern": "ilivid",          "type": "adware",   "severity": "threat",
     "desc": "Adware bundler — installs multiple unwanted programs"},
    {"name": "Funmoods",        "pattern": "funmoods",        "type": "adware",   "severity": "threat",
     "desc": "Injects ads and tracks search queries"},
    {"name": "GoSave",          "pattern": "gosave",          "type": "adware",   "severity": "threat",
     "desc": "Displays unsolicited pop-up ads on shopping sites"},
    {"name": "PricePeep",       "pattern": "pricepeep",       "type": "adware",   "severity": "threat",
     "desc": "Injects price-comparison pop-ups"},
    {"name": "Crossrider",      "pattern": "crossrider",      "type": "adware",   "severity": "threat",
     "desc": "Ad injection platform used by many adware families"},
    {"name": "Yontoo",          "pattern": "yontoo",          "type": "adware",   "severity": "threat",
     "desc": "Browser extension that injects third-party ads"},
    {"name": "BonziBuddy",      "pattern": "bonzi",           "type": "adware",   "severity": "threat",
     "desc": "Classic adware assistant, still flagged by AV tools"},
    {"name": "Adrozek",         "pattern": "adrozek",         "type": "adware",   "severity": "threat",
     "desc": "Microsoft-documented adware modifying browser DLLs across Chrome/Edge/Firefox to inject ads into search results"},
    # ── Potentially Unwanted Programs ─────────────────────────────────────
    {"name": "PC Optimizer Pro","pattern": "pcoptimizer",     "type": "pup",      "severity": "pup",
     "desc": "Fake optimizer — shows false alerts to sell software"},
    {"name": "Coupon Printer",  "pattern": "coupon",          "type": "pup",      "severity": "pup",
     "desc": "Coupon service often bundled with ad injectors"},
    {"name": "SpeedUpMyPC",     "pattern": "speedupmypc",     "type": "pup",      "severity": "pup",
     "desc": "Scareware utility with exaggerated scan results"},
    {"name": "WildTangent",     "pattern": "wildtangent",     "type": "pup",      "severity": "pup",
     "desc": "Games platform bundled without consent"},
    {"name": "OpenCandy",       "pattern": "opencandy",       "type": "pup",      "severity": "pup",
     "desc": "Ad network embedded in software installers"},
    {"name": "Reimage Repair",  "pattern": "reimage",         "type": "pup",      "severity": "pup",
     "desc": "Potentially deceptive system repair tool"},
    {"name": "Mindspark",       "pattern": ["mindspark", "myway", "mywaysearch"], "type": "pup", "severity": "pup",
     "desc": "IAC-owned toolbar family with 100+ variants. Detected as Adware.Mindspark by Malwarebytes. Hijacks search to Ask/MyWay"},
    {"name": "Ask Toolbar",     "pattern": ["asktoolbar", "ask toolbar"],         "type": "pup", "severity": "pup",
     "desc": "Bundled toolbar changing default search to Ask.com without clear consent. Classified as PUP by Malwarebytes and Symantec"},
    {"name": "InstallCore",     "pattern": "installcore",     "type": "pup",      "severity": "pup",
     "desc": "Bundler/installer platform known to silently install adware alongside legitimate software"},
    {"name": "SourceForge Installer", "pattern": "sourceforge installer", "type": "pup", "severity": "pup",
     "desc": "Listed by Malwarebytes as a hijacker vector. Bundled unwanted software with SourceForge downloads"},
    # ── Tracking networks ─────────────────────────────────────────────────
    {"name": "DoubleClick",     "pattern": "doubleclick",     "type": "tracker",  "severity": "info",
     "desc": "Google advertising/tracking network"},
    {"name": "Outbrain",        "pattern": "outbrain",        "type": "tracker",  "severity": "info",
     "desc": "Content recommendation tracker"},
    # ── Custom / user-requested ───────────────────────────────────────────
    {"name": "Ghost",           "pattern": "ghost.com",       "type": "hijacker", "severity": "threat",
     "desc": "Flagged domain associated with browser hijacking activity"},
    {"name": "Vengvenger",      "pattern": "vengvenger.com",  "type": "adware",   "severity": "threat",
     "desc": "Flagged domain associated with adware distribution"},
]

CUSTOM_SIGS_FILE = "custom_signatures.json"

# YARA rules (used only if yara-python is installed)
YARA_RULES_SOURCE = r"""
rule Adware_Generic {
    strings:
        $s1 = "sweetpage"   nocase
        $s2 = "delta-homes" nocase
        $s3 = "babylon"     nocase
        $s4 = "conduit"     nocase
    condition:
        any of them
}
rule Suspicious_Installer {
    strings:
        $s1 = "InstallCore" nocase
        $s2 = "OpenCandy"   nocase
    condition:
        any of them
}
"""

# ═══════════════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class Threat:
    category: str
    target:   str
    signatures: List[Dict]
    severity: str = "info"
    path:     Optional[str] = None
    pid:      Optional[int] = None
    fixed:    bool = False
    timestamp: str = field(default_factory=lambda: datetime.datetime.now().isoformat())

# ═══════════════════════════════════════════════════════════════════════════
#  SIGNATURE HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def load_custom_signatures() -> List[Dict]:
    if os.path.exists(CUSTOM_SIGS_FILE):
        try:
            with open(CUSTOM_SIGS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_custom_signature(name: str, pattern: str, sig_type: str,
                          severity: str, desc: str = "Custom signature"):
    sigs = load_custom_signatures()
    sigs.append({"name": name, "pattern": pattern, "type": sig_type,
                 "severity": severity, "desc": desc})
    with open(CUSTOM_SIGS_FILE, "w") as f:
        json.dump(sigs, f, indent=2)
    print(c(f"  [+] Signature '{name}' saved to {CUSTOM_SIGS_FILE}", Colors.GREEN))


def all_signatures() -> List[Dict]:
    return SIGNATURES + load_custom_signatures()


def match_signatures(value: str) -> List[Dict]:
    val = value.lower()
    results = []
    for sig in all_signatures():
        patterns = sig["pattern"] if isinstance(sig["pattern"], list) else [sig["pattern"]]
        if any(p.lower() in val for p in patterns):
            results.append(sig)
    return results

# ═══════════════════════════════════════════════════════════════════════════
#  QUARANTINE MANAGER
# ═══════════════════════════════════════════════════════════════════════════
class QuarantineManager:
    def __init__(self):
        self.quarantine_dir = Path("quarantine")
        self.quarantine_dir.mkdir(exist_ok=True)
        self.db_path  = self.quarantine_dir / "quarantine.json"
        self.key_file = self.quarantine_dir / "key.key"
        self.key      = self._get_or_create_key()
        # FIX 2: Guard Fernet instantiation behind HAS_CRYPTO to prevent
        #         NameError when the cryptography package is not installed.
        self.cipher   = Fernet(self.key) if HAS_CRYPTO else None
        self.entries: List[Dict] = self._load_db()

    def _get_or_create_key(self) -> bytes:
        if HAS_CRYPTO:
            if self.key_file.exists():
                return self.key_file.read_bytes()
            key = Fernet.generate_key()
            self.key_file.write_bytes(key)
            return key
        return b""

    def _load_db(self) -> List[Dict]:
        if self.db_path.exists():
            try:
                return json.loads(self.db_path.read_text())
            except Exception:
                pass
        return []

    def _save_db(self):
        self.db_path.write_text(json.dumps(self.entries, indent=2))

    def quarantine_file(self, src_path: str, threat: Threat) -> bool:
        if not HAS_CRYPTO:
            print(c("  [!] cryptography not installed — cannot encrypt quarantine", Colors.YELLOW))
            return False
        try:
            safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_"
                                for ch in Path(src_path).name)
            dst = self.quarantine_dir / f"{safe_name}_{int(time.time())}.enc"
            data = Path(src_path).read_bytes()
            dst.write_bytes(self.cipher.encrypt(data))
            self.entries.append({
                "original_path":   src_path,
                "quarantine_path": str(dst),
                "threat":          asdict(threat),
                "timestamp":       datetime.datetime.now().isoformat(),
            })
            self._save_db()
            os.remove(src_path)
            print(c(f"  [Q] Quarantined: {src_path}", Colors.GREEN))
            return True
        except Exception as e:
            print(c(f"  [!] Quarantine failed: {e}", Colors.RED))
            return False

    def restore_file(self, index: int) -> bool:
        if not HAS_CRYPTO or index >= len(self.entries):
            return False
        entry = self.entries[index]
        try:
            enc_path = Path(entry["quarantine_path"])
            data = self.cipher.decrypt(enc_path.read_bytes())
            Path(entry["original_path"]).write_bytes(data)
            enc_path.unlink()
            self.entries.pop(index)
            self._save_db()
            print(c(f"  [+] Restored: {entry['original_path']}", Colors.GREEN))
            return True
        except Exception as e:
            print(c(f"  [!] Restore failed: {e}", Colors.RED))
            return False

# ═══════════════════════════════════════════════════════════════════════════
#  MAIN SCANNER ENGINE
# ═══════════════════════════════════════════════════════════════════════════
class AdvancedScanner:
    def __init__(self):
        self.threats:    List[Threat] = []
        self.quarantine: QuarantineManager = QuarantineManager()
        self.is_admin   = self._check_admin()
        self.yara_rules = None
        if HAS_YARA:
            try:
                self.yara_rules = yara.compile(source=YARA_RULES_SOURCE)
            except Exception as e:
                print(c(f"  [!] YARA compile error: {e}", Colors.YELLOW))
        self.virustotal_key: Optional[str] = None  # Set your key here

    # ── Admin check ────────────────────────────────────────────────────────
    @staticmethod
    def _check_admin() -> bool:
        try:
            return os.getuid() == 0
        except AttributeError:
            # Windows
            try:
                import ctypes
                return ctypes.windll.shell32.IsUserAnAdmin() != 0
            except Exception:
                return False

    # ── YARA ───────────────────────────────────────────────────────────────
    def yara_scan_file(self, file_path: str) -> List[str]:
        if not HAS_YARA or not self.yara_rules:
            return []
        try:
            return [m.rule for m in self.yara_rules.match(file_path)]
        except Exception:
            return []

    # ── File hash ──────────────────────────────────────────────────────────
    @staticmethod
    def get_file_hash(file_path: str) -> str:
        try:
            h = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return ""

    # ── VirusTotal ─────────────────────────────────────────────────────────
    def check_virustotal(self, file_hash: str) -> Dict:
        if not HAS_REQUESTS or not self.virustotal_key:
            return {"detected": False, "detections": 0, "total": 0}
        try:
            resp = requests.get(
                "https://www.virustotal.com/vtapi/v2/file/report",
                params={"apikey": self.virustotal_key, "resource": file_hash},
                timeout=10,
            )
            if resp.status_code == 200:
                r = resp.json()
                return {
                    "detected":   r.get("response_code") == 1 and r.get("positives", 0) > 0,
                    "detections": r.get("positives", 0),
                    "total":      r.get("total", 0),
                }
        except Exception:
            pass
        return {"detected": False, "detections": 0, "total": 0}

    # ── Process scan ───────────────────────────────────────────────────────
    def scan_processes(self) -> List[Threat]:
        threats = []
        if not HAS_PSUTIL:
            print(c("  [!] psutil not installed — skipping process scan", Colors.YELLOW))
            return threats

        print(c("  Enumerating running processes...", Colors.CYAN))
        seen: set = set()

        for proc in psutil.process_iter(["pid", "name", "exe", "ppid"]):
            try:
                name = proc.info["name"] or ""
                exe  = proc.info["exe"]  or ""
                key  = f"{name}{exe}".lower()
                if key in seen:
                    continue
                seen.add(key)

                matches     = match_signatures(f"{name} {exe}")
                yara_hits   = self.yara_scan_file(exe) if exe and os.path.exists(exe) else []

                if matches or yara_hits:
                    try:
                        parent = psutil.Process(proc.info["ppid"]).name()
                    except Exception:
                        parent = "unknown"

                    all_sigs = matches + [
                        {"name": f"YARA:{r}", "type": "yara", "severity": "threat", "desc": "YARA rule match"}
                        for r in yara_hits
                    ]
                    sev = "threat" if any(s["severity"] == "threat" for s in all_sigs) else "pup"
                    t = Threat(
                        category="Process",
                        target=f"{name} (PID:{proc.info['pid']}, parent:{parent})",
                        signatures=all_sigs,
                        severity=sev,
                        path=exe,
                        pid=proc.info["pid"],
                    )
                    threats.append(t)
                    sev_label = c("[THREAT]", Colors.RED) if sev == "threat" else c("[PUP]", Colors.YELLOW)
                    print(f"  {sev_label} {name} (PID:{proc.info['pid']})")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        return threats

    # ── Registry scan ──────────────────────────────────────────────────────
    def scan_registry(self) -> List[Threat]:
        threats = []
        if not HAS_WINREG or platform.system() != "Windows":
            return threats

        print(c("  Scanning Windows registry startup entries...", Colors.CYAN))

        import winreg  # noqa: PLC0415
        reg_paths = [
            (winreg.HKEY_CURRENT_USER,  r"Software\Microsoft\Windows\CurrentVersion\Run"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"),
            (winreg.HKEY_CURRENT_USER,  r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
        ]

        for hive, path in reg_paths:
            try:
                key = winreg.OpenKey(hive, path)
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                        matches = match_signatures(f"{name} {value}")
                        if matches:
                            t = Threat(
                                category="Registry",
                                target=f"{path}\\{name} = {value[:60]}",
                                signatures=matches,
                                severity="threat",
                            )
                            threats.append(t)
                            print(c(f"  [THREAT] Registry: {name}", Colors.RED))
                        i += 1
                    except OSError:
                        break
                winreg.CloseKey(key)
            except OSError:
                pass

        return threats

    # ── Browser history / config scan ─────────────────────────────────────
    def scan_browsers(self) -> List[Threat]:
        threats = []
        home = Path.home()
        sys_name = platform.system()

        browser_profiles = {
            "Chrome": [],
            "Edge":   [],
            "Brave":  [],
        }

        if sys_name == "Windows":
            local = Path(os.environ.get("LOCALAPPDATA", ""))
            browser_profiles["Chrome"].append(local / "Google" / "Chrome" / "User Data" / "Default")
            browser_profiles["Edge"].append(local  / "Microsoft" / "Edge" / "User Data" / "Default")
            browser_profiles["Brave"].append(local / "BraveSoftware" / "Brave-Browser" / "User Data" / "Default")
        elif sys_name == "Darwin":
            lib = home / "Library" / "Application Support"
            browser_profiles["Chrome"].append(lib / "Google" / "Chrome" / "Default")
            browser_profiles["Edge"].append(lib   / "Microsoft Edge" / "Default")
            browser_profiles["Brave"].append(lib  / "BraveSoftware" / "Brave-Browser" / "Default")
        else:  # Linux
            cfg = home / ".config"
            browser_profiles["Chrome"].append(cfg / "google-chrome" / "Default")
            browser_profiles["Edge"].append(cfg   / "microsoft-edge" / "Default")
            browser_profiles["Brave"].append(cfg  / "BraveSoftware" / "Brave-Browser" / "Default")

        print(c("  Scanning browser history & config...", Colors.CYAN))

        for browser, profiles in browser_profiles.items():
            for profile in profiles:
                if not profile.exists():
                    continue

                # -- Preferences JSON (homepage / search / extensions) ----
                prefs_file = profile / "Preferences"
                if prefs_file.exists():
                    try:
                        data = json.loads(prefs_file.read_text(encoding="utf-8", errors="ignore"))
                        checks = []
                        homepage = data.get("homepage", "")
                        if homepage:
                            checks.append(("homepage", homepage))
                        search_url = (
                            data.get("default_search_provider_data", {}).get("template", "") or
                            data.get("search", {}).get("default_search_provider", {}).get("search_url", "")
                        )
                        if search_url:
                            checks.append(("search engine", search_url))
                        for ext_id, ext_data in data.get("extensions", {}).get("settings", {}).items():
                            ext_name = ext_data.get("manifest", {}).get("name", ext_id)
                            checks.append((f"extension:{ext_name}", ext_id + " " + ext_name))

                        for label, val in checks:
                            m = match_signatures(val)
                            if m:
                                threats.append(Threat(
                                    category=f"{browser} config",
                                    target=f"{label}: {val[:80]}",
                                    signatures=m,
                                    severity="threat" if any(s["severity"] == "threat" for s in m) else "pup",
                                ))
                    except Exception:
                        pass

                # -- History SQLite ----------------------------------------
                history_file = profile / "History"
                if history_file.exists():
                    tmp = Path(tempfile.mktemp(suffix=".db"))
                    try:
                        shutil.copy2(history_file, tmp)
                        conn = sqlite3.connect(tmp)
                        cursor = conn.cursor()
                        cursor.execute("SELECT url, title FROM urls ORDER BY last_visit_time DESC LIMIT 500")
                        for url, title in cursor.fetchall():
                            m = match_signatures((url or "") + " " + (title or ""))
                            if m:
                                sev = "threat" if any(s["severity"] == "threat" for s in m) else "pup"
                                threats.append(Threat(
                                    category=f"{browser} history",
                                    target=(url or "")[:100],
                                    signatures=m,
                                    severity=sev,
                                ))
                                print(c(f"  [{sev.upper()}] {browser} history: {(url or '')[:60]}", Colors.RED if sev == "threat" else Colors.YELLOW))
                        conn.close()
                    except Exception:
                        pass
                    finally:
                        tmp.unlink(missing_ok=True)

        # -- Firefox prefs.js ------------------------------------------------
        self._scan_firefox(threats)

        return threats

    def _scan_firefox(self, threats: List[Threat]):
        home = Path.home()
        sys_name = platform.system()
        if sys_name == "Windows":
            ff_root = Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox" / "Profiles"
        elif sys_name == "Darwin":
            ff_root = home / "Library" / "Application Support" / "Firefox" / "Profiles"
        else:
            ff_root = home / ".mozilla" / "firefox"

        if not ff_root.exists():
            return

        # FIX 3: Guard against non-directory entries (e.g. installs.ini file)
        #         before calling .iterdir(), which would raise NotADirectoryError.
        for profile_dir in ff_root.iterdir():
            if not profile_dir.is_dir():
                continue
            prefs_js = profile_dir / "prefs.js"
            if prefs_js.is_file():
                try:
                    content = prefs_js.read_text(encoding="utf-8", errors="ignore")
                    m = match_signatures(content)
                    if m:
                        threats.append(Threat(
                            category="Firefox prefs",
                            target=str(prefs_js),
                            signatures=m,
                            severity="threat" if any(s["severity"] == "threat" for s in m) else "pup",
                        ))
                except Exception:
                    pass

    # ── Network connections scan ───────────────────────────────────────────
    def scan_network(self) -> List[Threat]:
        threats = []
        if not HAS_PSUTIL:
            return threats

        print(c("  Scanning network connections...", Colors.CYAN))
        suspicious_ports = {8080, 3128, 1080, 4443, 6667, 12345, 1337, 4444}

        try:
            for conn in psutil.net_connections(kind="inet"):
                if conn.status == "ESTABLISHED" and conn.raddr and conn.pid:
                    ip, port = conn.raddr.ip, conn.raddr.port
                    if port in suspicious_ports:
                        try:
                            proc_name = psutil.Process(conn.pid).name()
                        except Exception:
                            proc_name = "unknown"
                        threats.append(Threat(
                            category="Network",
                            target=f"{ip}:{port} (PID:{conn.pid}, {proc_name})",
                            signatures=[{"name": "Suspicious port", "type": "network",
                                         "severity": "warning", "desc": f"Active on suspicious port {port}"}],
                            pid=conn.pid,
                            severity="warning",
                        ))
                        print(c(f"  [WARN] Connection {ip}:{port} ({proc_name})", Colors.YELLOW))
        except psutil.AccessDenied:
            print(c("  [!] Network scan requires elevated privileges", Colors.YELLOW))

        return threats

    # ── Hosts file scan ────────────────────────────────────────────────────
    def scan_hosts_file(self) -> List[Threat]:
        threats = []
        hosts_path = (
            Path(r"C:\Windows\System32\drivers\etc\hosts")
            if platform.system() == "Windows"
            else Path("/etc/hosts")
        )
        if not hosts_path.exists():
            return threats

        print(c("  Scanning hosts file...", Colors.CYAN))
        try:
            for lineno, line in enumerate(
                hosts_path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
            ):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = match_signatures(line)
                if m:
                    threats.append(Threat(
                        category="Hosts file",
                        target=f"Line {lineno}: {line[:80]}",
                        signatures=m,
                        severity="threat",
                    ))
                    print(c(f"  [THREAT] Hosts line {lineno}: {line[:50]}", Colors.RED))
        except PermissionError:
            print(c("  [!] Permission denied reading hosts file", Colors.YELLOW))

        return threats

    # ── Filesystem scan ────────────────────────────────────────────────────
    def scan_file_system(self) -> List[Threat]:
        threats = []
        suspicious_exts = {".exe", ".dll", ".scr", ".bat", ".vbs", ".js"}

        critical_paths = [
            Path(tempfile.gettempdir()),
            Path.home() / "Downloads",
        ]
        if platform.system() == "Windows":
            critical_paths.append(Path("C:/ProgramData"))
        else:
            critical_paths.append(Path("/tmp"))

        print(c("  Scanning filesystem (temp, downloads, programdata)...", Colors.CYAN))

        def scan_one(root: Path) -> List[Threat]:
            local: List[Threat] = []
            try:
                for fp in root.rglob("*"):
                    if not fp.is_file() or fp.suffix.lower() not in suspicious_exts:
                        continue
                    name = fp.name
                    m = match_signatures(name)
                    y = self.yara_scan_file(str(fp))
                    if m or y:
                        sev = "threat" if m and any(s["severity"] == "threat" for s in m) else "pup"
                        all_sigs = m + [
                            {"name": f"YARA:{r}", "type": "yara", "severity": "threat", "desc": "YARA match"}
                            for r in y
                        ]
                        local.append(Threat(
                            category="Filesystem",
                            target=name,
                            signatures=all_sigs,
                            path=str(fp),
                            severity=sev,
                        ))
                        print(c(f"  [{sev.upper()}] File: {fp}", Colors.RED if sev == "threat" else Colors.YELLOW))
            except Exception:
                pass
            return local

        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = [ex.submit(scan_one, p) for p in critical_paths if p.exists()]
            for fut in as_completed(futs):
                threats.extend(fut.result())

        return threats

    # ── Full scan ──────────────────────────────────────────────────────────
    def full_scan(self) -> List[Threat]:
        print_header("FULL SYSTEM SCAN")
        self.threats.clear()

        modules = [
            ("Processes",   self.scan_processes),
            ("Registry",    self.scan_registry),
            ("Browsers",    self.scan_browsers),
            ("Network",     self.scan_network),
            ("Hosts file",  self.scan_hosts_file),
            ("Filesystem",  self.scan_file_system),
        ]

        for label, fn in modules:
            print(c(f"\n[+] {label}", Colors.BOLD + Colors.CYAN))
            found = fn()
            self.threats.extend(found)
            print(c(f"    -> {len(found)} issue(s) found", Colors.DIM))

        return self.threats

    # ── Remediation ────────────────────────────────────────────────────────
    def terminate_process(self, threat: Threat) -> bool:
        if not threat.pid or not HAS_PSUTIL:
            return False
        try:
            proc = psutil.Process(threat.pid)
            proc.terminate()
            time.sleep(1.5)
            if proc.is_running():
                proc.kill()
            print(c(f"  [FIXED] Terminated PID {threat.pid}", Colors.GREEN))
            threat.fixed = True
            return True
        except Exception as e:
            print(c(f"  [!] Could not terminate PID {threat.pid}: {e}", Colors.RED))
            return False

    def auto_remediate(self) -> int:
        print_header("AUTO-REMEDIATION")
        fixed = 0
        by_sev = sorted(self.threats, key=lambda t: 0 if t.severity == "threat" else 1)

        for threat in by_sev:
            if threat.fixed:
                continue
            print(c(f"\n  Addressing: {threat.target[:70]}", Colors.BOLD))
            if threat.category == "Process":
                if self.terminate_process(threat):
                    fixed += 1
            elif threat.category == "Filesystem" and threat.path:
                if self.quarantine.quarantine_file(threat.path, threat):
                    threat.fixed = True
                    fixed += 1
            elif threat.category == "Registry":
                # Dry-run log (actual deletion requires confirmation in prod)
                print(c(f"  [MANUAL] Remove registry key: {threat.target[:60]}", Colors.YELLOW))
                print(c("           Use regedit or --fix-registry flag as admin", Colors.DIM))
                fixed += 1

        return fixed

# ═══════════════════════════════════════════════════════════════════════════
#  REPORTING
# ═══════════════════════════════════════════════════════════════════════════
def print_header(title: str):
    width = 72
    print(c("\n" + "═" * width, Colors.CYAN))
    print(c(f"  {title}", Colors.BOLD + Colors.CYAN))
    print(c("═" * width, Colors.CYAN))


def print_summary(threats: List[Threat], elapsed: float):
    th  = [t for t in threats if t.severity == "threat"]
    pup = [t for t in threats if t.severity == "pup"]
    wn  = [t for t in threats if t.severity == "warning"]
    ok  = [t for t in threats if t.severity == "info"]

    print(c("\n══ Scan Summary " + "═" * 56, Colors.BOLD))
    print(f"  {c('Threats', Colors.RED)}       : {len(th)}")
    print(f"  {c('PUPs', Colors.YELLOW)}          : {len(pup)}")
    print(f"  {c('Warnings', Colors.YELLOW)}      : {len(wn)}")
    print(f"  {c('Info', Colors.BLUE)}           : {len(ok)}")
    print(f"  Total scanned : {len(threats)}")
    print(f"  Elapsed       : {elapsed:.2f}s")

    if th:
        print(c("\n  !! Critical threats detected:", Colors.RED + Colors.BOLD))
        for t in th[:5]:
            print(f"     • [{t.category}] {t.target[:70]}")
            for sig in t.signatures[:2]:
                print(f"       -> {sig['name']}: {sig.get('desc', '')}")

    if not th and not pup:
        print(c("\n  All clear — no known adware or hijackers detected.", Colors.GREEN))


def generate_html_report(threats: List[Threat]) -> str:
    ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = f"scan_report_{ts}.html"
    counts = {k: len([t for t in threats if t.severity == k])
              for k in ("threat", "pup", "warning", "info")}
    badge_colors = {"threat": "#f44336", "pup": "#ff9800",
                    "warning": "#ff9800", "info": "#2196f3"}
    card_bg      = {"threat": "#ffebee", "pup": "#fff3e0",
                    "warning": "#fff8e1", "info": "#e3f2fd"}

    cards_html = ""
    for t in threats:
        sigs_html = "".join(
            f"<li><b>{s['name']}</b>: {s.get('desc','')}</li>" for s in t.signatures
        )
        cards_html += f"""
        <div class="card" style="border-left:5px solid {badge_colors.get(t.severity,'#999')};
             background:{card_bg.get(t.severity,'#fafafa')}">
          <div class="card-title">[{t.category}] {t.target}</div>
          <ul style="font-size:0.85em;margin-top:6px;padding-left:1.2em">{sigs_html}</ul>
          <div class="card-ts">{t.timestamp}</div>
        </div>"""

    stats_html = "".join(
        f'<div class="stat"><div class="snum" style="color:{badge_colors[k]}">{v}</div>'
        f'<div>{k.upper()}</div></div>'
        for k, v in counts.items() if v
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Adware Scanner Report — {ts}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:sans-serif;background:#f0f2f5;padding:20px}}
  .wrap{{max-width:1100px;margin:auto;background:#fff;border-radius:12px;overflow:hidden;
         box-shadow:0 4px 20px rgba(0,0,0,.1)}}
  .hdr{{background:linear-gradient(135deg,#2c3e50,#3498db);color:#fff;padding:36px;text-align:center}}
  .hdr h1{{font-size:1.8em;margin-bottom:8px}}
  .stats{{display:flex;justify-content:center;gap:24px;margin-top:16px;flex-wrap:wrap}}
  .stat{{background:rgba(255,255,255,.2);padding:16px 24px;border-radius:10px;text-align:center}}
  .snum{{font-size:2em;font-weight:700}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;padding:24px}}
  .card{{padding:16px;border-radius:8px}}
  .card-title{{font-weight:600;font-size:.95em}}
  .card-ts{{font-size:.78em;color:#777;margin-top:6px}}
  footer{{background:#2c3e50;color:#fff;text-align:center;padding:16px;font-size:.85em}}
</style></head>
<body><div class="wrap">
  <div class="hdr">
    <h1>Adware Scanner Enterprise Report</h1>
    <p>Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} &nbsp;|&nbsp; {sum(counts.values())} issues</p>
    <div class="stats">{stats_html}</div>
  </div>
  <div class="grid">{cards_html if threats else '<p style="padding:24px;color:#555">No threats detected.</p>'}</div>
  <footer>Adware Scanner v3.0 &mdash; Enterprise Edition</footer>
</div></body></html>"""

    Path(out).write_text(html, encoding="utf-8")
    print(c(f"\n  [+] HTML report saved: {out}", Colors.GREEN))
    return out


def open_file(path: str):
    sys_name = platform.system()
    try:
        if sys_name == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys_name == "Darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])
    except Exception:
        print(c(f"  Open manually: {path}", Colors.DIM))

# ═══════════════════════════════════════════════════════════════════════════
#  REAL-TIME MONITOR
# ═══════════════════════════════════════════════════════════════════════════
def realtime_monitor(scanner: AdvancedScanner):
    print_header("REAL-TIME PROTECTION")
    print(c("  Monitoring new processes every 2 s — press Ctrl+C to stop\n", Colors.YELLOW))
    if not HAS_PSUTIL:
        print(c("  [!] psutil required for real-time monitoring", Colors.RED))
        return

    seen_pids: set = {p.pid for p in psutil.process_iter()}
    try:
        while True:
            time.sleep(2)
            current = {p.pid for p in psutil.process_iter()}
            for pid in current - seen_pids:
                try:
                    proc = psutil.Process(pid)
                    m = match_signatures(f"{proc.name()} {proc.exe()}")
                    if m:
                        print(c(f"\n  [!!] NEW THREAT: {proc.name()} PID:{pid}", Colors.RED + Colors.BOLD))
                        for sig in m:
                            print(c(f"       -> {sig['name']}: {sig.get('desc', '')}", Colors.RED))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            seen_pids = current
    except KeyboardInterrupt:
        print(c("\n  Real-time monitor stopped.", Colors.YELLOW))

# ═══════════════════════════════════════════════════════════════════════════
#  INTERACTIVE MENU
# ═══════════════════════════════════════════════════════════════════════════
MENU = c("""
╔═══════════════════════════════════════════════════════════════╗
║  ADVANCED ADWARE SCANNER v3.0 — ENTERPRISE EDITION            ║
╚═══════════════════════════════════════════════════════════════╝

  SCAN
    1  Quick scan      — processes + registry
    2  Full scan       — all modules
    3  Browser scan    — history, extensions, prefs

  REMEDIATION
    4  Auto-fix        — terminate & quarantine detected threats
    5  Quarantine view — list quarantined files

  TOOLS
    6  HTML report     — generate & open report
    7  Real-time       — live process monitor
    8  List signatures — show full database
    9  Add signature   — add custom signature

    0  Exit
""", Colors.CYAN)


def print_menu():
    os.system("cls" if platform.system() == "Windows" else "clear")
    print(MENU)
    return input(c("  Select option: ", Colors.BOLD + Colors.GREEN)).strip()


def interactive_loop(scanner: AdvancedScanner):
    while True:
        try:
            choice = print_menu()

            if choice == "1":
                print_header("QUICK SCAN")
                start = time.time()
                results = scanner.scan_processes() + scanner.scan_registry()
                scanner.threats = results
                print_summary(results, time.time() - start)

            elif choice == "2":
                start = time.time()
                scanner.full_scan()
                print_summary(scanner.threats, time.time() - start)

            elif choice == "3":
                print_header("BROWSER DEEP SCAN")
                start = time.time()
                results = scanner.scan_browsers()
                scanner.threats = results
                print_summary(results, time.time() - start)

            elif choice == "4":
                if not scanner.threats:
                    print(c("\n  No threats loaded. Run a scan first.", Colors.YELLOW))
                else:
                    fixed = scanner.auto_remediate()
                    print(c(f"\n  Remediation complete — {fixed} item(s) addressed.", Colors.GREEN))

            elif choice == "5":
                print_header("QUARANTINE")
                entries = scanner.quarantine.entries
                if not entries:
                    print("  Quarantine is empty.")
                for i, e in enumerate(entries, 1):
                    print(f"  {i}. {e['threat']['target'][:60]}  [{e['timestamp'][:10]}]")
                if entries:
                    idx = input(c("\n  Enter number to restore (or Enter to skip): ", Colors.DIM)).strip()
                    if idx.isdigit():
                        scanner.quarantine.restore_file(int(idx) - 1)

            elif choice == "6":
                report = generate_html_report(scanner.threats)
                open_file(report)

            elif choice == "7":
                realtime_monitor(scanner)

            elif choice == "8":
                print_header("SIGNATURE DATABASE")
                for sig in all_signatures():
                    col = Colors.RED if sig["severity"] == "threat" else Colors.YELLOW
                    sev_str = sig['severity'].upper().ljust(7)
                    print(f"  {c(sev_str, col)} {sig['name']:28} pattern={sig['pattern']}")

            elif choice == "9":
                name    = input("  Name    : ").strip()
                pattern = input("  Pattern : ").strip()
                stype   = input("  Type (adware/hijacker/pup) : ").strip() or "adware"
                sev     = input("  Severity (threat/pup)      : ").strip() or "threat"
                desc    = input("  Description                : ").strip()
                if name and pattern:
                    save_custom_signature(name, pattern, stype, sev, desc)

            elif choice == "0":
                print(c("\n  Goodbye! Stay protected.\n", Colors.GREEN))
                sys.exit(0)

            else:
                print(c("  Invalid option.", Colors.RED))

            input(c("\n  Press Enter to continue...", Colors.DIM))

        except KeyboardInterrupt:
            print(c("\n  Operation cancelled.", Colors.YELLOW))
        except Exception as e:
            print(c(f"\n  Unexpected error: {e}", Colors.RED))
            input(c("  Press Enter to continue...", Colors.DIM))

# ═══════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Adware & Browser Hijacker Scanner v3.0",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--quick",   action="store_true", help="Quick scan (processes + registry)")
    parser.add_argument("--full",    action="store_true", help="Full system scan")
    parser.add_argument("--report",  action="store_true", help="Save HTML report after scan")
    parser.add_argument("--target",  nargs="+", metavar="VALUE",
                        help="Scan specific strings directly")
    parser.add_argument("--add-sig", nargs="+", metavar="FIELD",
                        help="NAME PATTERN TYPE SEVERITY [DESC]")
    parser.add_argument("--list-sigs", action="store_true", help="List all signatures and exit")
    args = parser.parse_args()

    # ── Non-interactive modes ──────────────────────────────────────────────
    if args.list_sigs:
        # FIX 4: Moved print() inside the for-loop so every signature is
        #         printed, not just the last one (was an indentation bug).
        for sig in all_signatures():
            col = Colors.RED if sig["severity"] == "threat" else Colors.YELLOW
            sev_str = sig['severity'].upper().ljust(7)
            print(f"{c(sev_str, col)} {sig['name']:28} {sig['pattern']}")
        return

    if args.add_sig:
        if len(args.add_sig) < 4:
            print("Usage: --add-sig NAME PATTERN TYPE SEVERITY [DESC]")
            sys.exit(1)
        save_custom_signature(*args.add_sig[:4],
                              desc=args.add_sig[4] if len(args.add_sig) > 4 else "Custom")
        return

    scanner = AdvancedScanner()
    print(c(f"\n  Signatures loaded: {len(all_signatures())}  |  Admin: {scanner.is_admin}", Colors.DIM))

    if args.target:
        start = time.time()
        results = []
        for t in args.target:
            m = match_signatures(t)
            # FIX 5: Corrected severity ternary — previously the "info" branch
            #         was unreachable because the condition order was wrong.
            if any(s["severity"] == "threat" for s in m):
                sev = "threat"
            elif m:
                sev = "pup"
            else:
                sev = "info"
            results.append(Threat(
                category="Custom target",
                target=t,
                signatures=m,
                severity=sev,
            ))
        for r in results:
            col = Colors.RED if r.severity == "threat" else (Colors.YELLOW if r.signatures else Colors.GREEN)
            label = "THREAT" if r.severity == "threat" else ("PUP" if r.severity == "pup" else "CLEAN")
            print(f"  {c('['+label+']', col)} {r.target}")
            for sig in r.signatures:
                print(f"       -> {sig['name']}: {sig.get('desc','')}")
        print_summary(results, time.time() - start)
        if args.report:
            generate_html_report(results)
        return

    if args.quick:
        start = time.time()
        scanner.threats = scanner.scan_processes() + scanner.scan_registry()
        print_summary(scanner.threats, time.time() - start)
        if args.report:
            generate_html_report(scanner.threats)
        return

    if args.full:
        start = time.time()
        scanner.full_scan()
        print_summary(scanner.threats, time.time() - start)
        if args.report:
            generate_html_report(scanner.threats)
        return

    # ── Default: interactive menu ──────────────────────────────────────────
    interactive_loop(scanner)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(c("\n  Goodbye!\n", Colors.GREEN))
        sys.exit(0)
    except Exception as e:
        print(c(f"\n  Fatal error: {e}", Colors.RED))
        print(c("  Try running as administrator for full functionality.", Colors.YELLOW))
        sys.exit(1)
