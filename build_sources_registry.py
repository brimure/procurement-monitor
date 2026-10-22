# build_sources_registry.py
"""
Builds the 33-Country Procurement Source Registry.
Outputs sources_registry.json with all portal endpoints and metadata.
"""

import json
import os

SOURCES = [
    # -------------------------------------------------------------
    # EASTERN AFRICA (19 Countries)
    # -------------------------------------------------------------
    {
        "country": "Burundi",
        "region": "Eastern Africa",
        "primary_language": "French",
        "portals": [
            {
                "entity": "Ministère des Finances",
                "type": "html_table",
                "url": "http://www.finances.gov.bi/index.php?option=com_content&view=category&layout=blog&id=86&Itemid=138",
                "notes": "Joomla CMS blog view; monitor French PFM keywords (SIGFP, GFP)."
            }
        ]
    },
    {
        "country": "Comoros",
        "region": "Eastern Africa",
        "primary_language": "French/Arabic",
        "portals": [
            {
                "entity": "Ministry of Finance / BidDetail",
                "type": "html_table",
                "url": "https://www.biddetail.com/comoros/latest-tenders",
                "notes": "Aggregator feed for Comoros public procurement notices."
            }
        ]
    },
    {
        "country": "Djibouti",
        "region": "Eastern Africa",
        "primary_language": "French/Arabic",
        "portals": [
            {
                "entity": "Ministère du Budget / MDB Pipeline",
                "type": "mdb_feed",
                "url": "https://search.worldbank.org/api/v2/procnotices",
                "notes": "Domestic portal unstable; monitored via multilateral donor procurement feed."
            }
        ]
    },
    {
        "country": "Eritrea",
        "region": "Eastern Africa",
        "primary_language": "English/Arabic",
        "portals": [
            {
                "entity": "Ministry of Finance / BidDetail",
                "type": "html_table",
                "url": "https://www.biddetail.com/eritrea-tenders",
                "notes": "Aggregator feed for Eritrean government notices."
            }
        ]
    },
    {
        "country": "Ethiopia",
        "region": "Eastern Africa",
        "primary_language": "English/Amharic",
        "portals": [
            {
                "entity": "Ministry of Finance",
                "type": "html_table",
                "url": "https://www.mofed.gov.et/bid/",
                "notes": "MoF procurement advert board."
            },
            {
                "entity": "Public Procurement Agency (PPA)",
                "type": "html_table",
                "url": "http://www.ppa.gov.et/index.php?option=com_ppa&view=procurement&layout=tender&Itemid=64&lang=en",
                "notes": "Central PPA procurement portal; includes English and Amharic notices."
            }
        ]
    },
    {
        "country": "Kenya",
        "region": "Eastern Africa",
        "primary_language": "English",
        "portals": [
            {
                "entity": "Public Procurement Information Portal (PPIP)",
                "type": "ocds_api",
                "url": "https://tenders.go.ke/tenders",
                "notes": "Central e-GP portal; standard tender listings and OCDS export."
            },
            {
                "entity": "The National Treasury",
                "type": "html_table",
                "url": "https://www.treasury.go.ke/",
                "notes": "National Treasury procurement notices and circulars."
            }
        ]
    },
    {
        "country": "Madagascar",
        "region": "Eastern Africa",
        "primary_language": "French",
        "portals": [
            {
                "entity": "Ministère de l'Économie et des Finances",
                "type": "html_table",
                "url": "http://www.mefb.gov.mg/",
                "notes": "MoF official website; French procurement circulars and notices."
            }
        ]
    },
    {
        "country": "Malawi",
        "region": "Eastern Africa",
        "primary_language": "English",
        "portals": [
            {
                "entity": "Ministry of Finance",
                "type": "html_table",
                "url": "http://www.finance.gov.mw/",
                "notes": "MoF official tender notice board."
            },
            {
                "entity": "Public Procurement and Disposal of Assets Authority (PPDA)",
                "type": "html_table",
                "url": "https://www.ppda.mw/",
                "notes": "Statutory regulatory portal for Malawian public tenders."
            }
        ]
    },
    {
        "country": "Mauritius",
        "region": "Eastern Africa",
        "primary_language": "English/French",
        "portals": [
            {
                "entity": "Ministry of Finance",
                "type": "html_table",
                "url": "http://mof.gov.mu/English/Pages/default.aspx",
                "notes": "MoF official portal."
            },
            {
                "entity": "Procurement Policy Office",
                "type": "html_table",
                "url": "http://publicprocurement.gov.mu/pages/procurementlist.aspx",
                "notes": "Central government procurement directory."
            }
        ]
    },
    {
        "country": "Mozambique",
        "region": "Eastern Africa",
        "primary_language": "Portuguese",
        "portals": [
            {
                "entity": "Ministério da Economia e Finanças (UFSA)",
                "type": "html_table",
                "url": "https://www.mef.gov.mz/",
                "notes": "MoF portal; monitor Portuguese PFM terms (SIGFE, CUT, DNT)."
            }
        ]
    },
    {
        "country": "Rwanda",
        "region": "Eastern Africa",
        "primary_language": "English/French",
        "portals": [
            {
                "entity": "Umucyo e-Procurement System",
                "type": "playwright",
                "url": "https://www.umucyo.gov.rw/eb/bav/selectListAdvertisingListForGU.do?menuId=EB01020100&leftTopFlag=l",
                "notes": "National e-GP system based on KONEPS framework; dynamic JS table."
            },
            {
                "entity": "MINECOFIN",
                "type": "html_table",
                "url": "https://www.minecofin.gov.rw/",
                "notes": "Ministry of Finance and Economic Planning official site."
            },
            {
                "entity": "Rwanda Public Procurement Authority (RPPA)",
                "type": "html_table",
                "url": "https://www.rppa.gov.rw/",
                "notes": "RPPA oversight portal."
            }
        ]
    },
    {
        "country": "Seychelles",
        "region": "Eastern Africa",
        "primary_language": "English/French",
        "portals": [
            {
                "entity": "National Tender Board",
                "type": "html_table",
                "url": "https://www.ntb.sc/tenders",
                "notes": "Clean central tender board listings."
            },
            {
                "entity": "Ministry of Finance, National Planning and Trade",
                "type": "html_table",
                "url": "http://www.finance.gov.sc/",
                "notes": "MoF official website."
            }
        ]
    },
    {
        "country": "Somalia",
        "region": "Eastern Africa",
        "primary_language": "English/Arabic",
        "portals": [
            {
                "entity": "Ministry of Finance (SPN)",
                "type": "html_table",
                "url": "https://mof.gov.so/news/specific-procurement-notice",
                "notes": "Specific Procurement Notices for PFM / World Bank funded projects."
            }
        ]
    },
    {
        "country": "South Sudan",
        "region": "Eastern Africa",
        "primary_language": "English",
        "portals": [
            {
                "entity": "Public Procurement and Disposal of Assets Authority (PPDAA)",
                "type": "html_table",
                "url": "https://tenderportal.ppdaa.gov.ss/current-bids",
                "notes": "National tender portal."
            },
            {
                "entity": "Ministry of Finance and Planning",
                "type": "html_table",
                "url": "https://mofp.gov.ss/",
                "notes": "MoFP portal."
            }
        ]
    },
    {
        "country": "Sudan",
        "region": "Eastern Africa",
        "primary_language": "Arabic/English",
        "portals": [
            {
                "entity": "Ministry of Finance / MDB Pipeline",
                "type": "mdb_feed",
                "url": "https://search.worldbank.org/api/v2/procnotices",
                "notes": "Domestic servers impacted by conflict; captured via World Bank/AfDB feeds."
            }
        ]
    },
    {
        "country": "Tanzania",
        "region": "Eastern Africa",
        "primary_language": "English",
        "portals": [
            {
                "entity": "National e-Procurement System of Tanzania (NeST)",
                "type": "playwright",
                "url": "https://nest.go.tz/tenders/published-tenders",
                "notes": "NeST e-GP portal; requires JS rendering."
            },
            {
                "entity": "Ministry of Finance",
                "type": "html_table",
                "url": "https://www.mof.go.tz/pages/tenders",
                "notes": "MoF tender publication section."
            }
        ]
    },
    {
        "country": "Uganda",
        "region": "Eastern Africa",
        "primary_language": "English",
        "portals": [
            {
                "entity": "Ministry of Finance, Planning and Economic Development (MoFPED)",
                "type": "html_table",
                "url": "https://www.finance.go.ug/media-center/procurement",
                "notes": "MoFPED procurement media center; periodic downtime requires timeout retries."
            }
        ]
    },
    {
        "country": "Zambia",
        "region": "Eastern Africa",
        "primary_language": "English",
        "portals": [
            {
                "entity": "Zambia Public Procurement Authority (ZPPA)",
                "type": "epps_portal",
                "url": "https://eprocure.zppa.org.zm/epps/home.do",
                "notes": "European Dynamics ePPS engine; target UNSPSC 43231601 (Financial Accounting Software)."
            }
        ]
    },
    {
        "country": "Zimbabwe",
        "region": "Eastern Africa",
        "primary_language": "English",
        "portals": [
            {
                "entity": "Procurement Regulatory Authority of Zimbabwe (PRAZ)",
                "type": "html_table",
                "url": "http://www.praz.org.zw/",
                "notes": "Central procurement regulatory portal."
            },
            {
                "entity": "Ministry of Finance and Economic Development",
                "type": "html_table",
                "url": "http://www.zimtreasury.gov.zw/",
                "notes": "National Treasury tenders board."
            }
        ]
    },

    # -------------------------------------------------------------
    # SOUTHERN AFRICA (Additional Distinct Countries)
    # -------------------------------------------------------------
    {
        "country": "Angola",
        "region": "Southern Africa",
        "primary_language": "Portuguese",
        "portals": [
            {
                "entity": "Portal de Compras Públicas",
                "type": "playwright",
                "url": "https://compraspublicas.minfin.gov.ao/ComprasPublicas/#!/",
                "notes": "Angular single-page app; monitor Portuguese terms (SIGFE, Orçamento)."
            }
        ]
    },
    {
        "country": "Botswana",
        "region": "Southern Africa",
        "primary_language": "English",
        "portals": [
            {
                "entity": "Ministry of Finance - Procurement Office",
                "type": "html_table",
                "url": "https://www.finance.gov.bw/index.php?Itemid=248&option=com_content&view=article&id=110&catid=38",
                "notes": "Official MoF procurement office listings."
            }
        ]
    },
    {
        "country": "Eswatini",
        "region": "Southern Africa",
        "primary_language": "English",
        "portals": [
            {
                "entity": "Swaziland Public Procurement (SPP)",
                "type": "html_table",
                "url": "http://www.gov.sz/index.php?option=com_content&view=article&catid=71%3Afinance&id=1391%3Apublic-procument&Itemid=418",
                "notes": "Official government procurement bulletin board."
            }
        ]
    },
    {
        "country": "Lesotho",
        "region": "Southern Africa",
        "primary_language": "English",
        "portals": [
            {
                "entity": "Ministry of Finance / MDB Pipeline",
                "type": "mdb_feed",
                "url": "https://search.worldbank.org/api/v2/procnotices",
                "notes": "Monitored via development bank procurement pipeline."
            }
        ]
    },
    {
        "country": "Namibia",
        "region": "Southern Africa",
        "primary_language": "English",
        "portals": [
            {
                "entity": "Central Procurement Board of Namibia (CPBN)",
                "type": "html_table",
                "url": "https://www.cpb.org.na/index.php/bids-management/current-bids",
                "notes": "Active bids directory with direct downloadable tender specifications."
            }
        ]
    },
    {
        "country": "South Africa",
        "region": "Southern Africa",
        "primary_language": "English",
        "portals": [
            {
                "entity": "National Treasury e-Tenders",
                "type": "ocds_api",
                "url": "https://www.etenders.gov.za/Home/opportunities?id=1",
                "notes": "National Treasury public portal with OCDS data feeds."
            },
            {
                "entity": "Tender Bulletins SA - Software",
                "type": "html_table",
                "url": "https://tenderbulletins.co.za/tender-category/computer-programming-consultancy-and-related-activities/",
                "notes": "Specialized aggregator for IT, software, and consultancy bids."
            },
            {
                "entity": "National Treasury Tender Info",
                "type": "html_table",
                "url": "https://www.treasury.gov.za/tenderinfo/tenders/",
                "notes": "Direct departmental tenders from the National Treasury."
            }
        ]
    },

    # -------------------------------------------------------------
    # CENTRAL AFRICA (Additional Distinct Countries)
    # -------------------------------------------------------------
    {
        "country": "Cameroon",
        "region": "Central Africa",
        "primary_language": "French/English",
        "portals": [
            {
                "entity": "Ministère des Finances",
                "type": "html_table",
                "url": "http://www.minfi.gov.cm/en/home/",
                "notes": "Bilingual MoF notice board; monitor French PFM terms."
            }
        ]
    },
    {
        "country": "Central African Republic",
        "region": "Central Africa",
        "primary_language": "French",
        "portals": [
            {
                "entity": "Direction Générale des Marchés Publics (DGMP)",
                "type": "html_table",
                "url": "http://dgmp-rca.org/",
                "notes": "Central procurement authority portal."
            }
        ]
    },
    {
        "country": "Chad",
        "region": "Central Africa",
        "primary_language": "French/Arabic",
        "portals": [
            {
                "entity": "Direction Générale des Marchés Publics / SGG",
                "type": "html_table",
                "url": "http://sgg-tchad.org/fr/index.php?option=com_content&view=article&id=204&Itemid=674",
                "notes": "Official public procurement gazette."
            }
        ]
    },
    {
        "country": "Republic of the Congo",
        "region": "Central Africa",
        "primary_language": "French",
        "portals": [
            {
                "entity": "Ministère de l'Économie et des Finances",
                "type": "html_table",
                "url": "http://www.mefb-cg.org/petroles/production/contrats.html",
                "notes": "MoF procurement announcements and contracts."
            }
        ]
    },
    {
        "country": "Democratic Republic of the Congo",
        "region": "Central Africa",
        "primary_language": "French",
        "portals": [
            {
                "entity": "Ministère des Finances",
                "type": "html_table",
                "url": "http://minfinrdc.com/minfin/",
                "notes": "MoF portal; frequent World Bank PFM / COREF reform project notices."
            }
        ]
    },
    {
        "country": "Equatorial Guinea",
        "region": "Central Africa",
        "primary_language": "Spanish/French/Portuguese",
        "portals": [
            {
                "entity": "Ministerio de Hacienda y Presupuestos / MDB",
                "type": "mdb_feed",
                "url": "https://search.worldbank.org/api/v2/procnotices",
                "notes": "Domestic digital portal scarce; tracked via multilateral donor pipeline."
            }
        ]
    },
    {
        "country": "Gabon",
        "region": "Central Africa",
        "primary_language": "French",
        "portals": [
            {
                "entity": "Marchés Publics et Appels d'Offres Gabon",
                "type": "html_table",
                "url": "http://www.gabon-services.com/investir-au-gabon/marches-publics-appels-d-offres",
                "notes": "National investment portal tender announcements."
            }
        ]
    },
    {
        "country": "São Tomé and Príncipe",
        "region": "Central Africa",
        "primary_language": "Portuguese",
        "portals": [
            {
                "entity": "Ministério das Finanças (INIC)",
                "type": "html_table",
                "url": "https://www.financas.gov.st/",
                "notes": "MoF portal; monitor Portuguese PFM terms."
            }
        ]
    }
]

def main():
    print(f"Building sources_registry.json for {len(SOURCES)} countries...")
    with open("sources_registry.json", "w", encoding="utf-8") as f:
        json.dump(SOURCES, f, indent=2, ensure_ascii=False)
    
    total_portals = sum(len(c["portals"]) for c in SOURCES)
    print(f"  [✓] Successfully created 'sources_registry.json'")
    print(f"  - Total unique countries: {len(SOURCES)}")
    print(f"  - Total procurement endpoints: {total_portals}")

if __name__ == "__main__":
    main()