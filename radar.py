from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Iterable
import xml.etree.ElementTree as ET

import pandas as pd
import requests

from config import CATEGORIES, CPV_PREFIXES, CV_TERMS, LOCAL_BODY_TERMS

FEEDS = {
    "PLACSP - perfiles": "https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3.atom",
    "PLACSP - agregadas": "https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_1044/PlataformasAgregadasSinMenores.atom",
}


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
    vals = child_texts(elem, set(names))
    return vals[0] if vals else ""


def find_amount(entry: ET.Element) -> str:
    for node in entry.iter():
        if lname(node.tag).lower() in {"taxexclusiveamount", "estimatedoverallcontractamount", "totalamount"}:
            txt = (node.text or "").strip()
            if txt:
                return f"{txt} {node.attrib.get('currencyID', 'EUR')}"
    return ""


def find_cpvs(entry: ET.Element) -> list[str]:
    vals = []
    for node in entry.iter():
        if lname(node.tag).lower() in {"itemclassificationcode", "classificationcode"}:
            txt = (node.text or "").strip()
            if txt and re.search(r"\d{4,8}", txt):
                vals.append(txt)
    return list(dict.fromkeys(vals))


def find_deadline(entry: ET.Element) -> str:
    for node in entry.iter():
        if lname(node.tag) in {"TenderSubmissionDeadlinePeriod", "TenderSubmissionDeadline"}:
            d = first_text(node, {"EndDate", "Date"})
            t = first_text(node, {"EndTime", "Time"})
            if d:
                return f"{d} {t}".strip()
    return first_text(entry, {"EndDate"})


def find_link(entry: ET.Element) -> str:
    for node in entry.iter():
        if lname(node.tag) == "link":
            href = node.attrib.get("href")
            if href and href.startswith("http"):
                return href
    vals = child_texts(entry, {"URI", "WebsiteURI", "ContractFolderURI"})
    return next((v for v in vals if v.startswith("http")), "")


def category_scores(text: str, cpvs: list[str]) -> tuple[list[str], int, str]:
    t = norm(text)
    matches, matched_terms = [], []
    score = 0
    for cat, cfg in CATEGORIES.items():
        found = [kw for kw in cfg["keywords"] if norm(kw) in t]
        if found:
            matches.append(cat)
            matched_terms.extend(found[:5])
            score += min(36, 18 + 6 * (len(found) - 1))
    if any(any(re.sub(r"\D", "", cpv).startswith(prefix) for prefix in CPV_PREFIXES) for cpv in cpvs):
        score += 10
    intent_terms = ["plan", "estrategia", "estudio", "asistencia tecnica", "consultoria", "redaccion", "elaboracion", "diagnostico"]
    score += min(18, sum(1 for x in intent_terms if x in t) * 4)
    if any(x in t for x in ["ejecucion de obras", "obra de", "suministro de"]) and not any(x in t for x in ["asistencia tecnica", "consultoria", "redaccion", "elaboracion"]):
        score -= 15
    return matches, max(0, min(100, score)), ", ".join(dict.fromkeys(matched_terms))


def _province_from_postcode(text: str) -> str:
    codes = re.findall(r"(?<!\d)(?:03|12|46)\d{3}(?!\d)", text or "")
    if not codes:
        return ""
    return {"03": "Alicante", "12": "Castellón", "46": "Valencia"}.get(codes[0][:2], "")


def is_cv_local(text: str) -> bool:
    t = norm(text)
    cv = any(norm(x) in t for x in CV_TERMS) or bool(_province_from_postcode(text))
    local = any(norm(x) in t for x in LOCAL_BODY_TERMS)
    return cv and local


def guess_province(text: str) -> str:
    by_pc = _province_from_postcode(text)
    if by_pc:
        return by_pc
    t = norm(text)
    if "alicante" in t or "alacant" in t: return "Alicante"
    if "castellon" in t or "castello" in t: return "Castellón"
    if "valencia" in t: return "Valencia"
    return "Sin determinar"


def parse_dt(s: str):
    if not s: return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        try: return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception: return None


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


def parse_entry(entry: ET.Element, source: str, cutoff: datetime | None) -> Tender | None:
    updated = first_text(entry, {"updated", "IssueDate"})
    dt = parse_dt(updated)
    if cutoff is not None and dt is not None:
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        if dt < cutoff: return None

    title = first_text(entry, {"title", "Name"})
    expediente = first_text(entry, {"ContractFolderID", "ID", "id"})
    organ = first_text(entry, {"PartyName", "RegistrationName"})
    raw_texts = [n.text.strip() for n in entry.iter() if n.text and n.text.strip()]
    full_text = " | ".join(raw_texts)
    geography = f"{organ} {full_text}"
    if not is_cv_local(geography): return None
    cpvs = find_cpvs(entry)
    cats, score, terms = category_scores(f"{title} {full_text}", cpvs)
    if not cats: return None
    return Tender(expediente, title, organ, guess_province(geography), updated, find_deadline(entry), find_amount(entry), ", ".join(cpvs), "; ".join(cats), score, terms, find_link(entry), source, full_text[:8000])


def download_atom(url: str, max_mb: int = 160) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".atom", delete=False)
    path = tmp.name
    tmp.close()
    total = 0
    try:
        with requests.get(url, timeout=(15, 90), stream=True, headers={"User-Agent": "RadarLicitacionesCV/3.0"}) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(1024 * 1024):
                    if not chunk: continue
                    total += len(chunk)
                    if total > max_mb * 1024 * 1024:
                        raise RuntimeError(f"El feed supera {max_mb} MB; se cancela para evitar bloquear la app")
                    f.write(chunk)
        return path
    except Exception:
        try: os.remove(path)
        except OSError: pass
        raise


def parse_atom_path(path: str, source: str, cutoff: datetime | None) -> list[Tender]:
    out = []
    try:
        for _event, elem in ET.iterparse(path, events=("end",)):
            if lname(elem.tag) == "entry":
                try:
                    t = parse_entry(elem, source, cutoff)
                    if t is not None: out.append(t)
                finally:
                    elem.clear()
    except ET.ParseError:
        pass
    return out


def load_recent(days: int = 30) -> tuple[pd.DataFrame, list[str]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_tenders, errors = [], []
    for source, url in FEEDS.items():
        path = None
        try:
            path = download_atom(url)
            all_tenders.extend(parse_atom_path(path, source, cutoff))
        except Exception as exc:
            errors.append(f"{source}: {exc}")
        finally:
            if path:
                try: os.remove(path)
                except OSError: pass
    return to_dataframe(all_tenders), errors


def to_dataframe(tenders: list[Tender]) -> pd.DataFrame:
    cols = list(Tender.__dataclass_fields__.keys())
    if not tenders: return pd.DataFrame(columns=cols)
    df = pd.DataFrame([asdict(x) for x in tenders])
    df["_key"] = df["expediente"].fillna("").astype(str).str.strip()
    empty = df["_key"].eq("")
    df.loc[empty, "_key"] = df.loc[empty, "titulo"].fillna("") + "|" + df.loc[empty, "organo"].fillna("")
    df["_updated"] = pd.to_datetime(df["fecha_actualizacion"], errors="coerce", utc=True)
    df = df.sort_values("_updated").drop_duplicates("_key", keep="last")
    return df.drop(columns=["_key", "_updated"]).reset_index(drop=True)
