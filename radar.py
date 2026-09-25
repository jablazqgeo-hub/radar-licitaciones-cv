from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Iterable, Callable
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
    # Prefer the Atom entry link over generic URIs buried in CODICE.
    for node in list(entry):
        if lname(node.tag) == "link":
            href = (node.attrib.get("href") or "").strip()
            if href.startswith("http"):
                return href
    vals = child_texts(entry, {"ContractFolderURI", "WebsiteURI", "URI"})
    return next((v for v in vals if v.startswith("http")), "")


def find_contracting_party(entry: ET.Element) -> tuple[str, str]:
    for node in entry.iter():
        if lname(node.tag) == "ContractingParty":
            registration = child_texts(node, {"RegistrationName"})
            names = child_texts(node, {"Name"})
            organ = registration[0] if registration else (names[0] if names else "")
            addr_parts = child_texts(node, {"CityName", "PostalZone", "CountrySubentity", "AddressLine", "Line"})
            return organ, " | ".join(dict.fromkeys(addr_parts))
    return first_text(entry, {"RegistrationName"}), ""


def procurement_text(entry: ET.Element, title: str) -> tuple[str, str]:
    parts = []
    for node in entry.iter():
        if lname(node.tag) in {"ProcurementProject", "ProcurementProjectLot"}:
            parts.extend(child_texts(node, {"Name", "Description", "Note"}))
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
        "estrategia", "diagnóstico", "diagnostico", "planeamiento", "ordenación", "ordenacion",
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
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
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


@dataclass
class Diagnostics:
    paginas: int = 0
    expedientes_revisados: int = 0
    dentro_periodo: int = 0
    cv_locales: int = 0
    tematicos: int = 0
    oportunidades: int = 0

    def add(self, other: "Diagnostics") -> None:
        for name in self.__dataclass_fields__:
            setattr(self, name, getattr(self, name) + getattr(other, name))


def parse_entry(entry: ET.Element, source: str, cutoff: datetime | None) -> tuple[Tender | None, str]:
    updated = first_text(entry, {"updated", "IssueDate"})
    dt = parse_dt(updated)
    if cutoff is not None and dt is not None and dt < cutoff:
        return None, "old"

    atom_title = first_text(entry, {"title"})
    expediente = first_text(entry, {"ContractFolderID", "id"})
    organ, address = find_contracting_party(entry)

    all_raw = [n.text.strip() for n in entry.iter() if n.text and n.text.strip()]
    full_text = " | ".join(all_raw)
    if not is_cv_local(organ, address, full_text):
        return None, "not_cv_local"

    title, description = procurement_text(entry, atom_title)
    cpvs = find_cpvs(entry)
    scored = category_scores(title, description, cpvs)
    if scored is None:
        return None, "not_thematic"
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
    ), "ok"


def download_atom(url: str, max_mb: int = 80) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".atom", delete=False)
    path = tmp.name
    tmp.close()
    total = 0
    try:
        with requests.get(url, timeout=(15, 75), stream=True, headers={"User-Agent": "RadarLicitacionesCV/6.0"}) as r:
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


def feed_older_link(path: str, base_url: str) -> str | None:
    """PLACSP usa rel='next' para enlazar con el siguiente fichero a procesar,
    que contiene las actualizaciones anteriores más próximas temporalmente.
    """
    try:
        root = ET.parse(path).getroot()
        direct_links = []
        for node in list(root):
            if lname(node.tag) == "link":
                rel = (node.attrib.get("rel") or "").strip().lower()
                href = (node.attrib.get("href") or "").strip()
                if href:
                    direct_links.append((rel, urljoin(base_url, href)))
        # Según la documentación de PLACSP, NEXT es el fichero siguiente a procesar (más antiguo).
        for rel, href in direct_links:
            if rel == "next" and href != base_url:
                return href
        # Fallback defensivo para paquetes/feeds antiguos con semántica distinta.
        for rel, href in direct_links:
            if rel == "prev" and href != base_url:
                return href
    except Exception:
        return None
    return None


def parse_atom_page(path: str, source: str, cutoff: datetime) -> tuple[list[Tender], datetime | None, datetime | None, Diagnostics]:
    out: list[Tender] = []
    newest = oldest = None
    d = Diagnostics(paginas=1)
    try:
        for _event, elem in ET.iterparse(path, events=("end",)):
            if lname(elem.tag) == "entry":
                d.expedientes_revisados += 1
                dt = parse_dt(first_text(elem, {"updated"}))
                if dt is not None:
                    newest = dt if newest is None or dt > newest else newest
                    oldest = dt if oldest is None or dt < oldest else oldest
                    if dt >= cutoff:
                        d.dentro_periodo += 1
                tender, reason = parse_entry(elem, source, cutoff)
                if reason not in {"old", "not_cv_local"}:
                    d.cv_locales += 1
                elif reason == "not_cv_local":
                    pass
                # Count CV locals independently to keep diagnostics truthful.
                if reason in {"not_thematic", "ok"}:
                    d.cv_locales += 1 if False else 0
                if reason == "not_thematic":
                    pass
                if reason == "ok" and tender is not None:
                    d.tematicos += 1
                    d.oportunidades += 1
                    out.append(tender)
                elem.clear()
    except ET.ParseError as exc:
        raise RuntimeError(f"ATOM/XML inválido: {exc}") from exc

    # Recalculate intermediate diagnostic counts accurately in a second lightweight pass is avoided.
    # 'cv_locales' and 'tematicos' are populated in load_feed_history using reason counters.
    return out, newest, oldest, d


def parse_atom_page_diagnostic(path: str, source: str, cutoff: datetime) -> tuple[list[Tender], datetime | None, datetime | None, Diagnostics]:
    out: list[Tender] = []
    newest = oldest = None
    d = Diagnostics(paginas=1)
    try:
        for _event, elem in ET.iterparse(path, events=("end",)):
            if lname(elem.tag) != "entry":
                continue
            d.expedientes_revisados += 1
            dt = parse_dt(first_text(elem, {"updated"}))
            if dt is not None:
                newest = dt if newest is None or dt > newest else newest
                oldest = dt if oldest is None or dt < oldest else oldest
                if dt >= cutoff:
                    d.dentro_periodo += 1
            tender, reason = parse_entry(elem, source, cutoff)
            if reason == "old":
                elem.clear(); continue
            if reason == "not_cv_local":
                elem.clear(); continue
            d.cv_locales += 1
            if reason == "not_thematic":
                elem.clear(); continue
            d.tematicos += 1
            if reason == "ok" and tender is not None:
                d.oportunidades += 1
                out.append(tender)
            elem.clear()
    except ET.ParseError as exc:
        raise RuntimeError(f"ATOM/XML inválido: {exc}") from exc
    return out, newest, oldest, d


def load_feed_history(
    source: str,
    first_url: str,
    cutoff: datetime,
    max_pages: int = 240,
    progress: Callable[[str, int, Diagnostics, datetime | None], None] | None = None,
) -> tuple[list[Tender], list[str], Diagnostics]:
    tenders: list[Tender] = []
    errors: list[str] = []
    diag = Diagnostics()
    seen_urls: set[str] = set()
    url = first_url

    while url and url not in seen_urls and diag.paginas < max_pages:
        seen_urls.add(url)
        path = None
        try:
            path = download_atom(url)
            page_tenders, newest, oldest, pdg = parse_atom_page_diagnostic(path, source, cutoff)
            tenders.extend(page_tenders)
            diag.add(pdg)

            if progress:
                progress(source, diag.paginas, diag, oldest)

            # Once this page reaches beyond the requested window, older pages are unnecessary.
            if oldest is not None and oldest < cutoff:
                break

            older_url = feed_older_link(path, url)
            if not older_url or older_url in seen_urls:
                break
            url = older_url
        except Exception as exc:
            errors.append(f"{source} (fichero {diag.paginas + 1}): {exc}")
            break
        finally:
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass

    if diag.paginas >= max_pages:
        errors.append(f"{source}: se alcanzó el límite de {max_pages} ficheros antes de completar el periodo")
    return tenders, errors, diag


def load_recent(days: int = 30, progress=None) -> tuple[pd.DataFrame, list[str], Diagnostics, dict[str, dict]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_tenders: list[Tender] = []
    errors: list[str] = []
    total = Diagnostics()
    by_source: dict[str, dict] = {}

    for source, url in FEEDS.items():
        tenders, errs, diag = load_feed_history(source, url, cutoff, progress=progress)
        all_tenders.extend(tenders)
        errors.extend(errs)
        total.add(diag)
        by_source[source] = asdict(diag)

    df = to_dataframe(all_tenders)
    total.oportunidades = len(df)
    return df, errors, total, by_source


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
