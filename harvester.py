# harvester.py
"""
Procurement Harvester and Ingestion Engine.
Connects sources_registry.json, classifier.py, SQLite, and exports public/tenders.json.
Targets live RFPs, EOIs, and Bids with direct solicitation links.
"""

import os
import json
import sqlite3
import urllib.request
import urllib.parse
import ssl
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


def parse_submission_deadline(date_str: str):
    """Parses tender deadline dates into a UTC datetime object."""
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


class SimpleHTMLScraper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self._current_text = []
        self._current_link = ""

    def handle_starttag(self, tag, attrs):
        if tag in ["tr", "article", "li"]:
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
        if tag in ["tr", "article", "li"]:
            full_text = " ".join(self._current_text).strip()
            if len(full_text) > 25 and self._current_link:
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
        Queries World Bank procurement API across core PFM keywords.
        Extracts direct solicitation links and checks submission deadlines.
        """
        print("\n[*] Querying World Bank Live Procurement Pipeline by PFM Keywords...")
        
        search_terms = [
            "IFMIS", 
            "financial management", 
            "public finance", 
            "accounting system", 
            "treasury", 
            "SIGFP", 
            "SIGFE",
            "revenue system", 
            "payroll",
            "procurement system"
        ]

        seen_notice_ids = set()
        live_notices = []
        now = datetime.now(timezone.utc)

        for term in search_terms:
            encoded_term = urllib.parse.quote_plus(term)
            endpoint = f"https://search.worldbank.org/api/v2/procnotices?format=json&qterm={encoded_term}&rows=75&os=0&srt=noticedate%20desc"
            
            content = self.fetch_url(endpoint, timeout=20)
            if not content:
                continue

            try:
                raw_data = json.loads(content).get("procnotices", [])
                items = list(raw_data.values()) if isinstance(raw_data, dict) else raw_data

                for item in items:
                    if not isinstance(item, dict):
                        continue

                    # Skip past contract awards
                    ntype = (item.get("notice_type") or item.get("noticeType") or item.get("procurementMethod") or "")
                    if "award" in ntype.lower():
                        continue

                    nid = item.get("id") or item.get("notice_id") or item.get("noticeId") or ""
                    if not nid or nid in seen_notice_ids:
                        continue

                    # Extract country using all possible field variants
                    cname = (
                        item.get("countryname") or 
                        item.get("project_country") or 
                        item.get("country_name") or 
                        item.get("country") or 
                        item.get("project_ctry_name") or ""
                    ).strip()

                    matched_country = next((tc for tc in self.target_countries if tc.lower() in cname.lower()), None)
                    if not matched_country:
                        continue

                    # Extract deadline and filter out expired bids
                    deadline_raw = (
                        item.get("submission_deadline_date") or 
                        item.get("submissionDeadlineDate") or 
                        item.get("submission_date") or 
                        item.get("deadline_date") or ""
                    )
                    deadline_dt = parse_submission_deadline(deadline_raw)

                    if deadline_dt:
                        if deadline_dt < now:
                            continue  # Drop expired notices
                        days_remaining = (deadline_dt - now).days
                        deadline_display = deadline_dt.strftime("%Y-%m-%d")
                    else:
                        days_remaining = None
                        deadline_display = "Active (Ongoing)"

                    seen_notice_ids.add(nid)

                    # Direct link to the official tender dossier
                    direct_url = f"https://projects.worldbank.org/en/projects-operations/procurement-detail/{nid}"
                    
                    desc = item.get("bid_description") or item.get("bidDescription") or ""
                    proj = item.get("project_name") or item.get("projectName") or ""
                    title = f"[{ntype}] {proj} - {desc}".strip(" -") if ntype else f"{proj} - {desc}".strip(" -")
                    borrower = item.get("borrower") or item.get("contactOrganization") or "Ministry of Finance / Treasury"

                    live_notices.append({
                        "country": matched_country,
                        "region": self.target_countries[matched_country]["region"],
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

        print(f"  --> Found {len(live_notices)} active, non-expired tender notices across target countries.")
        return live_notices

    def fetch_national_tenders(self, country: str, region: str, portal: dict):
        """Scrapes national portals while filtering strictly for active tender links."""
        notices = []
        url = portal.get("url")
        entity = portal.get("entity")

        html_text = self.fetch_url(url, timeout=12)
        if not html_text:
            return notices

        tender_intent_markers = [
            "tender", "rfp", "reoi", "eoi", "request for", "invitation to",
            "invitation for", "bidding", "procurement of", "appel d'offres",
            "manifestation d'intérêt", "concurso", "consultant"
        ]
        
        irrelevant_news_markers = [
            "speech", "workshop", "press release", "courtesy visit", "celebrated",
            "communique", "discours", "atelier", "point de presse"
        ]

        extracted_pairs = []

        if HAS_BS4:
            try:
                soup = BeautifulSoup(html_text, "html.parser")
                for el in soup.select("table tr, article, .tender-item, .views-row"):
                    text = el.get_text(separator=" ", strip=True)
                    link_tag = el.find("a")
                    if link_tag and "href" in link_tag.attrs:
                        href = link_tag["href"]
                        full_url = urllib.parse.urljoin(url, href)
                        extracted_pairs.append((text, full_url))
            except Exception:
                pass
        else:
            try:
                parser = SimpleHTMLScraper()
                parser.feed(html_text)
                for text, href in parser.rows:
                    full_url = urllib.parse.urljoin(url, href) if href else url
                    extracted_pairs.append((text, full_url))
            except Exception:
                pass

        for text, link in extracted_pairs:
            text_lower = text.lower()
            
            # Drop news/press events
            if any(nm in text_lower for nm in irrelevant_news_markers):
                continue

            # Ensure item is an actual procurement notice
            if any(tm in text_lower for tm in tender_intent_markers) and len(text) > 30:
                notices.append({
                    "country": country,
                    "region": region,
                    "entity": entity,
                    "title": text[:300].strip(),
                    "url": link,
                    "deadline": "Active Tender",
                    "days_left": None,
                    "has_valid_deadline": True,
                    "source": "National Portal"
                })

        return notices

    def run(self):
        print("=" * 70)
        print("STARTING LIVE PROCUREMENT HARVESTING CYCLE")
        print("=" * 70)

        all_candidates = []

        # 1. Fetch targeted live World Bank opportunities
        all_candidates.extend(self.fetch_live_world_bank_pipeline())

        # 2. Fetch national tender boards
        print("\n[*] Scanning Dedicated National Tender Boards...")
        for c in self.registry:
            country = c["country"]
            region = c["region"]
            for portal in c["portals"]:
                ptype = portal.get("type")
                if ptype in ["html_table", "ocds_api"]:
                    portal_notices = self.fetch_national_tenders(country, region, portal)
                    all_candidates.extend(portal_notices)

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

        # Sort: Highest score and nearest deadline first
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
        print(f"HARVEST COMPLETE: {len(qualified_bids)} Verified Live Opportunities")
        print(f"  ★ Tier 1 (Direct GRP/IFMIS):  {tier_counts['TIER_1_DIRECT_GRP']}")
        print(f"  ⚡ Tier 2 (Early Signals):    {tier_counts['TIER_2_EARLY_SIGNAL']}")
        print(f"  📌 Tier 3 (Adjacent/PFM):     {tier_counts['TIER_3_ADJACENT']}")
        print(f"  [✓] Exported live payload:    public/tenders.json")
        print(f"  [✓] Database updated:         {self.db_path}")
        print("=" * 70)


if __name__ == "__main__":
    harvester = ProcurementHarvester()
    harvester.run()