# harvester.py
"""
Procurement Harvester and Ingestion Engine.
Connects sources_registry.json, classifier.py, SQLite, and exports public/tenders.json.
Scans across all 33 target countries in Eastern, Southern, and Central Africa.
"""

import os
import json
import sqlite3
import urllib.request
import urllib.parse
import ssl
import gzip
import zlib
import re
from datetime import datetime, timezone

from classifier import OpportunityClassifier

try:
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


COUNTRY_SYNONYMS = {
    "Burundi": ["burundi", "pafen"],
    "Central African Republic": ["central african republic", "république centrafricaine", "republique centrafricaine", "centrafrique", "rca", "bangui"],
    "Namibia": ["namibia", "namfisa"],
    "Democratic Republic of the Congo": ["democratic republic of the congo", "congo, democratic republic of", "congo, dem. rep.", "dr congo", "drc", "rdc", "république démocratique du congo"],
    "Republic of the Congo": ["republic of the congo", "congo, republic of", "congo, rep.", "congo (brazzaville)", "république du congo"],
    "Chad": ["chad", "tchad"],
    "Cameroon": ["cameroon", "cameroun"],
    "Equatorial Guinea": ["equatorial guinea", "guinée équatoriale", "guinea ecuatorial"],
    "Eswatini": ["eswatini", "swaziland"],
    "São Tomé and Príncipe": ["são tomé", "sao tome", "sao tome and principe", "são tomé e príncipe"],
    "Comoros": ["comoros", "comores"],
    "Djibouti": ["djibouti"],
    "Eritrea": ["eritrea"],
    "Ethiopia": ["ethiopia", "éthiopie"],
    "Kenya": ["kenya"],
    "Madagascar": ["madagascar"],
    "Malawi": ["malawi"],
    "Mauritius": ["mauritius", "maurice"],
    "Mozambique": ["mozambique"],
    "Rwanda": ["rwanda"],
    "Seychelles": ["seychelles"],
    "Somalia": ["somalia", "somalie"],
    "South Sudan": ["south sudan", "soudan du sud"],
    "Sudan": ["sudan", "soudan"],
    "Tanzania": ["tanzania", "tanzanie"],
    "Uganda": ["uganda", "ouganda"],
    "Zambia": ["zambia", "zambie"],
    "Zimbabwe": ["zimbabwe"],
    "Botswana": ["botswana"],
    "Lesotho": ["lesotho"],
    "South Africa": ["south africa", "afrique du sud"],
    "Angola": ["angola"],
    "Gabon": ["gabon"]
}


def parse_submission_deadline(date_str: str):
    if not date_str or date_str in ["N/A", "null", "None", ""]:
        return None

    cleaned = re.sub(r'T.*$', '', str(date_str)).strip()
    formats = [
        "%Y-%m-%d", "%d-%b-%Y", "%d/%m/%Y", "%m/%d/%Y",
        "%d-%m-%Y", "%Y/%m/%d", "%d %B %Y", "%d %b %Y"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def clean_scraped_title(raw_text: str) -> str:
    cleaned = re.sub(r'<[^>]+>', ' ', raw_text)
    # Filter out code artifacts
    if any(g in cleaned.lower() for g in ["data-frame", "style=", "z-index", "px;", "elementor", "lazyload", "copyright"]):
        return ""
    
    # Strip file metadata
    cleaned = re.sub(r'\d+\s+fichier[·\s\w]*\d+[\.,]?\d*\s*[KkMmGg][BbOo].*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\|\s*\d+[\.,]?\d*\s*[KkMmGg][BbOo]\s*Download.*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'Read More.*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'Télécharger.*', '', cleaned, flags=re.IGNORECASE)
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned


class ProcurementHarvester:
    def __init__(self, registry_path="sources_registry.json", db_path="procurement_leads.db"):
        self.registry_path = registry_path
        self.db_path = db_path
        self.classifier = OpportunityClassifier()
        self.load_registry()
        self.init_database()

        self.ssl_ctx = ssl.create_default_context()
        self.ssl_ctx.check_hostname = False
        self.ssl_ctx.verify_mode = ssl.CERT_NONE

    def load_registry(self):
        if not os.path.exists(self.registry_path):
            self.registry = []
        else:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                self.registry = json.load(f)

        self.target_countries = {item["country"]: item for item in self.registry}
        print(f"[✓] Loaded registry with {len(self.registry)} countries.")

    def init_database(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS procurement_notices (
                id TEXT PRIMARY KEY,
                country TEXT,
                region TEXT,
                entity TEXT,
                title TEXT,
                tier TEXT,
                score INTEGER,
                matched_terms TEXT,
                url TEXT,
                deadline TEXT,
                days_left INTEGER,
                discovered_at TEXT
            )
        """)
        conn.commit()
        conn.close()

    def fetch_url(self, url, timeout=18):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate"
        }
        if HAS_REQUESTS:
            try:
                r = requests.get(url, headers=headers, timeout=timeout, verify=False)
                return r.text
            except Exception:
                return None
        else:
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, context=self.ssl_ctx, timeout=timeout) as resp:
                    raw_bytes = resp.read()
                    if raw_bytes.startswith(b'\x1f\x8b'):
                        try:
                            return gzip.decompress(raw_bytes).decode('utf-8', errors='ignore')
                        except Exception:
                            pass
                    try:
                        return zlib.decompress(raw_bytes).decode('utf-8', errors='ignore')
                    except Exception:
                        pass
                    return raw_bytes.decode('utf-8', errors='ignore')
            except Exception:
                return None

    def match_country(self, text: str):
        text_lower = text.lower()
        for country, syns in COUNTRY_SYNONYMS.items():
            if any(s in text_lower for s in syns):
                return country
        return None

    def fetch_live_world_bank_pipeline(self):
        """Fetches the newest 300 notices directly from the World Bank API."""
        print("\n[*] Querying World Bank Live Procurement Pipeline (Latest 300 Notices across Africa)...")
        live_notices = []
        endpoint = "https://search.worldbank.org/api/v2/procnotices?format=json&rows=300&os=0&srt=noticedate%20desc"
        
        content = self.fetch_url(endpoint, timeout=25)
        if not content:
            print("  [!] World Bank API endpoint temporarily unreachable.")
            return live_notices

        now = datetime.now(timezone.utc)

        try:
            raw_data = json.loads(content).get("procnotices", [])
            items = list(raw_data.values()) if isinstance(raw_data, dict) else raw_data

            for item in items:
                if not isinstance(item, dict):
                    continue

                ntype = (item.get("notice_type") or item.get("noticeType") or item.get("procurementMethod") or "")
                if "award" in ntype.lower():
                    continue

                cname = (
                    item.get("countryname") or item.get("project_country") or 
                    item.get("country_name") or item.get("country") or ""
                ).strip()

                matched_country = self.match_country(cname)
                if not matched_country:
                    continue

                deadline_raw = (
                    item.get("submission_deadline_date") or 
                    item.get("submissionDeadlineDate") or 
                    item.get("submission_date") or ""
                )
                deadline_dt = parse_submission_deadline(deadline_raw)

                if deadline_dt:
                    if deadline_dt < now:
                        continue
                    days_remaining = (deadline_dt - now).days
                    deadline_display = deadline_dt.strftime("%Y-%m-%d")
                else:
                    days_remaining = None
                    deadline_display = "Active (Ongoing)"

                nid = item.get("id") or item.get("notice_id") or ""
                direct_url = f"https://projects.worldbank.org/en/projects-operations/procurement-detail/{nid}" if nid else item.get("url", "#")
                
                desc = item.get("bid_description") or item.get("bidDescription") or ""
                proj = item.get("project_name") or item.get("projectName") or ""
                title = f"[{ntype}] {proj} - {desc}".strip(" -")
                borrower = item.get("borrower") or item.get("contactOrganization") or "Ministry of Finance / PIU"

                region = self.target_countries.get(matched_country, {}).get("region", "Africa")

                live_notices.append({
                    "country": matched_country,
                    "region": region,
                    "entity": borrower,
                    "title": title[:300].strip(),
                    "url": direct_url,
                    "deadline": deadline_display,
                    "days_left": days_remaining,
                    "has_valid_deadline": True,
                    "source": "World Bank Live Procurement"
                })

            print(f"  --> Found {len(live_notices)} active World Bank notices for target countries.")
        except Exception as e:
            print(f"  [!] Error parsing World Bank data: {e}")

        return live_notices

    def fetch_pafen_burundi(self):
        """Clean ingestion for PAFEN Burundi with tender-level deduplication."""
        print(" -> Ingesting PAFEN Burundi (e-GP, SIGFP, CUT)...")
        raw_tenders = []
        html = self.fetch_url("https://pafen.gov.bi/appels-doffres/", timeout=15)
        if not html:
            return raw_tenders

        pattern = re.compile(r'<a\s+(?:[^>]*?\s+)?href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
        for m in pattern.finditer(html):
            href = m.group(1).strip()
            title = clean_scraped_title(m.group(2))
            if not title or len(title) < 25:
                continue

            blob = title.lower()
            if any(k in blob for k in ["e-gp", "sigfp", "cut", "compte unique", "finances publiques", "marchés publics"]):
                full_url = urllib.parse.urljoin("https://pafen.gov.bi/appels-doffres/", href)
                raw_tenders.append({
                    "title": title,
                    "url": full_url
                })

        # Group notices into clean tenders
        deduped = {}
        for t in raw_tenders:
            key = "OTHER"
            if "sigfp" in t["title"].lower():
                key = "SIGFP_BI"
            elif "e-gp" in t["title"].lower() or "marchés publics" in t["title"].lower():
                key = "EGP_BI"
            elif "cut" in t["title"].lower() or "compte unique" in t["title"].lower():
                key = "CUT_BI"

            if key not in deduped:
                deduped[key] = t
            elif len(t["title"]) > len(deduped[key]["title"]):
                deduped[key] = t

        output = []
        for t in deduped.values():
            output.append({
                "country": "Burundi",
                "region": "Eastern Africa",
                "entity": "PAFEN - Projet Économie Numérique (Burundi)",
                "title": t["title"],
                "url": t["url"],
                "deadline": "Active Tender",
                "days_left": None,
                "has_valid_deadline": True,
                "source": "PAFEN Portal"
            })
        return output

    def fetch_namfisa_namibia(self):
        """Ingests NAMFISA's 3 software solution solicitations."""
        print(" -> Ingesting NAMFISA Namibia (Budgeting, Performance & HRMIS Solutions)...")
        notices = []
        html = self.fetch_url("https://www.namfisa.com.na/download-category/procurement/", timeout=15)
        if not html:
            return notices

        pattern = re.compile(r'<a\s+(?:[^>]*?\s+)?href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
        seen_tenders = set()

        for m in pattern.finditer(html):
            href = m.group(1).strip()
            title = clean_scraped_title(m.group(2))
            if not title or len(title) < 30:
                continue

            blob = title.lower()
            # Only match the software solutions
            if any(k in blob for k in ["namfisa-001", "namfisa-002", "namfisa-003", "financial reporting solution", "strategy and performance", "human resources administration"]):
                key = title[:35]
                if key in seen_tenders:
                    continue
                seen_tenders.add(key)

                full_url = urllib.parse.urljoin("https://www.namfisa.com.na", href)
                deadline_str = "11 November 2026"
                days_left = (datetime(2026, 11, 11, tzinfo=timezone.utc) - datetime.now(timezone.utc)).days

                notices.append({
                    "country": "Namibia",
                    "region": "Southern Africa",
                    "entity": "NAMFISA",
                    "title": title,
                    "url": full_url,
                    "deadline": deadline_str,
                    "days_left": days_left,
                    "has_valid_deadline": True,
                    "source": "NAMFISA Portal"
                })
        return notices

    def fetch_portal_tenders(self, country: str, region: str, portal: dict):
        """Scrapes dedicated tender boards from sources_registry.json."""
        notices = []
        url = portal.get("url")
        if not url:
            return notices

        html = self.fetch_url(url, timeout=12)
        if not html:
            return notices

        pattern = re.compile(r'<a\s+(?:[^>]*?\s+)?href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
        for m in pattern.finditer(html):
            href = m.group(1).strip()
            text = clean_scraped_title(m.group(2))
            if not text or len(text) < 30:
                continue

            blob = text.lower()
            if any(t in blob for t in ["tender", "rfp", "reoi", "eoi", "bidding", "appel d'offres", "concurso", "sigfp", "ifmis"]):
                full_url = urllib.parse.urljoin(url, href)
                notices.append({
                    "country": country,
                    "region": region,
                    "entity": portal["entity"],
                    "title": text[:300].strip(),
                    "url": full_url,
                    "deadline": "Active Tender",
                    "days_left": None,
                    "has_valid_deadline": True,
                    "source": "National Portal"
                })
        return notices

    def run(self):
        print("=" * 70)
        print("RUNNING AFRICA PROCUREMENT HARVESTER")
        print("=" * 70)

        all_candidates = []

        # 1. World Bank Pipeline (All 33 countries)
        all_candidates.extend(self.fetch_live_world_bank_pipeline())

        # 2. Targeted Units (PAFEN & NAMFISA)
        all_candidates.extend(self.fetch_pafen_burundi())
        all_candidates.extend(self.fetch_namfisa_namibia())

        # 3. National Portals across all 33 countries
        print("\n[*] Scanning National Procurement Portals across all 33 Countries...")
        for c in self.registry:
            country = c["country"]
            region = c["region"]
            for portal in c.get("portals", []):
                ptype = portal.get("type")
                if ptype in ["html_table", "ocds_api"]:
                    all_candidates.extend(self.fetch_portal_tenders(country, region, portal))

        print(f"\n[*] Evaluating {len(all_candidates)} candidates against 5 Keyword Databases...")

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        qualified_bids = []
        new_count = 0
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        for item in all_candidates:
            evaluation = self.classifier.evaluate(
                title=item["title"],
                buyer=item["entity"],
                country=item["country"],
                has_valid_deadline=item.get("has_valid_deadline", False)
            )

            if evaluation["is_relevant"]:
                lead_id = f"{item['country']}_{abs(hash(item['title']))}"
                matched_terms = list(set(
                    evaluation["matched_anchors"] + 
                    evaluation["matched_core"] + 
                    evaluation["matched_multilingual"] + 
                    evaluation["matched_buyers"] + 
                    evaluation["matched_early"]
                ))

                cur.execute("SELECT id FROM procurement_notices WHERE id = ?", (lead_id,))
                if cur.fetchone() is None:
                    cur.execute("""
                        INSERT INTO procurement_notices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        lead_id, item["country"], item["region"], item["entity"],
                        item["title"], evaluation["tier"], evaluation["score"],
                        "; ".join(matched_terms[:8]), item["url"], item["deadline"],
                        item.get("days_left"), now_iso
                    ))
                    new_count += 1

                qualified_bids.append({
                    "id": lead_id,
                    "country": item["country"],
                    "region": item["region"],
                    "entity": item["entity"],
                    "title": item["title"],
                    "tier": evaluation["tier"],
                    "score": evaluation["score"],
                    "matched_terms": matched_terms[:6],
                    "url": item["url"],
                    "deadline": item["deadline"],
                    "days_left": item.get("days_left")
                })

        conn.commit()
        conn.close()

        # Sort: Highest score and soonest deadline first
        qualified_bids.sort(
            key=lambda x: (x["score"], -(x["days_left"] if x["days_left"] is not None else -999)),
            reverse=True
        )

        os.makedirs("public", exist_ok=True)
        tier_counts = {
            "TIER_1_DIRECT_GRP": sum(1 for q in qualified_bids if q["tier"] == "TIER_1_DIRECT_GRP"),
            "TIER_2_EARLY_SIGNAL": sum(1 for q in qualified_bids if q["tier"] == "TIER_2_EARLY_SIGNAL"),
            "TIER_3_ADJACENT": sum(1 for q in qualified_bids if q["tier"] == "TIER_3_ADJACENT"),
        }

        output_payload = {
            "last_updated": now_iso,
            "total_opportunities": len(qualified_bids),
            "new_this_cycle": new_count,
            "tier_counts": tier_counts,
            "tenders": qualified_bids
        }

        with open("public/tenders.json", "w", encoding="utf-8") as f:
            json.dump(output_payload, f, indent=2, ensure_ascii=False)

        print("\n" + "=" * 70)
        print(f"HARVEST COMPLETE: {len(qualified_bids)} Verified Opportunities")
        print(f"  ★ Tier 1 (Direct GRP/IFMIS/HRMIS/e-GP): {tier_counts['TIER_1_DIRECT_GRP']}")
        print(f"  ⚡ Tier 2 (Early Signals):               {tier_counts['TIER_2_EARLY_SIGNAL']}")
        print(f"  📌 Tier 3 (Adjacent/PFM):                {tier_counts['TIER_3_ADJACENT']}")
        print(f"  [✓] Exported live payload to:            public/tenders.json")
        print("=" * 70)


if __name__ == "__main__":
    harvester = ProcurementHarvester()
    harvester.run()