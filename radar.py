from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

import pandas as pd
import requests

from config import (
    CATEGORIES, CPV_PREFIXES, CV_TERMS, LOCAL_BODY_TERMS,
    PLANNING_INTENT_TERMS, STRONG_PLAN_TERMS, NEGATIVE_TITLE_TERMS,
)

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


def find_contracting_party(entry: ET.Element) -> tuple[str, str]:
    for node in entry.iter():
        if lname(node.tag) == "ContractingParty":
            names = []
            for sub in node.iter():
                if lname(sub.tag) in {"RegistrationName", "Name"} and sub.text and sub.text.strip():
                    names.append(sub.text.strip())
            organ = names[0] if names else ""
            addr_parts = child_texts(node, {"CityName", "PostalZone", "CountrySubentity", "AddressLine", "Line"})
            return organ, " | ".join(addr_parts)
    return first_text(entry, {"RegistrationName"}), ""


def procurement_text(entry: ET.Element, title: str) -> tuple[str, str]:
    parts = []
    # El objeto contractual vive normalmente en ProcurementProject / Lot.
    for node in entry.iter():
        if lname(node.tag) in {"ProcurementProject", "ProcurementProjectLot"}:
            parts.extend(child_texts(node, {"Name", "Description", "Note"}))
    # Fallbacks de Atom/CODICE útiles sin incorporar todo el XML.
    parts.extend(child_texts(entry, {"summary"}))
    cleaned, seen = [], set()
    for p in parts:
        k = norm(p)
        if k and k not in seen:
            seen.add(k)
            cleaned.append(p)
    return title, " | ".join(cleaned)


def category_scores(title: str, description: str, cpvs: list[str]) -> tuple[list[str], int, str] | None:
    t_title = norm(title)
    t_desc = norm(description)
    combined = f"{t_title} {t_desc}"

    title_negative = [x for x in NEGATIVE_TITLE_TERMS if norm(x) in t_title]
    strong_service = any(norm(x) in t_title for x in [
        "asistencia técnica", "asistencia tecnica", "consultoría", "consultoria",
        "redacción", "redaccion", "elaboración", "elaboracion", "estudio de", "plan de",
        "estrategia", "diagnóstico", "diagnostico",
    ])
    if title_negative and not strong_service:
        return None

    categories, matched_terms = [], []
    score = 0
    for cat, cfg in CATEGORIES.items():
        found_title = [kw for kw in cfg["keywords"] if norm(kw) in t_title]
        found_desc = [kw for kw in cfg["keywords"] if norm(kw) in t_desc]
        if found_title or found_desc:
            categories.append(cat)
            for kw in found_title + found_desc:
                if kw not in matched_terms:
                    matched_terms.append(kw)
            if found_title:
                score += min(48, 32 + 6 * (len(found_title) - 1))
            else:
                score += min(32, 20 + 4 * (len(found_desc) - 1))

    if not categories:
        return None

    intent_title = [x for x in PLANNING_INTENT_TERMS if norm(x) in t_title]
    intent_desc = [x for x in PLANNING_INTENT_TERMS if norm(x) in t_desc]
    strong_plan = [x for x in STRONG_PLAN_TERMS if norm(x) in combined]

    # Exigimos intención de planificación, salvo que aparezca un instrumento inequívoco.
    if not intent_title and not intent_desc and not strong_plan:
        return None

    if intent_title:
        score += min(30, 20 + 4 * (len(intent_title) - 1))
    elif intent_desc:
        score += min(18, 12 + 2 * (len(intent_desc) - 1))
    if strong_plan:
        score += min(22, 14 + 4 * (len(strong_plan) - 1))

    digits = [re.sub(r"\D", "", cpv) for cpv in cpvs]
    if any(any(c.startswith(prefix) for prefix in CPV_PREFIXES) for c in digits):
        score += 10

    score -= min(35, 20 * len(title_negative))
    return categories, max(0, min(100, score)), ", ".join(dict.fromkeys(matched_terms[:8]))


def _province_from_postcode(text: str) -> str:
    codes = re.findall(r"(?<!\d)(?:03|12|46)\d{3}(?!\d)", text or "")
    if not codes:
        return ""
    return {"03": "Alicante", "12": "Castellón", "46": "Valencia"}.get(codes[0][:2], "")


def is_cv_local(organ: str, address: str, full_text: str) -> bool:
    local_text = f"{organ} {full_text}"
    geo_text = f"{address} {organ} {full_text}"
    t_geo, t_local = norm(geo_text), norm(local_text)
    cv = any(norm(x) in t_geo for x in CV_TERMS) or bool(_province_from_postcode(geo_text))
    local = any(norm(x) in t_local for x in LOCAL_BODY_TERMS)
    return cv and local


def guess_province(address: str, organ: str, title: str, full_text: str) -> str:
    for source in [address, organ, title, full_text]:
        by_pc = _province_from_postcode(source)
        if by_pc:
            return by_pc
        t = norm(source)
        if "alicante" in t or "alacant" in t:
            return "Alicante"
        if "castellon" in t or "castello" in t:
            return "Castellón"
        if "valencia" in t:
            return "Valencia"
    return "Sin determinar"


def parse_dt(s: str):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            return None


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
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt < cutoff:
            return None

    atom_title = first_text(entry, {"title"})
    expediente = first_text(entry, {"ContractFolderID", "id"})
    organ, address = find_contracting_party(entry)

    all_raw = [n.text.strip() for n in entry.iter() if n.text and n.text.strip()]
    full_text = " | ".join(all_raw)
    if not is_cv_local(organ, address, full_text):
        return None

    title, description = procurement_text(entry, atom_title)
    cpvs = find_cpvs(entry)
    scored = category_scores(title, description, cpvs)
    if scored is None:
        return None
    cats, score, terms = scored

    return Tender(
        expediente=expediente,
        titulo=title,
        organo=organ or "Sin identificar",
        provincia=guess_province(address, organ, title, full_text),
        fecha_actualizacion=updated,
        fecha_limite=find_deadline(entry),
        presupuesto=find_amount(entry),
        cpv=", ".join(cpvs),
        categorias="; ".join(cats),
        relevancia=score,
        coincidencias=terms,
        enlace=find_link(entry),
        fuente=source,
        texto=f"{title} | {description}"[:8000],
    )


def download_atom(url: str, max_mb: int = 80) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".atom", delete=False)
    path = tmp.name
    tmp.close()
    total = 0
    try:
        with requests.get(url, timeout=(15, 75), stream=True, headers={"User-Agent": "RadarLicitacionesCV/5.0"}) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_mb * 1024 * 1024:
                        raise RuntimeError(f"El fichero supera {max_mb} MB")
                    f.write(chunk)
        return path
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        raise


def feed_prev_link(path: str, base_url: str) -> str | None:
    try:
        root = ET.parse(path).getroot()
        # Solo links hijos directos del feed; no enlaces de cada entry.
        for node in list(root):
            if lname(node.tag) == "link" and node.attrib.get("rel") == "prev":
                href = (node.attrib.get("href") or "").strip()
                if href:
                    return urljoin(base_url, href)
    except Exception:
        return None
    return None


def page_date_range(path: str) -> tuple[datetime | None, datetime | None]:
    newest = oldest = None
    try:
        for _event, elem in ET.iterparse(path, events=("end",)):
            if lname(elem.tag) == "entry":
                dt = parse_dt(first_text(elem, {"updated"}))
                if dt is not None:
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    newest = dt if newest is None or dt > newest else newest
                    oldest = dt if oldest is None or dt < oldest else oldest
                elem.clear()
    except ET.ParseError:
        pass
    return newest, oldest


def parse_atom_path(path: str, source: str, cutoff: datetime | None) -> list[Tender]:
    out = []
    try:
        for _event, elem in ET.iterparse(path, events=("end",)):
            if lname(elem.tag) == "entry":
                try:
                    t = parse_entry(elem, source, cutoff)
                    if t is not None:
                        out.append(t)
                finally:
                    elem.clear()
    except ET.ParseError:
        pass
    return out


def load_feed_history(source: str, first_url: str, cutoff: datetime, max_pages: int = 180) -> tuple[list[Tender], list[str], int]:
    """Recorre rel=prev desde el feed más reciente hasta cubrir cutoff."""
    tenders, errors = [], []
    seen_urls = set()
    url = first_url
    pages = 0

    while url and url not in seen_urls and pages < max_pages:
        seen_urls.add(url)
        path = None
        try:
            path = download_atom(url)
            pages += 1
            newest, oldest = page_date_range(path)
            tenders.extend(parse_atom_path(path, source, cutoff))
            prev_url = feed_prev_link(path, url)

            # Si la página ya cruza la fecha de corte, no necesitamos páginas más antiguas.
            if oldest is not None and oldest < cutoff:
                break
            if not prev_url:
                break
            url = prev_url
        except Exception as exc:
            errors.append(f"{source} (página {pages + 1}): {exc}")
            break
        finally:
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass

    if pages >= max_pages:
        errors.append(f"{source}: se alcanzó el límite de {max_pages} páginas antes de completar todo el periodo")
    return tenders, errors, pages


def load_recent(days: int = 30) -> tuple[pd.DataFrame, list[str], int]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_tenders, errors = [], []
    total_pages = 0
    for source, url in FEEDS.items():
        tenders, errs, pages = load_feed_history(source, url, cutoff)
        all_tenders.extend(tenders)
        errors.extend(errs)
        total_pages += pages
    return to_dataframe(all_tenders), errors, total_pages


def to_dataframe(tenders: list[Tender]) -> pd.DataFrame:
    cols = list(Tender.__dataclass_fields__.keys())
    if not tenders:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame([asdict(x) for x in tenders])
    df["_key"] = df["expediente"].fillna("").astype(str).str.strip()
    empty = df["_key"].eq("")
    df.loc[empty, "_key"] = df.loc[empty, "titulo"].fillna("") + "|" + df.loc[empty, "organo"].fillna("")
    df["_updated"] = pd.to_datetime(df["fecha_actualizacion"], errors="coerce", utc=True)
    df = df.sort_values("_updated").drop_duplicates("_key", keep="last")
    return df.drop(columns=["_key", "_updated"]).reset_index(drop=True)
