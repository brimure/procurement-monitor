# classifier.py
"""
Procurement Opportunity Classifier for FreeBalance PFM/GRP/HRMIS Monitoring.
"""

import json
import os
import re

PROCUREMENT_ACTION_INTENT = [
    # English
    "request for proposals", "rfp", "request for expressions of interest", "reoi",
    "expression of interest", "eoi", "invitation for bids", "ifb", "request for bids",
    "rfb", "specific procurement notice", "spn", "invitation to tender", "itt",
    "tender notice", "tender document", "bidding document", "procurement of",
    "supply, installation", "supply, delivery", "implementation of", "consultancy services for",
    "terms of reference", "bidding details", "oib", "g/oib", "g/rfq", "sc/rp",
    # French
    "demande de propositions", "appel d'offres", "avis d'appel d'offres",
    "avis à manifestation d'intérêt", "manifestation d'intérêt", "ami",
    "dossier d'appel d'offres", "dao", "fourniture et mise en place",
    "recrutement d'un consultant", "avis de passation des marchés",
    "aquisition et mise en place", "acquisition et mise en place",
    # Portuguese & Others
    "concurso público", "manifestação de interesse", "solicitação de propostas",
    "concurso de projectos", "documentos de concurso", "termos de referência",
    "طلب عروض", "مناقصة", "إبداء الاهتمام", "የጨረታ ማስታወቂያ", "የግዢ ማስታወቂያ"
]

IRRELEVANT_PATTERNS = [
    "workshop", "press release", "communique", "speech", "inauguration",
    "seminar", "celebration", "courtesy visit", "courtesy call",
    "discours", "atelier", "communiqué", "point de presse"
]


class OpportunityClassifier:
    def __init__(self, keywords_dir="keywords"):
        self.keywords_dir = keywords_dir
        self.load_databases()

    def load_databases(self):
        with open(os.path.join(self.keywords_dir, "db_core_direct.json"), "r", encoding="utf-8") as f:
            self.core_direct = json.load(f)

        with open(os.path.join(self.keywords_dir, "db_multilingual.json"), "r", encoding="utf-8") as f:
            self.multilingual = json.load(f)

        with open(os.path.join(self.keywords_dir, "db_buyer_entities.json"), "r", encoding="utf-8") as f:
            self.buyer_entities = json.load(f)

        with open(os.path.join(self.keywords_dir, "db_early_signals.json"), "r", encoding="utf-8") as f:
            self.early_signals = json.load(f)

        with open(os.path.join(self.keywords_dir, "db_negative_filters.json"), "r", encoding="utf-8") as f:
            self.negative_filters = json.load(f)

        self.flat_core_terms = set(t.strip().lower() for cat in self.core_direct.values() for t in cat)
        self.flat_multilingual_terms = set(
            t.strip().lower() for lang in self.multilingual.values() for concept in lang.values() for t in concept
        )
        self.flat_buyers = set(b.strip().lower() for buyers in self.buyer_entities.values() for b in buyers)

        self.flat_early_signals = {}
        for area, data in self.early_signals.items():
            for kw in data.get("keywords", []):
                self.flat_early_signals[kw.strip().lower()] = area

        self.strict_exclusions = [ex["term"].strip().lower() for ex in self.negative_filters.get("strict_exclusions", [])]
        self.exemptions_whitelist = [w.strip().lower() for w in self.negative_filters.get("exemptions_whitelist", [])]

        # Primary anchors for core opportunities
        self.primary_anchors = {
            "ifmis", "fmis", "grp", "gbfmis", "gifmis", "gfmis",
            "integrated financial management", "government resource planning",
            "public financial management system", "treasury single account",
            "sigfp", "sigf", "compte unique du trésor", "gestion des finances publiques",
            "sigfe", "conta única do tesouro", "gestão das finanças públicas",
            "hrmis", "sigrh", "gestion des ressources humaines",
            "e-gp", "egp", "electronic government procurement", "marchés publics électroniques",
            "budgeting, planning", "financial reporting solution", "performance management solution",
            "pafen", "namfisa", "نظام معلومات الإدارة المالية", "نظام الإدارة المالية المتكامل",
            "የተቀናጀ የፋይናንስ አስተዳደር መረጃ ሥርዓት"
        }

    def evaluate(self, title: str, description: str = "", buyer: str = "", country: str = "", *args, **kwargs) -> dict:
        search_corpus = f"{title} {description} {buyer} {country}".lower()
        has_valid_deadline = kwargs.get("has_valid_deadline", False)

        if not has_valid_deadline:
            if any(p in search_corpus for p in IRRELEVANT_PATTERNS):
                return {"is_relevant": False, "tier": "EXCLUDED", "reason": "Press release"}

        has_intent = any(i in search_corpus for i in PROCUREMENT_ACTION_INTENT) or has_valid_deadline
        if not has_intent:
            return {"is_relevant": False, "tier": "EXCLUDED", "reason": "No procurement action intent"}

        is_whitelisted = any(w in search_corpus for w in self.exemptions_whitelist)
        if not is_whitelisted:
            for exc in self.strict_exclusions:
                if exc in search_corpus:
                    return {"is_relevant": False, "tier": "EXCLUDED", "reason": f"Excluded by rule: {exc}"}

        matched_anchors = [a for a in self.primary_anchors if a in search_corpus]
        matched_core = [t for t in self.flat_core_terms if t in search_corpus]
        matched_multi = [m for m in self.flat_multilingual_terms if m in search_corpus]
        matched_buyers = [b for b in self.flat_buyers if b in search_corpus]

        matched_early = []
        for kw, area in self.flat_early_signals.items():
            if kw in search_corpus:
                matched_early.append(f"{kw} ({area})")

        all_direct_matches = list(set(matched_core + matched_multi + matched_anchors))
        score = (len(matched_anchors) * 50) + (len(all_direct_matches) * 20) + (len(matched_buyers) * 15) + (len(matched_early) * 15)

        if matched_anchors or len(all_direct_matches) >= 2:
            tier = "TIER_1_DIRECT_GRP"
            is_relevant = True
        elif matched_early:
            tier = "TIER_2_EARLY_SIGNAL"
            is_relevant = True
        elif all_direct_matches:
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