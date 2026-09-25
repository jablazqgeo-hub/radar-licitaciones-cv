from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Iterable
import xml.etree.ElementTree as ET

import pandas as pd
import requests

from config import CATEGORIES, CPV_PREFIXES, CV_TERMS, LOCAL_BODY_TERMS


def norm(text: str | None) -> str:
    text = text or ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    return re.sub(r"\s+", " ", text).strip()


def lname(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def child_texts(elem: ET.Element, wanted: set[str]) -> list[str]:
    out = []
    for node in elem.iter():
        if lname(node.tag) in wanted and node.text and node.text.strip():
            out.append(node.text.strip())
    return out


def first_text(elem: ET.Element, names: Iterable[str]) -> str:
    names = set(names)
    vals = child_texts(elem, names)
    return vals[0] if vals else ""


def find_amount(entry: ET.Element) -> str:
    candidates = []
    for node in entry.iter():
        n = lname(node.tag).lower()
        if n in {"taxexclusiveamount", "estimatedoverallcontractamount", "totalamount"}:
            txt = (node.text or "").strip()
            if txt:
                currency = node.attrib.get("currencyID", "EUR")
                candidates.append(f"{txt} {currency}")
    return candidates[0] if candidates else ""


def find_cpvs(entry: ET.Element) -> list[str]:
    vals = []
    for node in entry.iter():
        n = lname(node.tag).lower()
        if n in {"itemclassificationcode", "classificationcode"}:
            txt = (node.text or "").strip()
            if txt and re.search(r"\d{4,8}", txt):
                vals.append(txt)
    return list(dict.fromkeys(vals))


def find_deadline(entry: ET.Element) -> str:
    for node in entry.iter():
        if lname(node.tag) in {"TenderSubmissionDeadlinePeriod", "TenderSubmissionDeadline"}:
            date = first_text(node, {"EndDate", "Date"})
            time = first_text(node, {"EndTime", "Time"})
            if date:
                return f"{date} {time}".strip()
    return first_text(entry, {"EndDate"})


def find_link(entry: ET.Element) -> str:
    # Atom links
    for node in entry.iter():
        if lname(node.tag) == "link":
            href = node.attrib.get("href")
            if href and "http" in href:
                return href
    # CODICE / URI fields
    vals = child_texts(entry, {"URI", "WebsiteURI", "ContractFolderURI"})
    return next((v for v in vals if v.startswith("http")), "")


def category_scores(text: str, cpvs: list[str]) -> tuple[list[str], int, str]:
    t = norm(text)
    matches = []
    matched_terms = []
    score = 0

    for cat, cfg in CATEGORIES.items():
        found = []
        for kw in cfg["keywords"]:
            nkw = norm(kw)
            if nkw and nkw in t:
                found.append(kw)
        if found:
            matches.append(cat)
            matched_terms.extend(found[:5])
            # Strong reward for exact thematic language; capped per category.
            score += min(36, 18 + 6 * (len(found) - 1))

    if any(any(re.sub(r"\D", "", cpv).startswith(prefix) for prefix in CPV_PREFIXES) for cpv in cpvs):
        score += 10

    # Extra relevance when the object looks like a study/plan/strategy/technical assistance.
    intent_terms = [
        "plan", "estrategia", "estudio", "asistencia tecnica", "consultoria", "consultoría",
        "redaccion", "redacción", "elaboracion", "elaboración", "diagnostico", "diagnóstico"
    ]
    intent_hits = sum(1 for x in intent_terms if norm(x) in t)
    score += min(18, intent_hits * 4)

    # Reduce false positives from construction-only tenders.
    works_terms = ["ejecucion de obras", "ejecución de obras", "obra de", "suministro de"]
    if any(norm(x) in t for x in works_terms) and not any(norm(x) in t for x in ["asistencia tecnica", "consultoria", "redaccion", "elaboracion"]):
        score -= 15

    return matches, max(0, min(100, score)), ", ".join(dict.fromkeys(matched_terms))


def _province_from_postcode(text: str) -> str:
    # Spanish postal codes begin with the province code: 03 Alicante, 12 Castellon, 46 Valencia.
    codes = re.findall(r"(?<!\d)(?:03|12|46)\d{3}(?!\d)", text or "")
    if not codes:
        return ""
    prefix = codes[0][:2]
    return {"03": "Alicante", "12": "Castellón", "46": "Valencia"}.get(prefix, "")


def is_cv_local(text: str) -> bool:
    t = norm(text)
    cv = any(norm(x) in t for x in CV_TERMS) or bool(_province_from_postcode(text))
    local = any(norm(x) in t for x in LOCAL_BODY_TERMS)
    return cv and local


def guess_province(text: str) -> str:
    by_postcode = _province_from_postcode(text)
    if by_postcode:
        return by_postcode
    t = norm(text)
    if "alicante" in t or "alacant" in t:
        return "Alicante"
    if "castellon" in t or "castello" in t:
        return "Castellón"
    if "valencia" in t:
        return "Valencia"
    return "Sin determinar"


@dataclass
class Tender:
    expediente: str
    titulo: str
    organo: str
    provincia: str
    fecha_actualizacion: str
    fecha_limite: str
    presupuesto: str
    cpv: str
    categorias: str
    relevancia: int
    coincidencias: str
    enlace: str
    fuente: str
    texto: str


def parse_atom(xml_bytes: bytes, source: str = "PLACSP") -> list[Tender]:
    root = ET.fromstring(xml_bytes)
    entries = [x for x in root.iter() if lname(x.tag) == "entry"]
    tenders: list[Tender] = []

    for entry in entries:
        title = first_text(entry, {"title", "Name"})
        expediente = first_text(entry, {"ContractFolderID", "ID", "id"})
        updated = first_text(entry, {"updated", "IssueDate"})
        organ = first_text(entry, {"PartyName", "RegistrationName"})
        cpvs = find_cpvs(entry)
        deadline = find_deadline(entry)
        amount = find_amount(entry)
        link = find_link(entry)

        # Keep all textual values to make the classifier tolerant of schema changes.
        raw_texts = []
        for node in entry.iter():
            if node.text and node.text.strip():
                raw_texts.append(node.text.strip())
        full_text = " | ".join(raw_texts)

        # If PartyName is absent or ambiguous, the title/full text still participates in geographic filtering.
        geography_text = f"{organ} {full_text}"
        if not is_cv_local(geography_text):
            continue

        cats, score, terms = category_scores(f"{title} {full_text}", cpvs)
        if not cats:
            continue

        tenders.append(Tender(
            expediente=expediente,
            titulo=title,
            organo=organ,
            provincia=guess_province(geography_text),
            fecha_actualizacion=updated,
            fecha_limite=deadline,
            presupuesto=amount,
            cpv=", ".join(cpvs),
            categorias="; ".join(cats),
            relevancia=score,
            coincidencias=terms,
            enlace=link,
            fuente=source,
            texto=full_text[:12000],
        ))
    return tenders


def parse_zip_bytes(data: bytes, source: str) -> list[Tender]:
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            if name.lower().endswith((".atom", ".xml")):
                try:
                    out.extend(parse_atom(zf.read(name), source=f"{source}: {name}"))
                except Exception:
                    # A malformed or auxiliary XML should not stop the whole import.
                    continue
    return out


def download_zip(url: str, timeout: int = 90) -> bytes:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "RadarLicitacionesCV/1.0"})
    r.raise_for_status()
    return r.content


def month_urls(year: int, month: int) -> dict[str, str]:
    yyyymm = f"{year}{month:02d}"
    return {
        "PLACSP - perfiles": f"https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3_{yyyymm}.zip",
        "PLACSP - agregadas": f"https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_1044/PlataformasAgregadasSinMenores_{yyyymm}.zip",
    }


def to_dataframe(tenders: list[Tender]) -> pd.DataFrame:
    if not tenders:
        return pd.DataFrame(columns=[f.name for f in Tender.__dataclass_fields__.values()])
    df = pd.DataFrame([asdict(x) for x in tenders])
    # Deduplicate updates. expediente is best; use title+organ when not available.
    df["_key"] = df["expediente"].fillna("").astype(str).str.strip()
    empty = df["_key"].eq("")
    df.loc[empty, "_key"] = df.loc[empty, "titulo"].fillna("") + "|" + df.loc[empty, "organo"].fillna("")
    df = df.sort_values(["fecha_actualizacion", "relevancia"], ascending=[False, False])
    df = df.drop_duplicates("_key", keep="first").drop(columns="_key")
    return df
