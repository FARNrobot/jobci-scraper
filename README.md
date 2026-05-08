# JobCI — Filtro de Emprego em Ciência da Informação 🗂️

Site pessoal que rastreia automaticamente vagas de emprego para perfis de **Ciência da Informação** em Portugal, atualizando a cada **3 horas** via GitHub Actions.

## Estrutura do projeto

```
jobci-scraper/
├── scraper.py                    ← Script Python de scraping
├── requirements.txt              ← Dependências Python
├── data/
│   └── jobs.json                 ← Base de dados de vagas (gerada automaticamente)
├── docs/
│   └── index.html                ← Site (publicado via GitHub Pages)
└── .github/
    └── workflows/
        └── scrape.yml            ← Agendador GitHub Actions (cron 3h)
```

---

## Como configurar (passo a passo)

### 1. Criar o repositório no GitHub

1. Vai a [github.com/new](https://github.com/new)
2. Nome: `jobci-scraper` (ou outro à tua escolha)
3. Visibilidade: **Público** ← obrigatório para GitHub Pages e Actions gratuitos
4. Clica em **Create repository**

### 2. Fazer upload dos ficheiros

**Opção A — Interface web do GitHub (mais simples):**
1. No repositório vazio, clica em "uploading an existing file"
2. Arrasta todos os ficheiros mantendo a estrutura de pastas
3. Clica "Commit changes"

**Opção B — Git na linha de comandos:**
```bash
git init
git remote add origin https://github.com/SEU_USERNAME/jobci-scraper.git
git add .
git commit -m "🚀 Setup inicial JobCI"
git push -u origin main
```

### 3. Ativar GitHub Pages

1. No repositório → **Settings** → **Pages**
2. Source: **Deploy from a branch**
3. Branch: `main` | Folder: `/docs`
4. Clica **Save**
5. Em ~2 minutos o site fica disponível em:
   `https://SEU_USERNAME.github.io/jobci-scraper/`

### 4. Dar permissões ao Actions para fazer commit

1. **Settings** → **Actions** → **General**
2. Em "Workflow permissions" → seleciona **"Read and write permissions"**
3. Clica **Save**

### 5. Correr o scraper pela primeira vez (manualmente)

1. Vai ao separador **Actions** do repositório
2. Clica em "JobCI — Scraper de Vagas"
3. Clica **"Run workflow"** → **Run workflow**
4. Aguarda ~5 minutos
5. Refresca o site — as vagas reais aparecem!

A partir daí corre automaticamente a cada 3 horas. ✅

---

## Personalizar os termos de pesquisa

Edita `scraper.py`, secção `SEARCH_QUERIES`:

```python
SEARCH_QUERIES = [
    '"gestão da informação"',
    'arquivista Portugal',
    '"data steward" OR "knowledge manager"',
    # Adiciona os teus próprios termos aqui
]
```

---

## Tecnologias utilizadas

| Ferramenta | Função | Custo |
|---|---|---|
| [JobSpy](https://github.com/speedyapply/JobSpy) | Scraping de LinkedIn, Indeed, Google Jobs | Gratuito |
| GitHub Actions | Cron job a cada 3h | Gratuito (repo público) |
| GitHub Pages | Hospedagem do site | Gratuito |
| `data/jobs.json` | Base de dados das vagas | Ficheiro no repo |

---

## Notas importantes

- **LinkedIn** pode bloquear IPs sem proxy. Para ativá-lo, adiciona proxies em `scraper.py`.
- **Indeed Portugal** é o mais fiável — raramente bloqueia.
- O histórico de vagas é preservado (máx. 200 vagas no `jobs.json`).
- As vagas expiradas continuam visíveis mas marcadas como "Prazo expirado".

---

## Fontes de dados rastreadas

| Fonte | URL | Método | Notas |
|---|---|---|---|
| **Indeed Portugal** | indeed.pt | JobSpy | Mais fiável, raramente bloqueia |
| **Google Jobs** | google.com/jobs | JobSpy | Agrega múltiplos portais |
| **BAD** | bad.pt/bolsa-de-emprego | HTML scraping | Vagas exclusivas de CI em PT |
| **BEP** | bep.gov.pt | API JSON pública | Concursos públicos do Estado |
| **Apply UP** | app.apply.up.pt | HTML scraping | Vagas e bolsas da Univ. Porto |
| **CM Porto** | cm-porto.pt | HTML scraping | Concursos município do Porto |

### Adicionar novas fontes

Para adicionar uma fonte nova, cria uma função `scrape_NOME()` em `scraper.py` que devolva uma lista de dicts e adiciona a chamada no `if __name__ == "__main__"`.
