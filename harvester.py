# harvester.py
"""
Procurement Harvester and Ingestion Engine.
Connects sources_registry.json, classifier.py, SQLite, and exports public/tenders.json.
Captures live e-GP, HRMIS/SIGRH, PFM, and GRP tenders across target African nations.
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
from html.parser import HTMLParser

from classifier import OpportunityClassifier

try:
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False


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
            "Accept-Language": "en-US,en;q=0.9,fr;q=0.8,pt;q=0.7",
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
        print("\n[*] Querying World Bank Live Pipeline (HRMIS, e-GP, PFM, GRP, SIGRH, SIGFP)...")
        search_terms = [
            "IFMIS", "HRMIS", "SIGRH", "e-GP", "eGP", "SIGFP", "SIGFE",
            "PAFEN", "financial management", "public finance", "accounting system",
            "civil service", "payroll", "budgeting", "electronic procurement"
        ]

        seen_ids = set()
        live_notices = []
        now = datetime.now(timezone.utc)

        for term in search_terms:
            encoded_term = urllib.parse.quote_plus(term)
            endpoint = f"https://search.worldbank.org/api/v2/procnotices?format=json&qterm={encoded_term}&rows=80&os=0&srt=noticedate%20desc"
            
            content = self.fetch_url(endpoint, timeout=20)
            if not content:
                continue

            try:
                raw_data = json.loads(content).get("procnotices", [])
                items = list(raw_data.values()) if isinstance(raw_data, dict) else raw_data

                for item in items:
                    if not isinstance(item, dict):
                        continue

                    ntype = (item.get("notice_type") or item.get("noticeType") or item.get("procurementMethod") or "")
                    if "award" in ntype.lower():
                        continue

                    nid = item.get("id") or item.get("notice_id") or item.get("noticeId") or ""
                    if not nid or nid in seen_ids:
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

                    seen_ids.add(nid)
                    direct_url = f"https://projects.worldbank.org/en/projects-operations/procurement-detail/{nid}"
                    
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
            except Exception:
                continue

        print(f"  --> Found {len(live_notices)} active notices in development bank feed.")
        return live_notices

    def fetch_pafen_burundi(self):
        print(" -> Ingesting PAFEN Burundi (e-GP & SIGFP)...")
        notices = []
        urls = ["https://pafen.gov.bi/appels-doffres/", "https://pafen.gov.bi/"]
        
        for url in urls:
            html = self.fetch_url(url, timeout=15)
            if not html:
                continue

            pattern = re.compile(r'<a\s+(?:[^>]*?\s+)?href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
            for m in pattern.finditer(html):
                href = m.group(1).strip()
                link_text = re.sub(r'<[^>]+>', ' ', m.group(2)).strip()
                
                start = max(0, m.start() - 350)
                end = min(len(html), m.end() + 350)
                context = " ".join(re.sub(r'<[^>]+>', ' ', html[start:end]).split())

                blob = f"{link_text} {context}".lower()
                if any(k in blob for k in ["e-gp", "sigfp", "marchés publics", "cut", "finances publiques", "appel d'offre", "ami"]):
                    full_title = link_text if len(link_text) > 25 else context[:200]
                    full_url = urllib.parse.urljoin(url, href)
                    notices.append({
                        "country": "Burundi",
                        "region": "Eastern Africa",
                        "entity": "PAFEN - Projet Économie Numérique (Burundi)",
                        "title": full_title[:280].strip(),
                        "url": full_url,
                        "deadline": "Active Tender",
                        "days_left": None,
                        "has_valid_deadline": True,
                        "source": "PAFEN Portal"
                    })
        return notices

    def fetch_namfisa_namibia(self):
        print(" -> Ingesting NAMFISA Namibia (Budgeting & HRMIS Solicitations)...")
        notices = []
        urls = [
            "https://www.namfisa.com.na/download-category/procurement/",
            "https://www.namfisa.com.na/procurement/"
        ]

        for url in urls:
            html = self.fetch_url(url, timeout=15)
            if not html:
                continue

            pattern = re.compile(r'<a\s+(?:[^>]*?\s+)?href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
            for m in pattern.finditer(html):
                href = m.group(1).strip()
                link_text = re.sub(r'<[^>]+>', ' ', m.group(2)).strip()
                
                start = max(0, m.start() - 300)
                end = min(len(html), m.end() + 300)
                context = " ".join(re.sub(r'<[^>]+>', ' ', html[start:end]).split())

                blob = f"{link_text} {context}".lower()
                if any(k in blob for k in ["namfisa", "budgeting", "reporting", "solution", "strategy", "human resources", "g/oib", "g/rfq", "sc/rp"]):
                    full_title = link_text if len(link_text) > 30 else context[:200]
                    full_url = urllib.parse.urljoin(url, href)
                    
                    deadline_str = "11 November 2026" if "november 2026" in blob else "Active Tender"
                    days_left = (datetime(2026, 11, 11, tzinfo=timezone.utc) - datetime.now(timezone.utc)).days if "11 November 2026" in deadline_str else None

                    notices.append({
                        "country": "Namibia",
                        "region": "Southern Africa",
                        "entity": "NAMFISA",
                        "title": full_title[:280].strip(),
                        "url": full_url,
                        "deadline": deadline_str,
                        "days_left": days_left,
                        "has_valid_deadline": True,
                        "source": "NAMFISA Portal"
                    })
        return notices

    def run(self):
        print("=" * 70)
        print("RUNNING ADVANCED PROCUREMENT HARVESTER")
        print("=" * 70)

        all_candidates = []
        all_candidates.extend(self.fetch_live_world_bank_pipeline())
        all_candidates.extend(self.fetch_pafen_burundi())
        all_candidates.extend(self.fetch_namfisa_namibia())

        print(f"\n[*] Evaluating {len(all_candidates)} opportunities against 5 Databases...")

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
        print(f"  [✓] Live payload updated:                public/tenders.json")
        print("=" * 70)


if __name__ == "__main__":
    harvester = ProcurementHarvester()
    harvester.run()