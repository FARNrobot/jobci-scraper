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

OUTPUT_PATH  = Path("data/jobs.json")
CACHE_PATH   = Path("data/cache_ttl.json")
TODAY        = datetime.now(timezone.utc)
TODAY_STR    = TODAY.strftime("%Y-%m-%d")

# TTL por fonte em horas — fontes mais estáticas correm menos vezes
SOURCE_TTL = {
    "jobspy":    3,   # Indeed/Google — alta rotatividade
    "bad":      12,   # BAD — atualização diária
    "bep":       6,   # BEP — moderada
    "applyup":   6,
    "cmporto":  24,   # CM Porto — raramente muda
}

def _cache_load() -> dict:
    try:
        if CACHE_PATH.exists():
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _cache_save(cache: dict):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")

def source_needs_refresh(source_key: str) -> bool:
    """Devolve True se o TTL da fonte expirou ou não existe registo."""
    cache = _cache_load()
    last  = cache.get(source_key)
    if not last:
        return True
    ttl_h = SOURCE_TTL.get(source_key, 6)
    elapsed = (TODAY - datetime.fromisoformat(last)).total_seconds() / 3600
    needs = elapsed >= ttl_h
    print(f"  ⏱ [{source_key}] última corrida há {elapsed:.1f}h (TTL={ttl_h}h) → {'correr' if needs else 'ignorar'}")
    return needs

def mark_source_done(source_key: str):
    cache = _cache_load()
    cache[source_key] = TODAY.isoformat()
    _cache_save(cache)

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
    # Cargos mais frequentes dos diplomados MCI (estudo iConf 2026)
    "information manager",
    "gestor de informação",
    "business analyst",
    "functional analyst",
    "consultant information",
    "consultor gestão informação",
    "project manager informação",

    # Cargos clássicos de CI
    "arquivista",
    "bibliotecário",
    "técnico de arquivo",
    "documentalista",
    "records manager",

    # Áreas emergentes do plano de estudos MCI
    "data steward",
    "knowledge manager",
    "preservação digital",
    "arquitetura de informação",
    "gestão documental",
    "information governance",

    # Setor público (BEP, CM Porto)
    "técnico superior arquivo",
    "técnico superior biblioteca",
    "ciência da informação",
]

JOBSPY_SITES   = ["indeed", "google"]
RESULTS_WANTED = 15
HOURS_OLD      = 72


# ── Palavras-chave para filtrar relevância ──────────────────
# ── Palavras FORTES: a presença de uma só já qualifica a vaga ──────────────
STRONG_KEYWORDS = [
    # Cargos e áreas nucleares de CI
    "arquivista", "archivist", "bibliotecário", "bibliotecária", "librarian",
    "ciência da informação", "information science", "gestão da informação",
    "information manager", "information management", "gestor de informação",
    "gestão documental", "records manager", "records management",
    "documentalista", "técnico de arquivo", "técnico de documentação",
    "técnico superior de arquivo", "técnico superior de biblioteca",
    "digital preservation", "preservação digital",
    "humanidades digitais", "digital humanities",
    "knowledge manager", "knowledge management",
    "data steward", "curador de dados", "data curation",
    "information governance", "enterprise content management",
    "arquitetura de informação", "information architect",
    "metadados", "metadata", "linked data", "ontologia", "taxonomia",
    "information retrieval", "recuperação de informação",
    "serviços de informação", "literacia da informação",
    "gestão de coleções", "collection management",
    "auditor de informação", "information audit",
    "oficial de proteção de dados", "data protection officer",
    "gestão de arquivo", "gestão de documentos",
    "dglab", "bad ", "bnp ", "biblioteca nacional",
    "biblioteca pública", "biblioteca universitária",
    "arquivo histórico", "arquivo municipal", "arquivo nacional",
    "ecm ", "alfresco", "documentum", "sharepoint records",
]

# ── Palavras FRACAS: precisam de estar combinadas com outras ────────────────
# (não qualificam sozinhas — evitam falsos positivos)
WEAK_KEYWORDS = [
    "informação", "information", "arquivo", "biblioteca", "bibliotec",
    "documental", "documentação", "documentation", "records", "content",
    "knowledge", "dados", "digital", "curator", "curador",
    "compliance", "rgpd", "gdpr", "técnico superior",
    "gestão", "analyst", "analista",
]

# ── Termos que EXCLUEM a vaga mesmo que haja palavras-chave ─────────────────
EXCLUDE_KEYWORDS = [
    # TI / software sem ligação a CI
    "desenvolvedor", "developer", "software engineer", "engenheiro de software",
    "programador", "programmer", "devops", "cloud engineer", "data engineer",
    "machine learning", "deep learning", "inteligência artificial", "ai engineer",
    "cibersegurança", "cybersecurity", "network engineer", "sys admin",
    "frontend", "backend", "fullstack", "full stack", "mobile developer",
    # Finanças / contabilidade
    "contabilista", "contabilidade", "auditor financeiro", "controller financeiro",
    "gestor financeiro", "financial analyst", "CFO", "tesoureiro",
    "seguros", "broker", "trader", "analista financeiro",
    # Vendas / marketing
    "comercial", "vendedor", "sales manager", "account executive",
    "marketing digital", "social media manager", "seo specialist",
    "growth hacker", "copywriter", "media buyer",
    # Saúde / engenharia / outros
    "enfermeiro", "médico", "farmacêutico", "engenheiro civil",
    "engenheiro mecânico", "arquiteto", "arquiteto de soluções",
    "motorista", "operador de armazém", "operador de produção",
    "recursos humanos", "recrutamento", "payroll",
    # Dados sem CI
    "data scientist", "data analyst", "machine learning engineer",
    "business intelligence", "bi developer", "etl developer",
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

# Padrões para extrair prazo real da descrição da vaga
_DEADLINE_PATTERNS = [
    r'candidaturas?\s+at[eé]\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
    r'prazo\s+(?:de\s+)?candidatura[s:]?\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
    r'data\s+limite[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
    r'closing\s+date[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
    r'deadline[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
    r'até\s+(?:ao\s+dia\s+)?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
    r'(\d{1,2}[/-]\d{1,2}[/-]\d{4})\s+(?:é\s+a\s+)?data\s+(?:limite|final)',
]

def extract_deadline(desc: str, posted: str, default_days: int = 30) -> str:
    """Tenta extrair prazo real da descrição; usa estimativa como fallback."""
    if desc:
        for pattern in _DEADLINE_PATTERNS:
            m = re.search(pattern, desc.lower())
            if m:
                raw = m.group(1).replace("-", "/")
                parts = raw.split("/")
                if len(parts) == 3:
                    try:
                        d, mo, y = parts
                        if len(y) == 2:
                            y = "20" + y
                        dt = datetime(int(y), int(mo), int(d))
                        return dt.strftime("%Y-%m-%d")
                    except Exception:
                        pass
    # Fallback: estimativa baseada na data de publicação
    try:
        return (datetime.strptime(posted, "%Y-%m-%d") + timedelta(days=default_days)).strftime("%Y-%m-%d")
    except Exception:
        return ""

def deadline_from(posted: str, days: int = 30) -> str:
    return extract_deadline("", posted, days)

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

def is_relevant(title: str, desc: str = "") -> bool:
    """
    Retorna True se a vaga for relevante para Ciência da Informação.
    Lógica:
      1. Se contiver qualquer EXCLUDE_KEYWORD → rejeita
      2. Se contiver qualquer STRONG_KEYWORD  → aceita
      3. Se contiver ≥2 WEAK_KEYWORDS distintas → aceita
      4. Caso contrário → rejeita
    """
    text = (title + " " + desc).lower()

    # 1. Exclusões (têm prioridade sobre tudo)
    if any(kw in text for kw in EXCLUDE_KEYWORDS):
        return False

    # 2. Palavra forte → aceita imediatamente
    if any(kw in text for kw in STRONG_KEYWORDS):
        return True

    # 3. Duas ou mais palavras fracas → aceita
    weak_hits = sum(1 for kw in WEAK_KEYWORDS if kw in text)
    return weak_hits >= 2

def classify_level(title: str, desc: str = "") -> str:
    """Classifica nível de senioridade com base no título e descrição."""
    text = (title + " " + desc).lower()
    if any(w in text for w in [
        "estagiário", "estagiaria", "estágio", "estagio", "trainee",
        "junior", "júnior", "entry level", "entry-level", "recém",
        "licenciado", "recém-graduado", "graduate"
    ]):
        return "Júnior"
    if any(w in text for w in [
        "sénior", "senior", "sr.", "lead", "principal", "especialista",
        "expert", "head of", "director", "diretor", "chefe de",
        "responsável", "coordenador", "gestor sénior"
    ]):
        return "Sénior"
    return "Médio"

def build_job(*, title, org, desc="", url="#", posted=None, area=None,
              contrato=None, modalidade=None, setor=None, local="Portugal",
              source="", job_type="", is_remote=False) -> dict:
    posted = posted or TODAY_STR
    posted_fmt = fmt_date(posted)
    return {
        "id":        make_id(title, org),
        "title":     title.strip(),
        "org":       org.strip(),
        "area":      area or classify_area(title, desc),
        "contrato":  contrato or classify_contract(job_type, desc),
        "modalidade":modalidade or classify_modality(desc, is_remote),
        "setor":     setor or classify_sector(org, desc),
        "local":     normalize_location(local),
        "nivel":     classify_level(title, desc),
        "tags":      extract_tags(title, desc),
        "newBadge":  True,
        "posted":    posted_fmt,
        "deadline":  extract_deadline(desc, posted_fmt, 30),
        "url":       url,
        "desc":      (desc[:300].strip() + "…") if len(desc) > 300 else desc.strip(),
        "source":    source,
    }


# ═══════════════════════════════════════════════════════════
#  FONTE A — JobSpy (Indeed + Google Jobs)
# ═══════════════════════════════════════════════════════════

def _canonical_url(url: str, site: str) -> str:
    """Extrai URL canónica e permanente para Indeed/Google Jobs."""
    if not url or url == "#":
        return "#"
    # Indeed: preserva só ?jk=ID, descarta parâmetros de tracking
    if "indeed.com" in url:
        m = re.search(r'jk=([a-f0-9]+)', url)
        if m:
            return f"https://www.indeed.com/viewjob?jk={m.group(1)}"
    # Google Jobs: tenta extrair URL original embutida
    if "google.com" in url:
        m = re.search(r'url=([^&]+)', url)
        if m:
            from urllib.parse import unquote
            return unquote(m.group(1))
    return url.split("&utm")[0].split("?tk=")[0]  # remove tracking genérico

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
                url=_canonical_url(str(row.get("job_url", "#") or "#"), str(row.get("site",""))),
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

        # Cada vaga real na BAD tem sempre um link "Ver Oferta" nos siblings do h2.
        # Filtra apenas h2 que tenham esse link — ignora menus, cabeçalhos, etc.
        for h in soup.find_all("h2"):
            title = h.get_text(strip=True)
            if not title or len(title) < 15:
                continue

            link_url = None
            meta_texts = []
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

            # Sem "Ver Oferta" = não é uma vaga, ignora
            if not link_url:
                continue

            combined = " ".join(meta_texts).lower()
            title_l = title.lower()

            local = "Portugal"
            for city in ["porto", "lisboa", "braga", "coimbra", "bruxelas", "luxemburgo", "aveiro", "évora", "faro", "setúbal"]:
                if city in combined:
                    local = city.capitalize()
                    break

            area = "Arquivo / Documentação"
            if "biblioteca" in combined or "biblioteca" in title_l:
                area = "Biblioteca / Serviços Digitais"
            elif "informação" in title_l and "gestão" in title_l:
                area = "Gestão da Informação"
            elif "documentação" in combined or "documental" in combined:
                area = "Gestão Documental"

            contrato = "Efetivo"
            if "estágio" in combined or "estágio" in title_l:
                contrato = "Estágio"
            elif "mobilidade" in combined:
                contrato = "A Prazo"
            elif "bolsa" in combined:
                contrato = "Bolsa"
            elif "a prazo" in combined or "termo" in combined:
                contrato = "A Prazo"

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

# A CM Porto publica concursos em páginas específicas.
# Estratégia: recolher APENAS <a> cujo href contenha padrões de URL de concurso.
# Nunca capturar links de navegação, gestão, segurança, etc.
CMP_URLS = [
    "https://www.cm-porto.pt/recursos-humanos/concursos-e-avisos-de-abertura",
    "https://www.cm-porto.pt/recursos-humanos/oportunidades-de-emprego",
    "https://www.cm-porto.pt/recursos-humanos/recrutamento",
]

CMP_JOB_URL_PATTERNS = [
    "/concurso", "/aviso-de-abertura", "/recrutamento/",
    "/procedimento", "/oferta-de-emprego", "/emprego/",
]

CMP_EXCLUDE_PATTERNS = [
    "/seguranca", "/sistema-de-gestao", "/centro-de-gestao",
    "/gestao-integrada", "/noticias", "/agenda", "/sobre",
    "/contactos", "/mapa", "/acessibilidade", "/politica",
    "/municipio", "/servicos", "/vereacao", "/camara",
    "recursos-humanos#", "/recursos-humanos/sistema",
    "/recursos-humanos/centro",
]

def scrape_cm_porto() -> list:
    print("\n── FONTE E: CM Porto ──")
    jobs = []
    for url in CMP_URLS:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                print(f"  ⚠ CM Porto {url}: HTTP {r.status_code}")
                continue
            soup = BeautifulSoup(r.text, "lxml")

            seen_titles = set()
            for a in soup.find_all("a", href=True):
                href = a["href"]
                full_url = href if href.startswith("http") else f"https://www.cm-porto.pt{href}"
                title = a.get_text(strip=True)

                href_lower = href.lower()
                is_job_url = any(p in href_lower for p in CMP_JOB_URL_PATTERNS)
                is_excluded = any(p in href_lower for p in CMP_EXCLUDE_PATTERNS)

                if not is_job_url or is_excluded:
                    continue
                if not title or len(title) < 10 or len(title) > 250:
                    continue
                if title in seen_titles:
                    continue

                seen_titles.add(title)
                jobs.append(build_job(
                    title=title, org="Câmara Municipal do Porto",
                    url=full_url, posted=TODAY_STR,
                    local="Porto", setor="Público",
                    source="CM Porto",
                ))

            if jobs:
                print(f"  ✅ CM Porto: {len(jobs)} vagas em {url}")
                break
            time.sleep(0.5)
        except Exception as e:
            print(f"  ⚠ CM Porto {url}: {e}")
            continue

    if not jobs:
        print("  ℹ CM Porto: 0 vagas (sem concursos abertos ou estrutura alterada)")
    return jobs


# ═══════════════════════════════════════════════════════════
#  AGREGAÇÃO E PERSISTÊNCIA
# ═══════════════════════════════════════════════════════════

def _similarity(a: str, b: str) -> float:
    """Similaridade simples baseada em bigramas (rápida, sem dependências)."""
    def bigrams(s):
        s = s.lower().strip()
        return set(s[i:i+2] for i in range(len(s)-1))
    ba, bb = bigrams(a), bigrams(b)
    if not ba or not bb:
        return 0.0
    return 2 * len(ba & bb) / (len(ba) + len(bb))

def deduplicate(jobs: list) -> list:
    """Remove duplicados exactos (por ID) e quasi-duplicados (similaridade ≥85%)."""
    seen_ids, seen_titles, result = set(), [], []
    for j in jobs:
        if j["id"] in seen_ids:
            continue
        # Verifica similaridade com títulos já aceites (mesma org)
        title = j.get("title","")
        org   = j.get("org","")
        is_dup = False
        for (st, so) in seen_titles:
            if so.lower() == org.lower() and _similarity(title, st) >= 0.85:
                is_dup = True
                break
        if is_dup:
            continue
        seen_ids.add(j["id"])
        seen_titles.append((title, org))
        result.append(j)
    print(f"  🔁 Deduplicação: {len(jobs)} → {len(result)} vagas únicas")
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
    if source_needs_refresh("jobspy"):
        all_jobs += scrape_jobspy(); mark_source_done("jobspy")
    else:
        print("\n── FONTE A: JobSpy — cache válida, a ignorar ──")

    if source_needs_refresh("bad"):
        all_jobs += scrape_bad(); mark_source_done("bad")
    else:
        print("\n── FONTE B: BAD — cache válida, a ignorar ──")

    if source_needs_refresh("bep"):
        all_jobs += scrape_bep(); mark_source_done("bep")
    else:
        print("\n── FONTE C: BEP — cache válida, a ignorar ──")

    if source_needs_refresh("applyup"):
        all_jobs += scrape_apply_up(); mark_source_done("applyup")
    else:
        print("\n── FONTE D: Apply UP — cache válida, a ignorar ──")

    if source_needs_refresh("cmporto"):
        all_jobs += scrape_cm_porto(); mark_source_done("cmporto")
    else:
        print("\n── FONTE E: CM Porto — cache válida, a ignorar ──")

    all_jobs = deduplicate(all_jobs)
    print(f"\n✅ Total único (antes de merge): {len(all_jobs)} vagas")

    final = merge_with_existing(all_jobs)
    save(final)
    print("\n🎉 Scraping concluído!")
