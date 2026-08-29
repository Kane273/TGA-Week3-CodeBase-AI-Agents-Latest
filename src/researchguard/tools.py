from __future__ import annotations

import math
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx
from langchain_core.tools import tool
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from researchguard.models import EvidenceItem


@dataclass(frozen=True)
class CorpusRecord:
    keywords: tuple[str, ...]
    evidence: EvidenceItem


ADDITIONAL_DEMO_TOPICS = (
    (
        ("mindfulness", "workplace", "stress"),
        "Mindfulness and workplace stress",
        "Mindfulness practice can reduce workplace stress.",
    ),
    (
        ("peer", "feedback", "writing", "quality"),
        "Peer feedback and writing",
        "Structured peer feedback can improve writing quality.",
    ),
    (
        ("screen", "time", "adolescent", "sleep"),
        "Screen time and adolescent sleep",
        "Reduced evening screen time can improve adolescent sleep.",
    ),
    (
        ("remote", "work", "productivity"),
        "Remote work and productivity",
        "Structured remote work can affect employee productivity.",
    ),
    (
        ("music", "practice", "working", "memory"),
        "Music practice and working memory",
        "Music practice can affect working-memory performance.",
    ),
    (
        ("green", "space", "anxiety"),
        "Green space and anxiety",
        "Green-space exposure can reduce anxiety symptoms.",
    ),
    (
        ("simulation", "training", "clinical", "accuracy"),
        "Simulation training and clinical accuracy",
        "Simulation training can improve clinical accuracy.",
    ),
    (
        ("spaced", "repetition", "vocabulary"),
        "Spaced repetition and vocabulary",
        "Spaced repetition can improve vocabulary retention.",
    ),
    (
        ("team", "diversity", "decision", "quality"),
        "Team diversity and decisions",
        "Team diversity can affect decision quality.",
    ),
    (
        ("standing", "desk", "desks", "back", "pain"),
        "Standing desks and back pain",
        "Standing-desk programs can reduce back pain.",
    ),
    (
        ("notifications", "sustained", "attention"),
        "Notifications and attention",
        "Reducing notifications can improve sustained attention.",
    ),
    (
        ("mentoring", "employee", "retention"),
        "Mentoring and employee retention",
        "Structured mentoring can improve employee retention.",
    ),
    (
        ("telehealth", "appointment", "adherence"),
        "Telehealth and appointment adherence",
        "Telehealth access can improve appointment adherence.",
    ),
    (
        ("financial", "education", "saving", "behavior"),
        "Financial education and saving",
        "Financial education can improve saving behavior.",
    ),
    (
        ("class", "size", "mathematics", "achievement"),
        "Class size and mathematics",
        "Reduced class size can affect mathematics achievement.",
    ),
    (
        ("daily", "walking", "blood", "pressure"),
        "Daily walking and blood pressure",
        "Daily walking can reduce blood pressure.",
    ),
    (
        ("coding", "assistants", "defect", "rates"),
        "Coding assistants and defects",
        "Coding assistants can affect software defect rates.",
    ),
    (
        ("four", "day", "workweeks", "burnout"),
        "Four-day workweeks and burnout",
        "Four-day workweeks can reduce employee burnout.",
    ),
    (
        ("virtual", "reality", "spatial", "learning"),
        "Virtual reality and spatial learning",
        "Virtual-reality instruction can improve spatial learning.",
    ),
    (
        ("break", "reminders", "eye", "strain"),
        "Break reminders and eye strain",
        "Scheduled break reminders can reduce digital eye strain.",
    ),
)


CORPUS = (
    CorpusRecord(
        ("sleep", "learning", "memory", "student"),
        EvidenceItem(
            title="Sleep and memory consolidation",
            finding="Sleep supports consolidation, while observational designs remain vulnerable to confounding.",
            source="demo://sleep-memory-review",
            strength="high",
            abstract="Sleep supports university learning and memory consolidation, although observational studies can be confounded by stress, health, and study habits.",
            claim="Sleep can support learning and memory consolidation.",
        ),
    ),
    CorpusRecord(
        ("exercise", "mood", "depression", "wellbeing"),
        EvidenceItem(
            title="Exercise and mental wellbeing",
            finding="Exercise interventions can improve mood, with adherence and expectancy as key threats.",
            source="demo://exercise-mood-review",
            strength="medium",
            abstract="Structured exercise interventions can improve mood outcomes. Adherence and expectancy effects influence estimates.",
            claim="Structured exercise can improve mood outcomes.",
        ),
    ),
    CorpusRecord(
        ("ai", "tutor", "education", "learning"),
        EvidenceItem(
            title="Adaptive tutoring systems",
            finding="AI tutoring can improve algebra performance; far transfer should be measured separately.",
            source="demo://adaptive-tutoring-review",
            strength="medium",
            abstract="An AI tutor improved algebra performance for first-year students in some settings, but far-transfer evidence remains limited.",
            claim="AI tutoring can improve algebra performance for first-year students.",
        ),
    ),
    CorpusRecord(
        ("retrieval", "augmented", "generation", "rag", "hallucinations", "factuality"),
        EvidenceItem(
            title="Retrieval grounding and answer factuality",
            finding="Retrieved evidence can improve factual grounding, but irrelevant context may introduce new errors.",
            source="demo://rag-factuality-review",
            strength="medium",
            abstract="Retrieval-grounded generation improved factual accuracy on knowledge-intensive questions when retrieved passages were relevant; noisy retrieval reduced the benefit.",
            claim="Relevant retrieved evidence can improve factual accuracy in generated answers.",
        ),
    ),
    CorpusRecord(
        ("focus", "software", "engineer", "burnout", "delivery", "developer"),
        EvidenceItem(
            title="Developer interruptions, focus, and wellbeing",
            finding="Frequent interruptions are associated with stress and fragmented work, though delivery effects depend on team coordination.",
            source="demo://developer-focus-review",
            strength="medium",
            abstract="Protected focus periods were associated with fewer interruptions and improved self-reported wellbeing among software professionals, with mixed effects on delivery throughput.",
            claim="Protected focus time may improve software-developer wellbeing.",
        ),
    ),
    CorpusRecord(
        ("code", "review", "security", "defect", "vulnerability", "agent"),
        EvidenceItem(
            title="AI-assisted secure code review",
            finding="AI assistance may increase defect recall, while false positives require expert confirmation.",
            source="demo://ai-security-review",
            strength="medium",
            abstract="AI-assisted reviewers identified more seeded security defects than unaided reviewers in a controlled benchmark, but also produced more false-positive findings.",
            claim="AI assistance can increase recall during security code review.",
        ),
    ),
    CorpusRecord(
        ("spaced", "retrieval", "practice", "memory", "certification", "retention"),
        EvidenceItem(
            title="Spaced retrieval and delayed retention",
            finding="Spaced retrieval generally improves delayed recall compared with massed restudy.",
            source="demo://spaced-retrieval-review",
            strength="high",
            abstract="Learners assigned to spaced retrieval practice retained more technical material at delayed testing than learners given massed restudy with equivalent study time.",
            claim="Spaced retrieval practice can improve delayed retention of technical material.",
        ),
    ),
) + tuple(
    CorpusRecord(
        keywords=keywords,
        evidence=EvidenceItem(
            title=title,
            finding=f"Bundled demonstration evidence: {claim}",
            source=f"demo://benchmark-{index + 1}",
            strength="medium",
            abstract=(
                f"A controlled demonstration record reports that {claim} "
                "The effect requires confirmation with domain-specific sources."
            ),
            claim=claim,
        ),
    )
    for index, (keywords, title, claim) in enumerate(ADDITIONAL_DEMO_TOPICS)
)


@tool
def search_demo_corpus(query: str) -> list[dict]:
    """Search the bundled, auditable demonstration evidence corpus."""
    words = set(query.lower().split())
    ranked = sorted(CORPUS, key=lambda row: len(words.intersection(row.keywords)), reverse=True)
    return [row.evidence.model_dump() for row in ranked[:3]]


@tool
def estimate_two_arm_sample_size(effect_size: float, power: float = 0.8) -> int:
    """Estimate total sample size for two equal arms using a transparent approximation."""
    if effect_size <= 0:
        raise ValueError("effect_size must be positive")
    if not 0.5 <= power < 1:
        raise ValueError("power must be between 0.5 and 1")
    z_power = 0.84 if power <= 0.8 else 1.28
    per_arm = math.ceil(2 * ((1.96 + z_power) / effect_size) ** 2)
    return per_arm * 2


@retry(
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.25, max=2),
    reraise=True,
)
def _get_json(url: str, params: dict[str, str | int], timeout: float = 8.0) -> dict:
    headers = {"User-Agent": "ResearchGuard/0.1 (research and education demo)"}
    response = httpx.get(url, params=params, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


@retry(
    retry=retry_if_exception_type(
        (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError)
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.25, max=2),
    reraise=True,
)
def _get_text(url: str, params: dict[str, str | int], timeout: float = 8.0) -> str:
    response = httpx.get(
        url,
        params=params,
        headers={"User-Agent": "ResearchGuard/0.2 (research and education demo)"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.text


def _pubmed_abstracts(ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    xml = _get_text(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"},
    )
    root = ET.fromstring(xml)
    abstracts: dict[str, str] = {}
    for article in root.findall(".//PubmedArticle"):
        pmid = article.findtext(".//PMID")
        sections = ["".join(node.itertext()) for node in article.findall(".//AbstractText")]
        if pmid:
            abstracts[pmid] = " ".join(sections).strip()
    return abstracts


@tool
def search_pubmed(query: str, limit: int = 5) -> list[dict]:
    """Search PubMed and return traceable article metadata. Requires network access."""
    limit = max(1, min(limit, 10))
    search = _get_json(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        {"db": "pubmed", "term": query, "retmode": "json", "retmax": limit},
    )
    ids = search.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    summary = _get_json(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
        {"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
    )
    result = summary.get("result", {})
    abstracts = _pubmed_abstracts(ids)
    return [
        {
            "title": result[pmid].get("title", "Untitled"),
            "finding": "PubMed metadata result; retrieve and review the abstract before making claims.",
            "source": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "identifier": f"PMID:{pmid}",
            "strength": "medium",
            "abstract": abstracts.get(pmid, ""),
            "claim": result[pmid].get("title", ""),
        }
        for pmid in ids
        if pmid in result
    ]


@tool
def search_crossref(query: str, limit: int = 5) -> list[dict]:
    """Search Crossref for scholarly works and DOI-backed citation metadata."""
    params: dict[str, str | int] = {"query": query, "rows": max(1, min(limit, 10))}
    if email := os.getenv("CROSSREF_MAILTO"):
        params["mailto"] = email
    payload = _get_json("https://api.crossref.org/works", params)
    items = payload.get("message", {}).get("items", [])
    return [
        {
            "title": (item.get("title") or ["Untitled"])[0],
            "finding": "Crossref metadata result; full-text claims require source review.",
            "source": item.get("URL") or f"https://doi.org/{item.get('DOI', '')}",
            "identifier": f"DOI:{item.get('DOI')}" if item.get("DOI") else None,
            "strength": "medium",
            "abstract": re.sub(r"<[^>]+>", " ", item.get("abstract", "")).strip(),
            "claim": (item.get("title") or [""])[0],
        }
        for item in items
    ]


@tool
def verify_citation(source: str, identifier: str | None = None) -> dict:
    """Verify that a citation uses an approved source form and has a stable identifier."""
    demo = source.startswith("demo://")
    pubmed = source.startswith("https://pubmed.ncbi.nlm.nih.gov/") and bool(
        identifier and identifier.startswith("PMID:")
    )
    doi = ("doi.org/" in source) and bool(identifier and identifier.startswith("DOI:"))
    return {
        "verified": demo or pubmed or doi,
        "reason": "recognized traceable source"
        if demo or pubmed or doi
        else "missing stable PMID/DOI",
    }


@tool
def verify_claim_support(claim: str, abstract: str) -> dict:
    """Estimate whether an abstract supports a claim and return the closest passage."""
    if not claim.strip() or not abstract.strip():
        return {
            "supported": False,
            "score": 0.0,
            "passage": "",
            "reason": "missing claim or abstract",
        }
    stop = {"the", "a", "an", "and", "or", "to", "of", "in", "for", "with", "is", "are", "can"}
    tokens = lambda text: {
        word
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if word not in stop and len(word) > 2
    }
    claim_tokens = tokens(claim)
    sentences = [value.strip() for value in re.split(r"(?<=[.!?])\s+", abstract) if value.strip()]
    ranked = sorted(
        (
            (len(claim_tokens & tokens(sentence)) / max(len(claim_tokens), 1), sentence)
            for sentence in sentences
        ),
        reverse=True,
    )
    score, passage = ranked[0] if ranked else (0.0, "")
    return {
        "supported": score >= 0.25,
        "score": round(score, 3),
        "passage": passage,
        "reason": "lexical entailment screening; human review required",
    }


def search_corpus(query: str) -> list[EvidenceItem]:
    """Typed adapter used by deterministic agents and tests."""
    return [EvidenceItem.model_validate(item) for item in search_demo_corpus.invoke(query)]
