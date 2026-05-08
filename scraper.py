"""
JobCI Scraper — Ciência da Informação (Portugal)
=================================================
Fontes:
  A) JobSpy  → Indeed Portugal + Google Jobs (queries gerais)
  B) BAD     → bad.pt/bolsa-de-emprego/ (HTML estático, raspável)
  C) BEP     → bep.gov.pt (API JSON pública do portal)
  D) Apply UP → app.apply.up.pt (HTML estático)
  E) CM Porto → cm-porto.pt (HTML, secção RH)

Requisitos: pip install python-jobspy==1.1.79 pandas requests beautifulsoup4 lxml
"""

import json
import hashlib
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
    import pandas as pd
    from jobspy import scrape_jobs
except ImportError:
    raise SystemExit(
        "Instala dependências:\n"
        "  pip install python-jobspy==1.1.79 pandas requests beautifulsoup4 lxml"
    )

# ═══════════════════════════════════════════════════════════
#  CONFIGURAÇÃO
# ═══════════════════════════════════════════════════════════

OUTPUT_PATH = Path("data/jobs.json")
TODAY = datetime.now(timezone.utc)
TODAY_STR = TODAY.strftime("%Y-%m-%d")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
}

# ── JobSpy queries ──────────────────────────────────────────
SEARCH_QUERIES = [
    # Títulos clássicos Portugal
    '"gestão da informação" OR "gestor de informação" Portugal',
    '"gestão documental" OR "gestão de documentos" OR "gestão de arquivo"',
    'arquivista OR "técnico de arquivo" OR "técnico superior documentação"',
    '"técnico superior" arquivo OR documentação OR biblioteca Portugal',
    # Biblioteconomia
    '"bibliotecário" OR "gestão de coleções" OR "serviços de informação"',
    '"literacia da informação" OR "biblioteca universitária" OR "biblioteca pública"',
    # Setor privado / empresarial
    '"knowledge manager" OR "knowledge management" Portugal',
    '"information manager" OR "gestão da informação" empresa Portugal',
    '"enterprise content management" OR ECM Portugal',
    '"records management" OR "records manager" Portugal',
    '"compliance" "gestão documental" OR "proteção de dados" Portugal',
    'RGPD "gestão de informação" OR "oficial de proteção de dados"',
    # Dados e investigação
    '"data steward" OR "curador de dados" OR "data curation" Portugal',
    '"administrador de dados" OR "analista de informação" Portugal',
    '"auditor de informação" OR "information audit" Portugal',
    # Humanidades Digitais / Preservação
    '"humanidades digitais" OR "preservação digital" OR "digital preservation"',
    '"metadados" OR "metadata" OR "Dublin Core" OR "linked data" Portugal',
    # UX / Arquitetura
    '"arquitetura de informação" OR "UX researcher" OR "information architect"',
    '"taxonomia" OR "ontologia" OR "content strategy" Portugal',
    # Concursos públicos
    '"concurso público" arquivo OR documentação OR biblioteca Portugal',
    'DGLAB OR BAD emprego arquivo biblioteca documentação',
]

JOBSPY_SITES   = ["indeed", "google"]
RESULTS_WANTED = 15
HOURS_OLD      = 72


# ── Palavras-chave para filtrar relevância ──────────────────
RELEVANT_KEYWORDS = [
    "informação", "information", "arquivo", "archivist", "arquivista",
    "documental", "documentação", "documentation", "bibliotec",
    "knowledge", "dados", "data steward", "records", "content",
    "digital preservation", "metadata", "metadados", "ux researcher",
    "ciência da informação", "gestor", "gestão", "analyst", "analista",
    "humanidades digitais", "digital humanities", "curador", "curator",
    "taxonomia", "ontologia", "compliance", "rgpd", "gdpr", "ecm",
    "dirigente", "assistente técnico", "técnico superior",
]

# ── Mapeamentos ─────────────────────────────────────────────
AREA_MAP = {
    "arquivo": "Arquivo", "archivist": "Arquivo",
    "documental": "Arquivo", "documentação": "Arquivo", "records": "Arquivo",
    "bibliotec": "Biblioteca", "librarian": "Biblioteca",
    "knowledge": "Gestão da Informação",
    "gestor de informação": "Gestão da Informação",
    "gestão da informação": "Gestão da Informação",
    "information manager": "Gestão da Informação",
    "ecm": "Gestão da Informação", "content manager": "Gestão da Informação",
    "compliance": "Gestão da Informação", "rgpd": "Gestão da Informação",
    "data steward": "Dados", "curador de dados": "Dados",
    "data curation": "Dados", "administrador de dados": "Dados",
    "analista": "Dados", "analyst": "Dados",
    "digital preservation": "Digital", "preservação digital": "Digital",
    "humanidades digitais": "Digital", "digital humanities": "Digital",
    "metadados": "Digital", "metadata": "Digital",
    "ux": "UX", "arquitetura de informação": "UX",
    "information architect": "UX", "taxonomia": "UX",
}

LOCATION_MAP = {
    "porto": "Porto", "lisboa": "Lisboa", "lisbon": "Lisboa",
    "braga": "Braga", "coimbra": "Coimbra",
    "brasil": "Brasil", "brazil": "Brasil",
    "bruxelas": "Internacional", "brussels": "Internacional",
    "luxemburgo": "Internacional", "luxembourg": "Internacional",
}


# ═══════════════════════════════════════════════════════════
#  FUNÇÕES UTILITÁRIAS COMUNS
# ═══════════════════════════════════════════════════════════

def make_id(title: str, company: str) -> str:
    key = f"{title.lower().strip()}|{company.lower().strip()}"
    return hashlib.md5(key.encode()).hexdigest()[:12]

def classify_area(title: str, desc: str = "") -> str:
    text = (title + " " + desc).lower()
    for kw, area in AREA_MAP.items():
        if kw in text:
            return area
    return "Gestão da Informação"

def classify_modality(desc: str, is_remote: bool = False) -> str:
    if is_remote:
        return "Remoto"
    t = (desc or "").lower()
    if any(w in t for w in ["híbrido", "hybrid", "hibrido"]):
        return "Híbrido"
    if any(w in t for w in ["remote", "remoto", "teletrabalho"]):
        return "Remoto"
    return "Presencial"

def classify_contract(job_type: str, desc: str = "") -> str:
    t = (desc or "").lower()
    if job_type == "internship" or any(w in t for w in ["estágio", "estagio", "internship", "trainee"]):
        return "Estágio"
    if any(w in t for w in ["bolsa", "fellowship", "fct", "investigação"]):
        return "Bolsa"
    if job_type == "contract" or any(w in t for w in ["prazo", "temporário", "cdd", "mobilidade"]):
        return "A Prazo"
    if any(w in t for w in ["freelance", "consultor", "consultoria"]):
        return "Freelance"
    return "Efetivo"

def classify_sector(company: str, desc: str = "") -> str:
    t = (company + " " + (desc or "")).lower()
    if any(w in t for w in ["universidade", "politécnico", "faculdade", "inesc", "fct", "investigação", "research", "institute"]):
        return "Academia"
    if any(w in t for w in ["câmara", "camara", "município", "governo", "dglab", "bnp", "biblioteca nacional",
                              "ministério", "hospital", "sns", "dgaep", "epso", "serviço europeu", "ip.", "i.p."]):
        return "Público"
    if any(w in t for w in ["museu", "fundação", "cultura", "patrimônio", "arquivo histórico", "teatro", "gulbenkian"]):
        return "Cultural"
    if any(w in t for w in ["ong", "associação", "europeana", "ifla", "bad "]):
        return "ONG"
    return "Privado"

def normalize_location(text: str) -> str:
    t = text.lower()
    for key, val in LOCATION_MAP.items():
        if key in t:
            return val
    if "portugal" in t:
        return "Porto"
    return "Internacional"

def fmt_date(d) -> str:
    if d is None or (hasattr(d, '__class__') and d.__class__.__name__ == 'NaTType'):
        return TODAY_STR
    if isinstance(d, str):
        return d[:10]
    try:
        return d.strftime("%Y-%m-%d")
    except Exception:
        return TODAY_STR

def deadline_from(posted: str, days: int = 30) -> str:
    try:
        return (datetime.strptime(posted, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")
    except Exception:
        return ""

def extract_tags(title: str, desc: str = "") -> list:
    skills = [
        "SharePoint", "Power BI", "Python", "SQL", "Opentext", "iManage",
        "GDPR", "RGPD", "ISO 15489", "Dublin Core", "EAD", "OAI-PMH",
        "MARC", "OAIS", "Linked Data", "SPARQL", "FAIR", "DMP", "NLP",
        "Figma", "CMS", "Microsoft 365", "Alfresco", "Documentum",
        "Gestão Documental", "Preservação Digital", "Metadados",
        "Digitalização", "Knowledge Management", "Records Management",
        "Taxonomia", "Ontologia", "ECM",
    ]
    text = title + " " + (desc or "")
    return [s for s in skills if re.search(re.escape(s), text, re.IGNORECASE)][:6]

def is_relevant(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in RELEVANT_KEYWORDS)

def build_job(*, title, org, desc="", url="#", posted=None, area=None,
              contrato=None, modalidade=None, setor=None, local="Portugal",
              source="", job_type="", is_remote=False) -> dict:
    posted = posted or TODAY_STR
    return {
        "id":        make_id(title, org),
        "title":     title.strip(),
        "org":       org.strip(),
        "area":      area or classify_area(title, desc),
        "contrato":  contrato or classify_contract(job_type, desc),
        "modalidade":modalidade or classify_modality(desc, is_remote),
        "setor":     setor or classify_sector(org, desc),
        "local":     normalize_location(local),
        "tags":      extract_tags(title, desc),
        "newBadge":  True,
        "posted":    fmt_date(posted),
        "deadline":  deadline_from(fmt_date(posted), 30),
        "url":       url,
        "desc":      (desc[:300].strip() + "…") if len(desc) > 300 else desc.strip(),
        "source":    source,
    }


# ═══════════════════════════════════════════════════════════
#  FONTE A — JobSpy (Indeed + Google Jobs)
# ═══════════════════════════════════════════════════════════

def scrape_jobspy() -> list:
    print("\n── FONTE A: JobSpy (Indeed + Google Jobs) ──")
    jobs, seen = [], set()
    for query in SEARCH_QUERIES:
        print(f"  🔍 {query[:65]}…")
        try:
            df = scrape_jobs(
                site_name=JOBSPY_SITES,
                search_term=query,
                google_search_term=f"{query} jobs Portugal",
                location="Portugal",
                results_wanted=RESULTS_WANTED,
                hours_old=HOURS_OLD,
                country_indeed="Portugal",
                linkedin_fetch_description=False,
                verbose=0,
            )
            print(f"     → {len(df)} resultados brutos")
        except Exception as e:
            print(f"     ✗ Erro: {e}")
            continue

        for _, row in df.iterrows():
            title = str(row.get("title", "")).strip()
            org   = str(row.get("company", "")).strip()
            if not title or not org or not is_relevant(title):
                continue
            jid = make_id(title, org)
            if jid in seen:
                continue
            seen.add(jid)
            city    = str(row.get("city", "") or "")
            state   = str(row.get("state", "") or "")
            country = str(row.get("country", "") or "")
            desc    = str(row.get("description", "") or "")
            jobs.append(build_job(
                title=title, org=org, desc=desc,
                url=str(row.get("job_url", "#") or "#"),
                posted=row.get("date_posted"),
                local=f"{city} {state} {country}",
                job_type=str(row.get("job_type", "") or ""),
                is_remote=bool(row.get("is_remote", False)),
                source=str(row.get("site", "")).capitalize(),
            ))
        time.sleep(1)

    print(f"  ✅ JobSpy: {len(jobs)} vagas relevantes")
    return jobs


# ═══════════════════════════════════════════════════════════
#  FONTE B — BAD (bad.pt/bolsa-de-emprego/)
# ═══════════════════════════════════════════════════════════

BAD_URL = "https://bad.pt/bolsa-de-emprego/"

def scrape_bad() -> list:
    print("\n── FONTE B: BAD — Bolsa de Emprego ──")
    jobs = []
    try:
        r = requests.get(BAD_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        # Cada vaga é um <h2> seguido de parágrafos com área/local/tipo
        headings = soup.find_all("h2")
        for h in headings:
            title = h.get_text(strip=True)
            if not title or len(title) < 10:
                continue

            # Recolhe texto dos elementos seguintes até ao próximo h2
            meta_texts = []
            link_url = "#"
            sib = h.find_next_sibling()
            while sib and sib.name != "h2":
                text = sib.get_text(strip=True)
                if text:
                    meta_texts.append(text)
                a = sib.find("a", href=True)
                if a and "ver oferta" in a.get_text(strip=True).lower():
                    href = a["href"]
                    link_url = href if href.startswith("http") else "https://bad.pt" + href
                sib = sib.find_next_sibling()

            # Extrai localização da metadata
            combined = " ".join(meta_texts).lower()
            local = "Portugal"
            for city in ["porto", "lisboa", "braga", "coimbra", "bruxelas", "luxemburgo"]:
                if city in combined:
                    local = city.capitalize()
                    break

            # Extrai área
            area = "Arquivo"
            if "biblioteca" in combined:
                area = "Biblioteca"
            elif "documentação" in combined or "documental" in combined:
                area = "Arquivo"

            # Tipo de vaga
            contrato = "Efetivo"
            if "estágio" in combined:
                contrato = "Estágio"
            elif "mobilidade" in combined or "a prazo" in combined:
                contrato = "A Prazo"
            elif "bolsa" in combined:
                contrato = "Bolsa"

            jobs.append(build_job(
                title=title, org="BAD — Bolsa de Emprego",
                url=link_url, posted=TODAY_STR,
                area=area, contrato=contrato,
                local=local, setor="Público",
                source="BAD",
            ))

        print(f"  ✅ BAD: {len(jobs)} vagas encontradas")
    except Exception as e:
        print(f"  ✗ BAD falhou: {e}")
    return jobs


# ═══════════════════════════════════════════════════════════
#  FONTE C — BEP (bep.gov.pt) — API JSON pública
# ═══════════════════════════════════════════════════════════

# O BEP expõe uma API REST pública (OData/JSON) usada pela sua própria interface.
# Pesquisa por categorias de arquivo/documentação/biblioteca.
BEP_API = (
    "https://www.bep.gov.pt/api/odata/OfertaEmprego"
    "?$filter=contains(tolower(Designacao),'arquivo') or "
    "contains(tolower(Designacao),'documentação') or "
    "contains(tolower(Designacao),'biblioteca') or "
    "contains(tolower(Designacao),'informação')"
    "&$orderby=DataPublicacao desc"
    "&$top=50"
    "&$format=json"
)

BEP_FALLBACK_URL = "https://www.bep.gov.pt/default.aspx"

def scrape_bep() -> list:
    print("\n── FONTE C: BEP (bep.gov.pt) ──")
    jobs = []

    # Tenta a API JSON primeiro
    try:
        r = requests.get(BEP_API, headers={**HEADERS, "Accept": "application/json"}, timeout=15)
        if r.status_code == 200:
            data = r.json()
            offers = data.get("value", [])
            print(f"  → API JSON: {len(offers)} resultados brutos")
            for item in offers:
                title = item.get("Designacao", "").strip()
                org   = item.get("Entidade", item.get("NomeEntidade", "Entidade Pública")).strip()
                if not title:
                    continue
                posted = str(item.get("DataPublicacao", TODAY_STR))[:10]
                local_raw = item.get("Distrito", item.get("Localidade", "Portugal"))
                url_id = item.get("ID", item.get("Id", ""))
                url = f"https://www.bep.gov.pt/default.aspx?app=ofertasemprego&id={url_id}" if url_id else BEP_FALLBACK_URL
                jobs.append(build_job(
                    title=title, org=org,
                    url=url, posted=posted,
                    local=str(local_raw),
                    setor="Público",
                    source="BEP",
                ))
            print(f"  ✅ BEP (API): {len(jobs)} vagas")
            return jobs
    except Exception as e:
        print(f"  ⚠ API JSON falhou ({e}), a tentar HTML…")

    # Fallback: raspagem HTML do BEP
    try:
        params = {
            "app": "ofertasemprego",
            "pesquisa": "arquivo documentação biblioteca informação",
            "ordem": "data",
        }
        r = requests.get(BEP_FALLBACK_URL, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        # Tenta encontrar lista de ofertas (estrutura típica do BEP)
        items = soup.select("div.oferta, li.oferta, .resultado-oferta, article")
        print(f"  → HTML fallback: {len(items)} elementos encontrados")
        for item in items[:30]:
            title_el = item.select_one("h2, h3, .titulo, .designacao")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if not title or not is_relevant(title):
                continue
            org_el  = item.select_one(".entidade, .empresa, .org")
            org     = org_el.get_text(strip=True) if org_el else "Entidade Pública"
            link_el = item.select_one("a[href]")
            href    = link_el["href"] if link_el else ""
            url     = href if href.startswith("http") else f"https://www.bep.gov.pt{href}"
            jobs.append(build_job(
                title=title, org=org,
                url=url, posted=TODAY_STR,
                setor="Público", source="BEP",
            ))
        print(f"  ✅ BEP (HTML): {len(jobs)} vagas")
    except Exception as e:
        print(f"  ✗ BEP HTML também falhou: {e}")

    return jobs


# ═══════════════════════════════════════════════════════════
#  FONTE D — Apply UP (app.apply.up.pt)
# ═══════════════════════════════════════════════════════════

APPLY_UP_URL = "https://app.apply.up.pt/"
APPLY_UP_SEARCH = "https://app.apply.up.pt/candidaturas/pesquisa"

def scrape_apply_up() -> list:
    print("\n── FONTE D: Apply UP (app.apply.up.pt) ──")
    jobs = []
    try:
        # Tenta a página de pesquisa com termos relevantes
        keywords = ["arquivo", "documentação", "biblioteca", "informação", "knowledge"]
        for kw in keywords:
            try:
                r = requests.get(
                    APPLY_UP_SEARCH,
                    params={"q": kw, "area": "ciencias-informacao"},
                    headers=HEADERS, timeout=15
                )
                if r.status_code != 200:
                    continue
                soup = BeautifulSoup(r.text, "lxml")
                cards = soup.select("article, .job-card, .oferta, .vaga, li.resultado")
                for card in cards:
                    title_el = card.select_one("h2, h3, .titulo, .nome")
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)
                    if not title or not is_relevant(title):
                        continue
                    org_el = card.select_one(".entidade, .departamento, .faculdade")
                    org    = org_el.get_text(strip=True) if org_el else "Universidade do Porto"
                    link   = card.select_one("a[href]")
                    href   = link["href"] if link else ""
                    url    = href if href.startswith("http") else f"https://app.apply.up.pt{href}"
                    jobs.append(build_job(
                        title=title, org=org,
                        url=url, posted=TODAY_STR,
                        local="Porto", setor="Academia",
                        source="Apply UP",
                    ))
                time.sleep(0.5)
            except Exception:
                continue

        # Se não encontrou nada via pesquisa, tenta página principal
        if not jobs:
            r = requests.get(APPLY_UP_URL, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.find_all("a", href=True):
                text = a.get_text(strip=True)
                if is_relevant(text) and len(text) > 15:
                    href = a["href"]
                    url  = href if href.startswith("http") else f"https://app.apply.up.pt{href}"
                    jobs.append(build_job(
                        title=text, org="Universidade do Porto",
                        url=url, posted=TODAY_STR,
                        local="Porto", setor="Academia",
                        source="Apply UP",
                    ))

        print(f"  ✅ Apply UP: {len(jobs)} vagas encontradas")
    except Exception as e:
        print(f"  ✗ Apply UP falhou: {e}")
    return jobs


# ═══════════════════════════════════════════════════════════
#  FONTE E — CM Porto (cm-porto.pt)
# ═══════════════════════════════════════════════════════════

CMP_URLS = [
    "https://www.cm-porto.pt/recursos-humanos/oportunidades-de-emprego",
    "https://www.cm-porto.pt/municipio/recursos-humanos",
    "https://www.cm-porto.pt/noticias?tipo=concursos",
]

def scrape_cm_porto() -> list:
    print("\n── FONTE E: CM Porto ──")
    jobs = []
    for url in CMP_URLS:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")

            # Procura qualquer elemento que contenha termos de CI
            candidates = []
            for tag in soup.find_all(["h1", "h2", "h3", "h4", "li", "p", "a"]):
                text = tag.get_text(strip=True)
                if is_relevant(text) and 15 < len(text) < 200:
                    link = tag if tag.name == "a" else tag.find("a", href=True)
                    href = link["href"] if link and link.get("href") else url
                    full_url = href if href.startswith("http") else f"https://www.cm-porto.pt{href}"
                    candidates.append((text, full_url))

            seen_titles = set()
            for title, job_url in candidates:
                if title not in seen_titles:
                    seen_titles.add(title)
                    jobs.append(build_job(
                        title=title, org="Câmara Municipal do Porto",
                        url=job_url, posted=TODAY_STR,
                        local="Porto", setor="Público",
                        source="CM Porto",
                    ))

            if jobs:
                break  # encontrou vagas nesta URL, para
            time.sleep(0.5)
        except Exception as e:
            print(f"  ⚠ {url}: {e}")
            continue

    print(f"  ✅ CM Porto: {len(jobs)} vagas encontradas")
    return jobs


# ═══════════════════════════════════════════════════════════
#  AGREGAÇÃO E PERSISTÊNCIA
# ═══════════════════════════════════════════════════════════

def deduplicate(jobs: list) -> list:
    seen, result = set(), []
    for j in jobs:
        if j["id"] not in seen:
            seen.add(j["id"])
            result.append(j)
    return result


def merge_with_existing(new_jobs: list) -> list:
    existing = []
    if OUTPUT_PATH.exists():
        try:
            with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                existing = data.get("jobs", [])
                for job in existing:
                    job["newBadge"] = False
        except Exception:
            pass

    existing_ids = {j["id"] for j in existing}
    truly_new    = [j for j in new_jobs if j["id"] not in existing_ids]
    print(f"\n  📊 {len(truly_new)} vagas novas | {len(existing)} já existentes")
    combined = truly_new + existing
    combined.sort(key=lambda j: j["posted"], reverse=True)
    return combined[:300]


def save(jobs: list):
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_updated": TODAY.isoformat(),
        "total": len(jobs),
        "sources": list({j["source"] for j in jobs if j.get("source")}),
        "jobs": jobs,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n  💾 Guardado: {OUTPUT_PATH} ({len(jobs)} vagas)")


# ═══════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  JobCI Scraper — Ciência da Informação (Portugal)")
    print(f"  {TODAY.strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)
    print("\nFontes ativas:")
    print("  A) JobSpy   → Indeed + Google Jobs")
    print("  B) BAD      → bad.pt/bolsa-de-emprego/")
    print("  C) BEP      → bep.gov.pt")
    print("  D) Apply UP → app.apply.up.pt")
    print("  E) CM Porto → cm-porto.pt")

    all_jobs = []
    all_jobs += scrape_jobspy()
    all_jobs += scrape_bad()
    all_jobs += scrape_bep()
    all_jobs += scrape_apply_up()
    all_jobs += scrape_cm_porto()

    all_jobs = deduplicate(all_jobs)
    print(f"\n✅ Total único (antes de merge): {len(all_jobs)} vagas")

    final = merge_with_existing(all_jobs)
    save(final)
    print("\n🎉 Scraping concluído!")
