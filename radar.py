from __future__ import annotations

import io
import os
import re
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass, asdict
from typing import Iterable, Callable
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
    out: list[str] = []
    for node in elem.iter():
        if lname(node.tag) in wanted and node.text and node.text.strip():
            out.append(node.text.strip())
    return out


def first_text(elem: ET.Element, names: Iterable[str]) -> str:
    vals = child_texts(elem, set(names))
    return vals[0] if vals else ""


def find_amount(entry: ET.Element) -> str:
    for node in entry.iter():
        n = lname(node.tag).lower()
        if n in {"taxexclusiveamount", "estimatedoverallcontractamount", "totalamount"}:
            txt = (node.text or "").strip()
            if txt:
                return f"{txt} {node.attrib.get('currencyID', 'EUR')}"
    return ""


def find_cpvs(entry: ET.Element) -> list[str]:
    vals: list[str] = []
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
    for node in entry.iter():
        if lname(node.tag) == "link":
            href = node.attrib.get("href")
            if href and href.startswith("http"):
                return href
    vals = child_texts(entry, {"URI", "WebsiteURI", "ContractFolderURI"})
    return next((v for v in vals if v.startswith("http")), "")


def category_scores(text: str, cpvs: list[str]) -> tuple[list[str], int, str]:
    t = norm(text)
    matches: list[str] = []
    matched_terms: list[str] = []
    score = 0

    for cat, cfg in CATEGORIES.items():
        found = [kw for kw in cfg["keywords"] if norm(kw) in t]
        if found:
            matches.append(cat)
            matched_terms.extend(found[:5])
            score += min(36, 18 + 6 * (len(found) - 1))

    if any(
        any(re.sub(r"\D", "", cpv).startswith(prefix) for prefix in CPV_PREFIXES)
        for cpv in cpvs
    ):
        score += 10

    intent_terms = [
        "plan", "estrategia", "estudio", "asistencia tecnica", "consultoria",
        "redaccion", "elaboracion", "diagnostico"
    ]
    intent_hits = sum(1 for x in intent_terms if x in t)
    score += min(18, intent_hits * 4)

    works_terms = ["ejecucion de obras", "obra de", "suministro de"]
    service_terms = ["asistencia tecnica", "consultoria", "redaccion", "elaboracion"]
    if any(x in t for x in works_terms) and not any(x in t for x in service_terms):
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


def parse_entry(entry: ET.Element, source: str) -> Tender | None:
    title = first_text(entry, {"title", "Name"})
    expediente = first_text(entry, {"ContractFolderID", "ID", "id"})
    updated = first_text(entry, {"updated", "IssueDate"})
    organ = first_text(entry, {"PartyName", "RegistrationName"})

    # Gather text only for this one entry; unlike ET.fromstring, this keeps memory bounded.
    raw_texts = [
        node.text.strip()
        for node in entry.iter()
        if node.text and node.text.strip()
    ]
    full_text = " | ".join(raw_texts)
    geography_text = f"{organ} {full_text}"
    if not is_cv_local(geography_text):
        return None

    cpvs = find_cpvs(entry)
    cats, score, terms = category_scores(f"{title} {full_text}", cpvs)
    if not cats:
        return None

    return Tender(
        expediente=expediente,
        titulo=title,
        organo=organ,
        provincia=guess_province(geography_text),
        fecha_actualizacion=updated,
        fecha_limite=find_deadline(entry),
        presupuesto=find_amount(entry),
        cpv=", ".join(cpvs),
        categorias="; ".join(cats),
        relevancia=score,
        coincidencias=terms,
        enlace=find_link(entry),
        fuente=source,
        texto=full_text[:8000],
    )


def parse_xml_stream(fileobj, source: str) -> list[Tender]:
    """Parse Atom/XML incrementally instead of loading the whole national file in RAM."""
    tenders: list[Tender] = []
    try:
        context = ET.iterparse(fileobj, events=("end",))
        for _event, elem in context:
            if lname(elem.tag) == "entry":
                try:
                    tender = parse_entry(elem, source)
                    if tender is not None:
                        tenders.append(tender)
                finally:
                    elem.clear()
    except ET.ParseError:
        return tenders
    return tenders


def parse_zip_path(path: str, source: str) -> list[Tender]:
    out: list[Tender] = []
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if not name.lower().endswith((".atom", ".xml")):
                continue
            try:
                with zf.open(name) as fh:
                    out.extend(parse_xml_stream(fh, source=f"{source}: {name}"))
            except Exception:
                continue
    return out


def parse_zip_bytes(data: bytes, source: str) -> list[Tender]:
    # Used for manual uploads; still parses each XML as a stream.
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        return parse_zip_path(path, source)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def download_zip_to_temp(url: str, timeout: int = 180) -> str:
    """Stream a large ZIP to disk to avoid holding the whole national dataset in memory."""
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    path = tmp.name
    tmp.close()
    try:
        with requests.get(
            url,
            timeout=(20, timeout),
            stream=True,
            headers={"User-Agent": "RadarLicitacionesCV/2.0"},
        ) as r:
            r.raise_for_status()
            with open(path, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        fh.write(chunk)
        return path
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        raise


def month_urls(year: int, month: int) -> dict[str, str]:
    yyyymm = f"{year}{month:02d}"
    return {
        "PLACSP - perfiles": f"https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3_{yyyymm}.zip",
        "PLACSP - agregadas": f"https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_1044/PlataformasAgregadasSinMenores_{yyyymm}.zip",
    }


def load_month(year: int, month: int, status_cb: Callable[[str], None] | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Download/process sources one by one and return only the small filtered CV dataset."""
    all_tenders: list[Tender] = []
    errors: list[str] = []

    for source, url in month_urls(year, month).items():
        path = None
        try:
            if status_cb:
                status_cb(f"Descargando {source}…")
            path = download_zip_to_temp(url)
            if status_cb:
                status_cb(f"Analizando {source} y filtrando Comunitat Valenciana…")
            all_tenders.extend(parse_zip_path(path, source))
        except Exception as exc:
            errors.append(f"{source}: {exc}")
        finally:
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass

    return to_dataframe(all_tenders), errors


def to_dataframe(tenders: list[Tender]) -> pd.DataFrame:
    cols = list(Tender.__dataclass_fields__.keys())
    if not tenders:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame([asdict(x) for x in tenders])
    df["_key"] = df["expediente"].fillna("").astype(str).str.strip()
    empty = df["_key"].eq("")
    df.loc[empty, "_key"] = (
        df.loc[empty, "titulo"].fillna("") + "|" + df.loc[empty, "organo"].fillna("")
    )
    df = df.sort_values(["fecha_actualizacion", "relevancia"], ascending=[False, False])
    return df.drop_duplicates("_key", keep="first").drop(columns="_key")
