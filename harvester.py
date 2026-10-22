# harvester.py
"""
Procurement Harvester and Ingestion Engine.
Connects sources_registry.json, classifier.py, SQLite, and exports public/tenders.json.
Runs on 100% standard Python libraries, with optional acceleration via requests/bs4.
"""

import os
import json
import sqlite3
import urllib.request
import urllib.parse
import ssl
from datetime import datetime, timezone
from html.parser import HTMLParser

# Import the classifier from Step 3
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


class SimpleHTMLScraper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self._current_text = []
        self._current_link = ""

    def handle_starttag(self, tag, attrs):
        if tag in ["tr", "article", "p", "li"]:
            self._current_text = []
            self._current_link = ""
        elif tag == "a":
            for k, v in attrs:
                if k.lower() == "href":
                    self._current_link = v

    def handle_data(self, data):
        cleaned = data.strip()
        if cleaned:
            self._current_text.append(cleaned)

    def handle_endtag(self, tag):
        if tag in ["tr", "article", "p", "li"]:
            full_text = " ".join(self._current_text).strip()
            if len(full_text) > 25:
                self.rows.append((full_text, self._current_link))
            self._current_text = []
            self._current_link = ""


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
            raise FileNotFoundError(f"Registry file '{self.registry_path}' not found.")
        with open(self.registry_path, "r", encoding="utf-8") as f:
            self.registry = json.load(f)
        
        self.target_countries = {item["country"]: item for item in self.registry}
        print(f"[✓] Loaded registry with {len(self.registry)} countries and {sum(len(c['portals']) for c in self.registry)} endpoints.")

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
                with urllib.request.urlopen(req, context=self.ssl_ctx, timeout=timeout) as response:
                    return response.read().decode('utf-8', errors='ignore')
            except Exception:
                return None

    def fetch_mdb_pipeline(self):
        """Queries the World Bank Procurement API supporting both list and dict responses."""
        print("\n[*] Querying Multilateral Development Bank (MDB) Pipeline...")
        notices = []
        endpoint = "https://search.worldbank.org/api/v2/procnotices?format=json&rows=150&os=0"
        
        content = self.fetch_url(endpoint, timeout=25)
        if content:
            try:
                raw_data = json.loads(content).get("procnotices", [])
                
                # Normalize list or dict return formats
                if isinstance(raw_data, dict):
                    items_list = list(raw_data.values())
                elif isinstance(raw_data, list):
                    items_list = raw_data
                else:
                    items_list = []

                for item in items_list:
                    if not isinstance(item, dict):
                        continue
                    cname = item.get("countryname", "").strip()
                    
                    matched_country = next(
                        (tc for tc in self.target_countries.keys() if tc.lower() in cname.lower()),
                        None
                    )

                    if matched_country:
                        country_meta = self.target_countries[matched_country]
                        title = item.get("bid_description", "") or item.get("project_name", "")
                        borrower = item.get("borrower", "Ministry of Finance / Treasury")
                        notices.append({
                            "country": matched_country,
                            "region": country_meta["region"],
                            "entity": borrower,
                            "title": title.strip(),
                            "url": item.get("url", "https://projects.worldbank.org/"),
                            "deadline": item.get("submission_date", "N/A"),
                            "source_type": "MDB_FEED"
                        })
                print(f"  --> Found {len(notices)} notices matching target African countries in MDB feed.")
            except Exception as e:
                print(f"  [!] Note: Error parsing MDB data: {e}")
        else:
            print("  [!] MDB live connection check complete.")

        return notices

    def fetch_portal(self, country: str, region: str, portal: dict):
        notices = []
        url = portal.get("url")
        entity = portal.get("entity")

        html_text = self.fetch_url(url, timeout=10)
        if not html_text:
            return notices

        if HAS_BS4:
            try:
                soup = BeautifulSoup(html_text, "html.parser")
                elements = soup.select("table tr, article, .tender, .post, .item-page, .views-row")
                for el in elements[:20]:
                    text = el.get_text(separator=" ", strip=True)
                    if len(text) > 25:
                        link = el.find("a")
                        href = link["href"] if link and "href" in link.attrs else url
                        full_url = urllib.parse.urljoin(url, href)
                        notices.append({
                            "country": country,
                            "region": region,
                            "entity": entity,
                            "title": text[:300].strip(),
                            "url": full_url,
                            "deadline": "N/A",
                            "source_type": "PORTAL_HTML"
                        })
            except Exception:
                pass
        else:
            try:
                parser = SimpleHTMLScraper()
                parser.feed(html_text)
                for text, href in parser.rows[:20]:
                    full_url = urllib.parse.urljoin(url, href) if href else url
                    notices.append({
                        "country": country,
                        "region": region,
                        "entity": entity,
                        "title": text[:300].strip(),
                        "url": full_url,
                        "deadline": "N/A",
                        "source_type": "PORTAL_HTML"
                    })
            except Exception:
                pass

        return notices

    def run(self):
        print("=" * 70)
        print("STARTING PROCUREMENT MONITORING & INGESTION CYCLE")
        print("=" * 70)

        all_raw_notices = []
        all_raw_notices.extend(self.fetch_mdb_pipeline())

        print("\n[*] Scanning National Procurement Portals...")
        for c in self.registry:
            country = c["country"]
            region = c["region"]
            for portal in c["portals"]:
                ptype = portal.get("type")
                if ptype in ["html_table", "ocds_api"]:
                    portal_notices = self.fetch_portal(country, region, portal)
                    all_raw_notices.extend(portal_notices)

        print(f"\n[*] Total raw records retrieved: {len(all_raw_notices)}")
        print("[*] Evaluating notices against 5 Keyword Knowledge Databases...")

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        qualified_leads = []
        new_count = 0
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        for item in all_raw_notices:
            evaluation = self.classifier.evaluate(
                title=item["title"],
                buyer=item["entity"],
                country=item["country"]
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
                        INSERT INTO procurement_notices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        lead_id, item["country"], item["region"], item["entity"],
                        item["title"], evaluation["tier"], evaluation["score"],
                        "; ".join(matched_terms[:8]), item["url"], item.get("deadline", "N/A"),
                        now_iso
                    ))
                    new_count += 1

                qualified_leads.append({
                    "id": lead_id,
                    "country": item["country"],
                    "region": item["region"],
                    "entity": item["entity"],
                    "title": item["title"],
                    "tier": evaluation["tier"],
                    "score": evaluation["score"],
                    "matched_terms": matched_terms[:6],
                    "url": item["url"],
                    "deadline": item.get("deadline", "N/A")
                })

        conn.commit()
        conn.close()

        qualified_leads.sort(key=lambda x: x["score"], reverse=True)

        os.makedirs("public", exist_ok=True)
        tier_counts = {
            "TIER_1_DIRECT_GRP": sum(1 for q in qualified_leads if q["tier"] == "TIER_1_DIRECT_GRP"),
            "TIER_2_EARLY_SIGNAL": sum(1 for q in qualified_leads if q["tier"] == "TIER_2_EARLY_SIGNAL"),
            "TIER_3_ADJACENT": sum(1 for q in qualified_leads if q["tier"] == "TIER_3_ADJACENT"),
        }

        output_payload = {
            "last_updated": now_iso,
            "total_opportunities": len(qualified_leads),
            "new_this_cycle": new_count,
            "tier_counts": tier_counts,
            "tenders": qualified_leads
        }

        with open("public/tenders.json", "w", encoding="utf-8") as f:
            json.dump(output_payload, f, indent=2, ensure_ascii=False)

        print("\n" + "=" * 70)
        print(f"CYCLE COMPLETE: {len(qualified_leads)} Qualified Leads ({new_count} newly added)")
        print(f"  ★ Tier 1 (Direct GRP/IFMIS):  {tier_counts['TIER_1_DIRECT_GRP']}")
        print(f"  ⚡ Tier 2 (Early Signals):    {tier_counts['TIER_2_EARLY_SIGNAL']}")
        print(f"  📌 Tier 3 (Adjacent/PFM):     {tier_counts['TIER_3_ADJACENT']}")
        print(f"  [✓] Exported live payload to: public/tenders.json")
        print(f"  [✓] Lead history saved in:    {self.db_path}")
        print("=" * 70)


if __name__ == "__main__":
    harvester = ProcurementHarvester()
    harvester.run()