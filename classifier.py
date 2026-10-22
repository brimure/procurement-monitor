# classifier.py
"""
Procurement Opportunity Classifier for FreeBalance PFM/GRP Monitoring.
Evaluates notices against the 5 JSON databases:
- keywords/db_core_direct.json
- keywords/db_multilingual.json (French, Portuguese, Arabic, Amharic, Spanish)
- keywords/db_buyer_entities.json
- keywords/db_early_signals.json
- keywords/db_negative_filters.json
"""

import json
import os
import re

class OpportunityClassifier:

    def __init__(self, keywords_dir="keywords"):
        self.keywords_dir = keywords_dir
        self.load_databases()

    def load_databases(self):
        """Loads and indexes the 5 keyword databases."""
        # 1. Core Direct Terms
        with open(os.path.join(self.keywords_dir, "db_core_direct.json"), "r", encoding="utf-8") as f:
            self.core_direct = json.load(f)

        # 2. Multilingual Terms
        with open(os.path.join(self.keywords_dir, "db_multilingual.json"), "r", encoding="utf-8") as f:
            self.multilingual = json.load(f)

        # 3. Buyer Entities
        with open(os.path.join(self.keywords_dir, "db_buyer_entities.json"), "r", encoding="utf-8") as f:
            self.buyer_entities = json.load(f)

        # 4. Early Signals
        with open(os.path.join(self.keywords_dir, "db_early_signals.json"), "r", encoding="utf-8") as f:
            self.early_signals = json.load(f)

        # 5. Negative Filters
        with open(os.path.join(self.keywords_dir, "db_negative_filters.json"), "r", encoding="utf-8") as f:
            self.negative_filters = json.load(f)

        # Flatten core terms
        self.flat_core_terms = set()
        for cat, terms in self.core_direct.items():
            for t in terms:
                self.flat_core_terms.add(t.strip().lower())

        # Flatten multilingual terms
        self.flat_multilingual_terms = set()
        for lang, concepts in self.multilingual.items():
            for concept, terms in concepts.items():
                for t in terms:
                    self.flat_multilingual_terms.add(t.strip().lower())

        # Flatten buyers
        self.flat_buyers = set()
        for cat, buyers in self.buyer_entities.items():
            for b in buyers:
                self.flat_buyers.add(b.strip().lower())

        # Flatten early signals
        self.flat_early_signals = {}
        for area, data in self.early_signals.items():
            for kw in data.get("keywords", []):
                self.flat_early_signals[kw.strip().lower()] = area

        # Exclusions and whitelist
        self.strict_exclusions = [
            ex["term"].strip().lower() for ex in self.negative_filters.get("strict_exclusions", [])
        ]
        self.exemptions_whitelist = [
            w.strip().lower() for w in self.negative_filters.get("exemptions_whitelist", [])
        ]

        # Primary anchor terms
        self.primary_anchors = {
            # English
            "ifmis", "fmis", "grp", "gbfmis", "gifmis", "gfmis",
            "integrated financial management", "government resource planning",
            "public financial management system", "treasury single account",
            # French
            "sigfp", "sigf", "compte unique du trésor", "gestion des finances publiques",
            # Portuguese
            "sigfe", "conta única do tesouro", "gestão das finanças públicas",
            # Arabic
            "نظام معلومات الإدارة المالية", "نظام الإدارة المالية المتكامل", "حساب الخزينة الموحد",
            # Amharic
            "የተቀናጀ የፋይናንስ አስተዳደር መረጃ ሥርዓት", "አንድ ወጥ የግምጃ ቤት ሂሳብ"
        }

    def evaluate(self, title: str, description: str = "", buyer: str = "", country: str = "") -> dict:
        """
        Evaluates a procurement opportunity across all 5 databases.
        """
        search_corpus = f"{title} {description} {buyer} {country}".lower()

        # Step 1: Check Exclusions (Negative Filters)
        is_whitelisted = any(w in search_corpus for w in self.exemptions_whitelist)
        matched_exclusions = []
        if not is_whitelisted:
            for exc in self.strict_exclusions:
                if exc in search_corpus:
                    matched_exclusions.append(exc)
            if matched_exclusions:
                return {
                    "is_relevant": False,
                    "tier": "EXCLUDED",
                    "reason": f"Matched exclusion rule: {', '.join(matched_exclusions)}",
                    "matched_core": [],
                    "matched_multilingual": [],
                    "matched_buyers": [],
                    "matched_early": [],
                    "matched_anchors": [],
                    "score": 0
                }

        # Step 2: Match Anchor terms
        matched_anchors = [a for a in self.primary_anchors if a in search_corpus]

        # Step 3: Match Core Direct Terms
        matched_core = [t for t in self.flat_core_terms if t in search_corpus]

        # Step 4: Match Multilingual Terms
        matched_multi = [m for m in self.flat_multilingual_terms if m in search_corpus]

        # Step 5: Match High-Relevance Buyers
        matched_buyers = [b for b in self.flat_buyers if b in search_corpus]

        # Step 6: Match Early Signals
        matched_early = []
        for kw, area in self.flat_early_signals.items():
            if kw in search_corpus:
                matched_early.append(f"{kw} ({area})")

        all_direct_matches = list(set(matched_core + matched_multi + matched_anchors))

        # Step 7: Scoring
        score = (len(matched_anchors) * 50) + (len(all_direct_matches) * 20) + (len(matched_buyers) * 15) + (len(matched_early) * 15)

        # Step 8: Tier Assignment Hierarchy
        if (matched_anchors or len(all_direct_matches) >= 2) and (matched_buyers or len(all_direct_matches) >= 3):
            tier = "TIER_1_DIRECT_GRP"
            is_relevant = True
        elif matched_anchors:
            tier = "TIER_1_DIRECT_GRP"
            is_relevant = True
        elif matched_early and (matched_buyers or all_direct_matches):
            tier = "TIER_2_EARLY_SIGNAL"
            is_relevant = True
        elif matched_early:
            tier = "TIER_2_EARLY_SIGNAL"
            is_relevant = True
        elif all_direct_matches and matched_buyers:
            tier = "TIER_3_ADJACENT"
            is_relevant = True
        else:
            tier = "LOW_RELEVANCE"
            is_relevant = False

        return {
            "is_relevant": is_relevant,
            "tier": tier,
            "score": score,
            "matched_anchors": matched_anchors,
            "matched_core": matched_core[:5],
            "matched_multilingual": matched_multi[:5],
            "matched_buyers": matched_buyers[:3],
            "matched_early": matched_early[:5]
        }

if __name__ == "__main__":
    clf = OpportunityClassifier()

    test_cases = [
        {
            "country": "Kenya",
            "title": "Supply, Customization, Implementation and Support of Integrated Financial Management Information System (IFMIS)",
            "buyer": "The National Treasury"
        },
        {
            "country": "Cameroon",
            "title": "Recrutement d'un consultant pour le diagnostic du SIGFP et l'assistance technique pour le Compte Unique du Trésor",
            "buyer": "Ministère des Finances"
        },
        {
            "country": "Angola",
            "title": "Modernização do Sistema Integrado de Gestão Financeira do Estado (SIGFE) e Integração da Conta Única do Tesouro",
            "buyer": "Ministério das Finanças"
        },
        {
            "country": "Ethiopia",
            "title": "የመንግስት የተቀናጀ የፋይናንስ አስተዳደር መረጃ ሥርዓት (IFMIS) የሶፍትዌር ዝርጋታ",
            "buyer": "የገንዘብ ሚኒስቴር"
        },
        {
            "country": "Sudan",
            "title": "مشروع تطوير نظام الإدارة المالية المتكامل والخزانة العامة",
            "buyer": "وزارة المالية"
        },
        {
            "country": "Tanzania",
            "title": "Supply and installation of school management system for secondary schools",
            "buyer": "Ministry of Education"
        }
    ]

    print("Running Classifier Unit Tests Across Languages:\n")
    for tc in test_cases:
        res = clf.evaluate(title=tc["title"], buyer=tc["buyer"], country=tc["country"])
        print(f"[{res['tier']}] ({tc['country']}) - Score: {res['score']}")
        print(f"  Title: {tc['title']}")
        print(f"  Anchors: {res['matched_anchors']}")
        print(f"  Relevant: {res['is_relevant']}\n")