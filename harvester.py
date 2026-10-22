# harvester.py
"""
Production Procurement Harvester.
Filters for live, current opportunities with valid future deadlines.
Excludes expired tenders, past contract awards, and generic ministerial news.
"""

import os
import json
import sqlite3
import urllib.request
import urllib.parse
import ssl
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


def parse_submission_deadline(date_str: str):
    """Parses varied government date formats into a UTC datetime object."""
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

    def fetch_url(self, url, timeout=15):
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
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
                    return resp.read().decode('utf-8', errors='ignore')
            except Exception:
                return None

    def fetch_live_world_bank_pipeline(self):
        """
        Fetches live open opportunities from the World Bank Procurement API.
        Enforces:
        - Sorted newest first (srt=noticedate desc)
        - Excludes Contract Awards (past closed bids)
        - Deadline >= Today
        """
        print("\n[*] Querying Live World Bank Pipeline (Active Bids & RFPs)...")
        live_notices = []
        endpoint = "https://search.worldbank.org/api/v2/procnotices?format=json&rows=250&os=0&srt=noticedate%20desc"
        
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

                notice_type = item.get("notice_type", "")
                # Exclude past contract awards
                if "Contract Award" in notice_type or "Award" in notice_type:
                    continue

                # Country matching
                cname = item.get("countryname", "").strip()
                matched_country = next((tc for tc in self.target_countries if tc.lower() in cname.lower()), None)
                if not matched_country:
                    continue

                # Deadline verification (drop expired notices)
                deadline_raw = item.get("submission_date") or item.get("submission_deadline_date")
                deadline_dt = parse_submission_deadline(deadline_raw)

                if deadline_dt:
                    if deadline_dt < now:
                        continue  # Expired
                    days_remaining = (deadline_dt - now).days
                    deadline_display = deadline_dt.strftime("%Y-%m-%d")
                else:
                    days_remaining = None
                    deadline_display = "Active (Ongoing)"

                title = item.get("bid_description") or item.get("project_name", "")
                notice_id = item.get("id", "")
                
                # Direct Procurement Notice URL
                direct_url = f"https://projects.worldbank.org/en/projects-operations/procurement-detail/{notice_id}" if notice_id else item.get("url", "#")

                live_notices.append({
                    "country": matched_country,
                    "region": self.target_countries[matched_country]["region"],
                    "entity": item.get("borrower", "Ministry of Finance / Treasury"),
                    "title": f"[{notice_type}] {title.strip()}",
                    "url": direct_url,
                    "deadline": deadline_display,
                    "days_left": days_remaining,
                    "has_valid_deadline": True,
                    "source": "World Bank Live Procurement"
                })

            print(f"  --> Found {len(live_notices)} active, non-expired tender notices for target countries.")
        except Exception as e:
            print(f"  [!] Error parsing live notices: {e}")

        return live_notices

    def fetch_afdb_procurement_notices(self):
        """
        Queries African Development Bank (AfDB) Specific Procurement Notices.
        """
        print("\n[*] Querying African Development Bank (AfDB) Solicitations...")
        notices = []
        afdb_url = "https://www.afdb.org/en/documents/project-related-procurement/procurement-notices/specific-procurement-notices"
        
        html_text = self.fetch_url(afdb_url, timeout=20)
        if not html_text:
            return notices

        from html.parser import HTMLParser
        class AfDBParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.records = []
                self._current_text = []
                self._current_link = ""

            def handle_starttag(self, tag, attrs):
                if tag == "a":
                    for k, v in attrs:
                        if k == "href":
                            self._current_link = v
                elif tag in ["tr", "div"]:
                    self._current_text = []

            def handle_data(self, data):
                cleaned = data.strip()
                if cleaned:
                    self._current_text.append(cleaned)

            def handle_endtag(self, tag):
                if tag == "tr":
                    row_text = " ".join(self._current_text)
                    if len(row_text) > 30 and self._current_link:
                        self.records.append((row_text, self._current_link))
                    self._current_text = []

        try:
            parser = AfDBParser()
            parser.feed(html_text)
            for row_text, link in parser.records:
                for country in self.target_countries:
                    if country.lower() in row_text.lower():
                        full_url = urllib.parse.urljoin("https://www.afdb.org", link)
                        notices.append({
                            "country": country,
                            "region": self.target_countries[country]["region"],
                            "entity": "African Development Bank (AfDB)",
                            "title": row_text[:280].strip(),
                            "url": full_url,
                            "deadline": "Active Tender",
                            "days_left": None,
                            "has_valid_deadline": True,
                            "source": "AfDB Specific Procurement Notices"
                        })
                        break
            print(f"  --> Found {len(notices)} African Development Bank notices.")
        except Exception as err:
            print(f"  [!] AfDB parsing note: {err}")

        return notices

    def run(self):
        print("=" * 70)
        print("RUNNING ACTIVE TENDER & RFP INGESTION ENGINE")
        print("=" * 70)

        all_candidates = []
        all_candidates.extend(self.fetch_live_world_bank_pipeline())
        all_candidates.extend(self.fetch_afdb_procurement_notices())

        print(f"\n[*] Evaluating {len(all_candidates)} candidates for PFM/GRP alignment...")

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
        qualified_bids.sort(key=lambda x: (x["score"], -(x["days_left"] if x["days_left"] is not None else -999)), reverse=True)

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
        print(f"HARVEST COMPLETE: {len(qualified_bids)} Verified Live Bids")
        print(f"  ★ Tier 1 (Direct GRP/IFMIS):  {tier_counts['TIER_1_DIRECT_GRP']}")
        print(f"  ⚡ Tier 2 (Early Signals):    {tier_counts['TIER_2_EARLY_SIGNAL']}")
        print(f"  📌 Tier 3 (Adjacent/PFM):     {tier_counts['TIER_3_ADJACENT']}")
        print(f"  [✓] Updated live payload:     public/tenders.json")
        print("=" * 70)


if __name__ == "__main__":
    harvester = ProcurementHarvester()
    harvester.run()