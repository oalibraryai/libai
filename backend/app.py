"""
YOUR_LIBRARY_NAME AI Agent
MCP-style tool-calling backend with RAG, PRIMO, PubMed, Google Scholar, Consensus

Tools:
  - search_primo: Search KU Library catalog
  - search_pubmed: Search biomedical literature
  - search_scholar: Search Google Scholar
  - search_consensus: Search Consensus (research papers)
  - get_library_info: RAG from KU library knowledge base

Environment variables (HF Space Secrets):
  OPENAI_API_KEY      — required (embeddings + ChatGPT)
  ANTHROPIC_API_KEY   — optional (Claude answers)
  PRIMO_API_KEY       — required (PRIMO search)
"""

import os
import json
import re
import glob
import time
import sqlite3
import hashlib
import secrets
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import FAISS
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document

import httpx

# ===== CONFIG =====
KNOWLEDGE_DIR = "knowledge"
# Use /data for persistence across HF Space restarts — fall back to local if /data unavailable
FAISS_INDEX_PATH = "/data/faiss_index" if os.path.exists("/data") else "faiss_index"
DB_PATH = "/data/analytics.db" if os.path.exists("/data") else "analytics.db"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
TOP_K = 5

# ===== MEDICAL TOPIC DETECTION =====
MEDICAL_KEYWORDS = [
    'medicine','medical','health','clinical','nursing','pharmacy','biomedical',
    'anatomy','physiology','epidemiology','oncology','cardiology','neuroscience',
    'genomics','pathology','surgery','mental health','nutrition','public health',
    'disease','therapy','treatment','diagnosis','patient','drug','pharmaceutical',
    'hospital','cancer','diabetes','heart','brain','cell biology','immunology',
    'biochemistry','microbiology','virology','pediatric','psychiatric','dental',
    'ophthalmology','radiology','anesthesia','emergency medicine','geriatric'
]

# ===== GLOBALS =====
vectorstore = None
http_client = None


# ===== ANALYTICS DB =====
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS queries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT, question TEXT, tool_used TEXT,
        model TEXT, response_time REAL, result_count INTEGER,
        error TEXT
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS bot_config (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT
    )''')
    # Set defaults if not exist
    defaults = {
        "welcome_message": "Hi! I'm the YOUR_LIBRARY_NAME AI Assistant. I can help you find articles, books, databases, and answer questions about library services. How can I help you today?",
        "bot_personality": "You are a helpful, friendly, and knowledgeable library assistant at YOUR_UNIVERSITY_NAME. KU = YOUR_UNIVERSITY_NAME, NOT Kuwait University. Be concise (2-4 sentences). Always include relevant URLs.",
        "custom_instructions": "",
        "announcement": "",
        "max_results": "5",
        "default_model": "gpt",
        "maintenance_mode": "false",
        "maintenance_message": "The library chatbot is currently undergoing maintenance. Please try again later.",
    }
    for k, v in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO bot_config (key, value, updated_at) VALUES (?, ?, ?)",
            (k, v, datetime.utcnow().isoformat())
        )
    conn.commit()
    conn.close()

def get_config(key, default=""):
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT value FROM bot_config WHERE key=?", (key,)).fetchone()
        conn.close()
        return row[0] if row else default
    except:
        return default

def set_config(key, value):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO bot_config (key, value, updated_at) VALUES (?, ?, ?)",
        (key, value, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()


# ===== ADMIN AUTH =====
# ADMIN_PASSWORD must be set as HF Space Secret — no insecure fallback
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
if not ADMIN_PASSWORD:
    import warnings
    warnings.warn("ADMIN_PASSWORD secret is not set. Admin dashboard will be inaccessible until configured.")
admin_sessions = {}  # token -> expiry timestamp
START_TIME = time.time()  # for uptime tracking

def create_session():
    token = secrets.token_hex(32)
    admin_sessions[token] = time.time() + 86400  # 24 hour session
    return token

def verify_session(request: Request):
    token = request.cookies.get("admin_session")
    if not token or token not in admin_sessions:
        return False
    if time.time() > admin_sessions[token]:
        del admin_sessions[token]
        return False
    return True

def log_query(question, tool, model, response_time, result_count=0, error=None):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            'INSERT INTO queries (timestamp,question,tool_used,model,response_time,result_count,error) VALUES (?,?,?,?,?,?,?)',
            (datetime.utcnow().isoformat(), question, tool, model, response_time, result_count, error)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Log error: {e}")


# ===== RAG SETUP =====
def load_documents():
    docs = []
    files = glob.glob(os.path.join(KNOWLEDGE_DIR, "*.txt"))
    for filepath in files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            lines = content.split("\n", 3)
            source, title, text = "", "", content
            for line in lines[:2]:
                if line.startswith("SOURCE:"): source = line.replace("SOURCE:", "").strip()
                elif line.startswith("TITLE:"): title = line.replace("TITLE:", "").strip()
            if source or title: text = "\n".join(lines[2:]).strip()
            docs.append(Document(page_content=text, metadata={"source": source, "title": title}))
        except Exception as e:
            print(f"Error loading {filepath}: {e}")
    print(f"Loaded {len(docs)} documents")
    return docs

def build_vectorstore(docs, force_rebuild=False):
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    index_file = os.path.join(FAISS_INDEX_PATH, "index.faiss")

    # On startup: load existing index if available (saves cost + time)
    if not force_rebuild and os.path.exists(index_file):
        print(f"Loading existing FAISS index from {FAISS_INDEX_PATH}")
        store = FAISS.load_local(FAISS_INDEX_PATH, embeddings, allow_dangerous_deserialization=True)
        print(f"Loaded existing index with {store.index.ntotal} chunks")
        return store

    # Force rebuild: always re-embed all documents from scratch
    print(f"Building new FAISS index from {len(docs)} documents...")
    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    chunks = splitter.split_documents(docs)
    print(f"Split into {len(chunks)} chunks, embedding now...")
    store = FAISS.from_documents(chunks, embeddings)
    os.makedirs(FAISS_INDEX_PATH, exist_ok=True)
    store.save_local(FAISS_INDEX_PATH)
    print(f"FAISS index saved with {store.index.ntotal} chunks")
    return store


# ===== TOOL: SEARCH PRIMO =====
async def tool_search_primo(query, limit=5, peer_reviewed=False, open_access=False, year_from=None, year_to=None):
    api_key = os.environ.get("PRIMO_API_KEY")
    if not api_key: return {"error": "PRIMO_API_KEY not configured", "results": []}

    vid = "YOUR_PRIMO_VID"
    facets = ""
    if peer_reviewed: facets += "&qInclude=facet_tlevel,exact,peer_reviewed"
    if open_access: facets += "&qInclude=facet_tlevel,exact,open_access"
    if year_from or year_to:
        yf = year_from or "1900"
        yt = year_to or str(datetime.now().year)
        facets += f"&multiFacets=facet_searchcreationdate,include,{yf}%7C,%7C{yt}"

    base = "https://api-eu.hosted.exlibrisgroup.com/primo/v1/search"
    qs = f"?vid={vid}&tab=Everything&scope=MyInst_and_CI&q=any,contains,{query}&lang=en&sort=rank&limit={limit}&offset=0&apikey={api_key}{facets}"

    async with httpx.AsyncClient(timeout=15) as client:
        for region in ["api-eu", "api-na", "api-ap"]:
            url = base.replace("api-eu", region) + qs
            try:
                r = await client.get(url, headers={"Accept": "application/json"})
                if r.status_code == 200:
                    data = r.json()
                    total = data.get("info", {}).get("total", 0)
                    results = []
                    for doc in data.get("docs", []):
                        d = doc.get("pnx", {}).get("display", {})
                        a = doc.get("pnx", {}).get("addata", {})
                        s = doc.get("pnx", {}).get("search", {})
                        results.append({
                            "title": (d.get("title") or ["Untitled"])[0],
                            "creator": "; ".join(d.get("creator") or d.get("contributor") or []) or "Unknown",
                            "date": (s.get("creationdate") or a.get("risdate") or a.get("date") or [""])[0],
                            "type": (d.get("type") or [""])[0],
                            "source": (d.get("source") or a.get("jtitle") or [""])[0],
                            "description": ((d.get("description") or [""])[0] or "")[:400],
                            "doi": (a.get("doi") or [None])[0],
                        })
                    return {"total": total, "results": results, "source": "PRIMO"}
            except Exception:
                continue
    return {"error": "PRIMO API unavailable", "results": [], "source": "PRIMO"}


# ===== MCP HELPER =====
async def _call_mcp(api_key, prompt, mcp_url, mcp_name, timeout=30):
    """Call Anthropic API with an MCP server. Returns text content or raises."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "mcp-client-2025-04-04",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": prompt}],
                "mcp_servers": [{"type": "url", "url": mcp_url, "name": mcp_name}],
            },
        )
        if r.status_code != 200:
            raise Exception(f"Anthropic API: {r.status_code}")
        data = r.json()
        parts = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                parts.append(block["text"])
            elif block.get("type") == "mcp_tool_result":
                for item in block.get("content", []):
                    if item.get("type") == "text":
                        parts.append(item["text"])
        return "\n".join(parts)


async def _parse_results(api_key, raw_text, source_name, limit=5):
    """Parse raw MCP results into structured JSON."""
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"},
            json={
                "model": "claude-sonnet-4-20250514", "max_tokens": 2000,
                "messages": [{"role": "user", "content": f"""Extract search results into a JSON array. Each item: title, creator, date, source, doi, link, description, type. Return ONLY valid JSON array. No markdown. If none, return [].

Text:
{raw_text[:3000]}"""}],
            },
        )
        if r.status_code != 200: return []
        text = "".join(b["text"] for b in r.json().get("content", []) if b.get("type") == "text").strip()
        if text.startswith("```"): text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        results = json.loads(text)
        for item in results:
            item["_source"] = source_name
            if item.get("doi") and not item.get("link"): item["link"] = f"https://doi.org/{item['doi']}"
        return results[:limit]


# ===== TOOL: SEARCH PUBMED (direct NCBI E-utilities — free, reliable) =====
async def tool_search_pubmed(query, limit=5):
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{base}/esearch.fcgi?db=pubmed&term={query}&retmax={limit}&retmode=json&sort=relevance")
            if r.status_code != 200: return {"error": "PubMed search failed", "results": [], "source": "PubMed"}
            ids = r.json().get("esearchresult", {}).get("idlist", [])
            if not ids: return {"total": 0, "results": [], "source": "PubMed"}
            r2 = await client.get(f"{base}/esummary.fcgi?db=pubmed&id={','.join(ids)}&retmode=json")
            if r2.status_code != 200: return {"error": "PubMed fetch failed", "results": [], "source": "PubMed"}
            data = r2.json().get("result", {})
            results = []
            for pid in ids:
                rec = data.get(pid, {})
                if not isinstance(rec, dict): continue
                authors = ", ".join(a.get("name", "") for a in rec.get("authors", [])[:3])
                if len(rec.get("authors", [])) > 3: authors += " et al."
                results.append({
                    "title": rec.get("title", ""), "creator": authors, "date": rec.get("pubdate", ""),
                    "source": rec.get("fulljournalname", rec.get("source", "")),
                    "doi": rec.get("elocationid", "").replace("doi: ", "") if "doi:" in rec.get("elocationid", "") else None,
                    "pmid": pid, "link": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
                    "type": "Journal Article", "_source": "PubMed",
                })
            total = int(r.json().get("esearchresult", {}).get("count", 0))
            return {"total": total, "results": results, "source": "PubMed"}
    except Exception as e:
        return {"error": f"PubMed: {str(e)}", "results": [], "source": "PubMed"}


# ===== TOOL: SEARCH CONSENSUS (via Semantic Scholar with consensus framing) =====
async def tool_search_consensus(query, limit=5):
    """
    Consensus.app requires OAuth so we can't call it directly.
    Instead we search Semantic Scholar with the same query and return
    results alongside a direct Consensus deep-link so the user can
    also check the AI-synthesized answer there.
    """
    scholar = await tool_search_scholar(query, limit)
    scholar["source"] = "Consensus / Semantic Scholar"
    scholar["consensus_url"] = f"https://consensus.app/results/?q={query}"
    scholar["message"] = "Results from Semantic Scholar. For AI-synthesized consensus, click the Consensus link."
    return scholar


# ===== TOOL: SEARCH SEMANTIC SCHOLAR (direct API — free, no auth) =====
async def tool_search_scholar(query, limit=5):
    """Search 200M+ papers via Semantic Scholar API. Free, no API key needed."""
    url = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
    params = {
        "query": query,
        "limit": min(limit, 20),
        "fields": "title,authors,year,venue,externalIds,abstract,citationCount,openAccessPdf,publicationTypes",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, params=params, headers={"Accept": "application/json"})
            if r.status_code != 200:
                return {"error": f"Semantic Scholar API: {r.status_code}", "results": [], "source": "Semantic Scholar"}

            data = r.json()
            total = data.get("total", 0)
            results = []
            for paper in data.get("data", [])[:limit]:
                authors = ", ".join(a.get("name", "") for a in (paper.get("authors") or [])[:3])
                if len(paper.get("authors") or []) > 3:
                    authors += " et al."
                ext_ids = paper.get("externalIds") or {}
                doi = ext_ids.get("DOI")
                link = None
                if paper.get("openAccessPdf", {}).get("url"):
                    link = paper["openAccessPdf"]["url"]
                elif doi:
                    link = f"https://doi.org/{doi}"
                else:
                    s2_id = paper.get("paperId")
                    if s2_id:
                        link = f"https://www.semanticscholar.org/paper/{s2_id}"

                results.append({
                    "title": paper.get("title", ""),
                    "creator": authors,
                    "date": str(paper.get("year", "")),
                    "source": paper.get("venue", ""),
                    "description": ((paper.get("abstract") or "")[:400]),
                    "doi": doi,
                    "link": link,
                    "citations": paper.get("citationCount", 0),
                    "type": (paper.get("publicationTypes") or ["Article"])[0] if paper.get("publicationTypes") else "Article",
                    "open_access": bool(paper.get("openAccessPdf")),
                    "_source": "Semantic Scholar",
                })
            return {"total": total, "results": results, "source": "Semantic Scholar"}
    except Exception as e:
        return {"error": f"Semantic Scholar: {str(e)}", "results": [], "source": "Semantic Scholar"}

async def tool_library_info(question, history=None, model="gpt"):
    if not vectorstore:
        return {"answer": "Knowledge base not initialized.", "sources": [], "has_answer": False}

    # Build search query — use question + history context
    base_query = question
    if history:
        history_text = "\n".join(f"{'User' if m['role']=='user' else 'Assistant'}: {m['content']}" for m in history[-3:])
        base_query = f"{history_text}\n{question}"

    # ── Semantic query expansion ──
    # Common synonym mappings for library staff/service terms
    # This improves FAISS retrieval when users use informal terms
    SYNONYMS = {
        "research librarian": "Research and Access Services Librarian",
        "who is the librarian": "library staff contacts librarian",
        "subject librarian": "Research and Access Services Librarian",
        "medical librarian": "Medical Librarian",
        "systems librarian": "Digital Technology Services Librarian",
        "acquisitions librarian": "collection development librarian",
        "public services": "Manager Public Services",
        "e-resources librarian": "e-resources librarian databases",
        "library director": "Dr Abdulla Al Hefeiti Assistant Provost",
        "ebook": "ebook central proquest download",
        "how to borrow": "borrowing loan period renew",
        "access from home": "remote access off campus proxy",
        "cite": "RefWorks citation reference management",
        "reference manager": "RefWorks citation bibliography",
        "researcher id": "ORCID researcher identifier profile",
        "impact factor": "journal citation reports SciVal",
        "systematic review": "Cochrane Embase CINAHL PICO",
        "ai tools": "LeapSpace Scopus AI ScienceDirect AI EBSCO Research AI",
    }
    question_lower = question.lower()
    expanded_query = base_query
    for term, expansion in SYNONYMS.items():
        if term in question_lower:
            expanded_query = f"{base_query} {expansion}"
            print(f"Query expanded with: {expansion[:50]}")
            break

    # ── FAISS scored search ──
    docs_with_scores = vectorstore.similarity_search_with_score(expanded_query, k=TOP_K)
    if not docs_with_scores:
        return {"answer": "", "sources": [], "has_answer": False}

    best_score = min(score for _, score in docs_with_scores)
    print(f"RAG best_score={best_score:.3f} for: {question[:60]}")

    # Threshold 1.2: Only answer from KB when docs are clearly relevant
    # "who is Indian PM", "what is photosynthesis" etc score >1.2 against library KB
    if best_score > 1.2:
        print(f"RAG skipped — score {best_score:.3f} exceeds 1.2 threshold")
        return {"answer": "", "sources": [], "has_answer": False}

    docs = [doc for doc, _ in docs_with_scores]
    context = "\n\n".join(d.page_content for d in docs)

    # If score is moderate (0.8–1.4), the match may be close but not exact.
    # Instruct the LLM to add a "Did you mean...?" clarification if it interprets the question loosely.
    moderate_match = 0.8 < best_score <= 1.4
    did_you_mean_instruction = """
- If you are answering a question that uses different wording from what's in the context
  (e.g. user asked "research librarian" but context says "Research and Access Services Librarian"),
  start your answer with: "Did you mean [exact title from context]? If so, here is the information:"
  then give the answer.""" if moderate_match else ""

    # Prepend custom personality from admin config if set
    personality = get_config("bot_personality", "")
    personality_prefix = f"{personality}\n\n" if personality else ""

    prompt = f"""{personality_prefix}You are the YOUR_LIBRARY_NAME AI Assistant.
Answer questions about YOUR_LIBRARY_NAME services and resources.

RULES — follow exactly:
1. Answer ONLY using the context provided below.
2. If the context has relevant information → answer in 2-4 sentences, include URLs if present.{did_you_mean_instruction}
3. If the context does NOT contain the answer → output the single word: NO_LIBRARY_ANSWER
   - Do NOT write "I'm sorry"
   - Do NOT write "I don't have information"
   - Do NOT suggest contacting the library
   - Do NOT apologise
   - ONLY output: NO_LIBRARY_ANSWER

Context:
{context}

Question: {question}

Answer:"""

    # Respect the model selection — use Claude if requested, GPT otherwise
    use_claude = model == "claude" and os.environ.get("ANTHROPIC_API_KEY")
    if use_claude:
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0.2, max_tokens=500)
    else:
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2, max_tokens=500)

    response = llm.invoke(prompt)
    answer = response.content.strip()

    # LLM signalled it couldn't answer from context
    if answer == "NO_LIBRARY_ANSWER" or answer.startswith("NO_LIBRARY_ANSWER"):
        return {"answer": "", "sources": [], "has_answer": False}

    # Catch cases where LLM ignored the NO_LIBRARY_ANSWER instruction
    # and generated a polite "I don't have info" response instead
    # Normalise smart/curly apostrophes to straight before pattern matching
    answer_normalised = answer.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')

    no_info_patterns = [
        "i don't have",
        "i do not have",
        "i'm sorry",
        "i am sorry",
        "i apologize",
        "i apologise",
        "no specific information",
        "not available in",
        "not in the context",
        "context does not contain",
        "context doesn't contain",
        "i cannot find",
        "i could not find",
        "don't have information",
        "do not have information",
        "unable to find",
        "unable to provide",
        "not found in",
        "no information",
        "for further inquiries",
        "for more information, please contact",
        "please visit ask",
        "please contact the library",
        "recommend checking",
        "i'd suggest",
        "i would suggest contacting",
    ]
    if any(p in answer_normalised for p in no_info_patterns):
        print(f"RAG no-info pattern matched: '{answer_normalised[:80]}'")
        return {"answer": "", "sources": [], "has_answer": False}

    sources = []
    seen = set()
    for d in docs:
        src = d.metadata.get("source", "")
        title = d.metadata.get("title", "")
        key = src or title
        if key and key not in seen:
            seen.add(key)
            sources.append({"title": title, "source": src})

    return {"answer": answer, "sources": sources, "has_answer": True}


# ===== DETECT MEDICAL TOPIC =====
def is_medical_topic(text):
    lower = text.lower()
    return any(kw in lower for kw in MEDICAL_KEYWORDS)


# ===== STARTUP =====
@asynccontextmanager
async def lifespan(app: FastAPI):
    global vectorstore, http_client
    print("=== Starting KU Library AI Agent ===")
    init_db()
    docs = load_documents()
    if docs:
        vectorstore = build_vectorstore(docs)
        print(f"Vector store ready with {vectorstore.index.ntotal} vectors")
    http_client = httpx.AsyncClient(timeout=15)
    yield
    await http_client.aclose()
    print("Shutting down...")


# ===== FASTAPI =====
app = FastAPI(title="KU Library AI Agent", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ===== MODELS =====
class ChatMessage(BaseModel):
    role: str
    content: str

class SearchRequest(BaseModel):
    query: str
    source: str = "primo"  # primo, pubmed, scholar, consensus, all
    model: str = "gpt"
    limit: int = 5
    peer_reviewed: bool = False
    open_access: bool = False
    year_from: str | None = None
    year_to: str | None = None

class RAGRequest(BaseModel):
    question: str
    model: str = "gpt"
    history: list[ChatMessage] = []

class AgentRequest(BaseModel):
    question: str
    model: str = "gpt"
    history: list[ChatMessage] = []


# ===== ENDPOINTS =====
@app.get("/")
def health():
    return {
        "status": "ok",
        "vectorstore_ready": vectorstore is not None,
        "tools": ["search_primo", "search_pubmed", "search_scholar", "search_consensus", "get_library_info"],
        "endpoints": ["/rag", "/search", "/agent", "/config", "/year"],
        "models": {
            "gpt": bool(os.environ.get("OPENAI_API_KEY")),
            "claude": bool(os.environ.get("ANTHROPIC_API_KEY")),
        },
    }


# Fix 6: authoritative server-side year — frontend uses this instead of client device clock
@app.get("/year")
def get_year():
    now = datetime.utcnow()
    return {
        "year": now.year,
        "month": now.month,
        "date": now.strftime("%Y-%m-%d"),
    }


# ---- Spell correction + Boolean building (uses HF Space OpenAI — separate quota from Cloudflare) ----
class CorrectRequest(BaseModel):
    query: str
    year: int = 2026

@app.post("/correct")
async def correct_query(req: CorrectRequest):
    """
    Spell-correct a search query and build a PRIMO Boolean.
    Uses HF Space OpenAI key — separate from Cloudflare Worker quota.
    """
    try:
        prompt = f"""You are a search expert for YOUR_LIBRARY_NAME PRIMO.

Fix ALL spelling mistakes in the query, then build a Boolean search string.

BOOLEAN RULES:
- Split into 2-3 main concept groups (ignore: of, on, in, the, impact, effect, role)
- Each group: (mainTerm OR synonym1 OR synonym2)
- Join groups with AND, use quotes for multi-word phrases

EXAMPLES:
Query: "impuct of glubal waming"
corrected: "impact of global warming"
boolean: ("global warming" OR "climate change") AND (impact OR effect OR consequence)

Query: "machne lerning helthcare"
corrected: "machine learning in healthcare"
boolean: ("machine learning" OR "deep learning" OR AI) AND (healthcare OR clinical OR medical)

Query: "demonetization indian economy"
corrected: "demonetization Indian economy"
boolean: (demonetization OR "currency reform") AND ("Indian economy" OR India OR GDP)

Query: "renewble energy last 5 years peer reviewed"
corrected: "renewable energy"
boolean: ("renewable energy" OR "solar energy" OR "clean energy") AND (adoption OR implementation)
year_from: {req.year - 5}
peer_reviewed: true

Query: "{req.query}"

Return ONLY valid JSON (no markdown):
{{"corrected":"spell-fixed query","boolean":"(A OR B) AND (C OR D)","natural":"plain English title","year_from":"","year_to":"","peer_reviewed":false,"open_access":false}}"""

        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, max_tokens=300)
        response = llm.invoke(prompt)
        text = response.content.strip()
        s, e = text.find("{"), text.rfind("}")
        if s == -1:
            raise ValueError("No JSON")
        result = json.loads(text[s:e+1])

        # Validate boolean
        boolean = result.get("boolean", "")
        has_operators = bool(re.search(r'\b(AND|OR)\b', boolean)) if boolean else False
        has_parens = "(" in boolean if boolean else False

        if not has_operators or not has_parens:
            # Build programmatic Boolean from corrected query
            corrected = result.get("corrected", req.query)
            boolean = _make_boolean(corrected)
            result["boolean"] = boolean

        return result

    except Exception as ex:
        # Full fallback — return programmatic Boolean from original query
        boolean = _make_boolean(req.query)
        return {
            "corrected": req.query,
            "boolean": boolean,
            "natural": req.query,
            "year_from": "",
            "year_to": "",
            "peer_reviewed": False,
            "open_access": False,
        }


def _make_boolean(text: str) -> str:
    """Build a basic Boolean from text by extracting meaningful phrase groups."""
    import re as re2
    stop = re2.compile(
        r'^(of|on|in|the|a|an|and|or|for|to|with|by|from|at|is|are|was|were|be|been|'
        r'being|have|has|had|do|does|did|will|would|could|should|may|its|this|that|'
        r'these|those|about|impact|effect|role|influence|importance|use|application|'
        r'study|analysis|review|what|how|why|when|where|which)$', re2.IGNORECASE
    )
    words = text.split()
    concepts, phrase = [], []
    for w in words:
        clean = w.strip("'\"")
        if not stop.match(clean) and len(clean) > 2:
            phrase.append(clean)
        else:
            if phrase:
                concepts.append(' '.join(phrase))
                phrase = []
    if phrase:
        concepts.append(' '.join(phrase))
    if len(concepts) >= 2:
        return ' AND '.join(f'"{c}"' for c in concepts)
    if len(concepts) == 1:
        return f'"{concepts[0]}"'
    return f'"{text}"'


# ---- General knowledge endpoint (uses HF Space OpenAI key — separate quota from Cloudflare) ----
class GeneralRequest(BaseModel):
    question: str
    history: list = []
    model: str = "gpt"

@app.post("/general")
async def general_query(req: GeneralRequest):
    """Answer general knowledge questions using OpenAI Responses API with web search."""
    try:
        import openai
        client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        # Build messages including history
        messages = []
        if req.history:
            for m in req.history[-5:]:
                role = m.get("role", "user")
                msg_content = m.get("content", "")
                if role in ("user", "assistant") and msg_content:
                    messages.append({"role": role, "content": msg_content})

        messages.append({"role": "user", "content": req.question})

        # Use Responses API with web_search_preview tool for real-time answers
        response = client.responses.create(
            model="gpt-4o-mini",
            tools=[{"type": "web_search_preview"}],
            input=messages,
        )

        # Extract text answer and web citations
        answer = ""
        sources = []
        for block in response.output:
            if hasattr(block, "content"):
                for item in block.content:
                    if hasattr(item, "text"):
                        answer += item.text
                    if hasattr(item, "annotations"):
                        for ann in item.annotations:
                            if hasattr(ann, "url") and hasattr(ann, "title"):
                                sources.append({"url": ann.url, "title": ann.title})

        if not answer:
            answer = response.output_text if hasattr(response, "output_text") else ""

        return {
            "answer": answer.strip(),
            "sources": sources,
            "model": "gpt-4o-mini-web"
        }

    except Exception as e:
        print(f"Web search failed, falling back to plain GPT: {e}")
        # Fallback to plain gpt-4o-mini without web search
        try:
            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3, max_tokens=500)
            msgs = []
            for m in req.history[-5:]:
                if m.get("role") in ("user","assistant"):
                    msgs.append({"role": m["role"], "content": m.get("content","")})
            msgs.append({"role": "user", "content": req.question})
            response = llm.invoke(msgs)
            return {"answer": response.content.strip(), "sources": [], "model": "gpt-4o-mini"}
        except Exception as e2:
            return {"answer": "", "sources": [], "error": str(e2)}


# ---- Individual search endpoints ----
@app.post("/search")
async def search(req: SearchRequest):
    start = time.time()
    source = req.source.lower()
    result = {}

    try:
        if source == "primo":
            result = await tool_search_primo(req.query, req.limit, req.peer_reviewed, req.open_access, req.year_from, req.year_to)
        elif source == "pubmed":
            result = await tool_search_pubmed(req.query, req.limit)
        elif source == "scholar":
            result = await tool_search_scholar(req.query, req.limit)
        elif source == "consensus":
            result = await tool_search_consensus(req.query, req.limit)
        elif source == "all":
            import asyncio
            tasks = [
                tool_search_primo(req.query, req.limit, req.peer_reviewed, req.open_access, req.year_from, req.year_to),
                tool_search_pubmed(req.query, min(req.limit, 3)),
                tool_search_scholar(req.query, min(req.limit, 3)),
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            combined = []
            for r in results:
                if isinstance(r, dict) and "results" in r:
                    for item in r["results"]:
                        item["_source"] = r.get("source", "unknown")
                    combined.extend(r["results"])
            result = {"total": len(combined), "results": combined, "source": "Multiple"}
        else:
            result = {"error": f"Unknown source: {source}", "results": []}

        elapsed = time.time() - start
        # Logging handled by Cloudflare D1 via worker /log endpoint (single source of truth)
        result["response_time"] = round(elapsed, 2)
        result["is_medical"] = is_medical_topic(req.query)
        return result

    except Exception as e:
        elapsed = time.time() - start
        return {"error": str(e), "results": [], "response_time": round(elapsed, 2)}


# ---- Public log endpoint (frontend calls this for all queries) ----
class LogRequest(BaseModel):
    question: str
    tool: str = "unknown"
    model: str = "gpt"
    response_time: float = 0
    result_count: int = 0
    error: str | None = None

@app.post("/log")
async def log_endpoint(req: LogRequest):
    log_query(req.question, req.tool, req.model, req.response_time, req.result_count, req.error)
    return {"status": "ok"}


# ---- RAG endpoint (backward compatible) ----
@app.post("/rag")
async def rag_query(req: RAGRequest):
    start = time.time()
    try:
        history = [{"role": m.role, "content": m.content} for m in req.history] if req.history else None
        result = await tool_library_info(req.question, history, model=req.model)
        elapsed = time.time() - start
        # Logging handled by Cloudflare D1 via worker /log endpoint
        return {
            "answer": result["answer"],
            "sources": result["sources"],
            "has_answer": result.get("has_answer", True),
            "model_used": req.model,
            "response_time": round(elapsed, 2),
        }
    except Exception as e:
        elapsed = time.time() - start
        return {"answer": "", "sources": [], "has_answer": False, "error": str(e)}


# ---- Agent endpoint (Batch 3: tool-calling agent) ----
@app.post("/agent")
async def agent_query(req: AgentRequest):
    """
    Multi-tool agent. Given a question it:
    1. Classifies intent (library_info | search_academic | search_medical | general)
    2. Calls the right combination of tools in parallel
    3. Synthesises results into a single answer with sources
    """
    start = time.time()
    question = req.question
    history = [{"role": m.role, "content": m.content} for m in req.history] if req.history else []

    # ---- Step 1: classify intent ----
    try:
        # Pre-classify using keywords before calling LLM — faster and more reliable
        question_lower = question.lower()
        research_keywords = [
            'impact', 'effect', 'influence', 'role', 'relationship', 'cause', 'consequence',
            'implication', 'benefit', 'challenge', 'advantage', 'disadvantage', 'application',
            'study', 'research', 'analysis', 'review', 'literature', 'paper', 'article',
            'find', 'search', 'look for', 'show me', 'get me', 'articles on', 'books on',
            'papers on', 'journal', 'publication', 'evidence', 'data', 'survey',
        ]
        medical_keywords_check = [
            'medicine', 'medical', 'health', 'clinical', 'drug', 'disease', 'treatment',
            'diagnosis', 'patient', 'hospital', 'nursing', 'pharmacy', 'cancer', 'diabetes',
            'surgery', 'therapy', 'pandemic', 'virus', 'vaccine', 'biomedical',
        ]
        library_keywords_check = [
            'library hours', 'study room', 'reserve', 'borrow', 'loan', 'fine', 'account',
            'interlibrary', 'ill', 'orcid', 'khazna', 'open access', 'apc', 'librarian',
        ]

        # Fast pre-classification
        if any(kw in question_lower for kw in library_keywords_check):
            intent = "library_info"
            search_query = ""
        elif any(kw in question_lower for kw in medical_keywords_check):
            intent = "search_medical"
            search_query = question
        elif any(kw in question_lower for kw in research_keywords):
            intent = "search_academic"
            search_query = question
        else:
            # Only call LLM if pre-classification is uncertain
            classifier_prompt = f"""You are classifying a question for a university LIBRARY chatbot.

CRITICAL RULE: If the question is about ANY topic that could be researched academically (science, technology, economics, environment, society, history, engineering, medicine, business, etc.) — classify it as "search_academic". This includes questions asking about impacts, effects, causes, relationships, or any factual topic.

Only use "general" for casual conversation (greetings, jokes, personal questions unrelated to research).

Question: "{question}"

Categories:
- library_info: library hours, services, borrowing, accounts, staff, policies
- search_academic: ANY research topic, impacts, effects, causes, studies, articles, books
- search_medical: health, clinical, biomedical, nursing, pharmacy topics
- general: ONLY casual conversation, greetings — NOT research questions

Return ONLY valid JSON: {{"intent":"<category>","search_query":"<corrected 3-6 keyword search query>"}}"""

            use_claude = req.model == "claude" and os.environ.get("ANTHROPIC_API_KEY")
            if use_claude:
                from langchain_anthropic import ChatAnthropic
                clf_llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0, max_tokens=120)
            else:
                clf_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, max_tokens=120)

            clf_resp = clf_llm.invoke(classifier_prompt)
            clf_text = clf_resp.content.strip()
            s, e = clf_text.find("{"), clf_text.rfind("}")
            clf = json.loads(clf_text[s:e+1]) if s != -1 else {}
            intent = clf.get("intent", "search_academic")  # default to search_academic not general
            search_query = clf.get("search_query", question)

    except Exception:
        intent = "search_academic"  # safe default — better to search than give wrong answer
        search_query = question

    # ---- Step 2: run tools based on intent ----
    tool_results = {}
    tools_used = []

    if intent == "library_info":
        # RAG from KU knowledge base
        rag = await tool_library_info(question, history[-5:] if history else None, model=req.model)
        tool_results["rag"] = rag
        tools_used.append("get_library_info")

    elif intent in ("search_academic", "search_medical"):
        # Run PRIMO + PubMed (if medical) in parallel
        import asyncio
        tasks = [tool_search_primo(search_query, limit=5)]
        if intent == "search_medical":
            tasks.append(tool_search_pubmed(search_query, limit=3))
        else:
            tasks.append(tool_search_scholar(search_query, limit=3))

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        combined = []
        for r in raw_results:
            if isinstance(r, dict) and r.get("results"):
                combined.extend(r["results"])
                tools_used.append(r.get("source", "unknown"))

        tool_results["search"] = {"results": combined[:8], "total": len(combined)}
        tools_used = list(set(tools_used))

        # Also get RAG context for library-specific guidance
        rag = await tool_library_info(question, history[-3:] if history else None, model=req.model)
        tool_results["rag"] = rag
        tools_used.append("get_library_info")

    else:
        # General question — use RAG + LLM
        rag = await tool_library_info(question, history[-5:] if history else None, model=req.model)
        tool_results["rag"] = rag
        tools_used.append("get_library_info")

    # ---- Step 3: synthesise answer ----
    context_parts = []
    if "rag" in tool_results and tool_results["rag"].get("answer"):
        context_parts.append(f"Library Knowledge Base:\n{tool_results['rag']['answer']}")
    if "search" in tool_results and tool_results["search"].get("results"):
        top = tool_results["search"]["results"][:3]
        res_text = "\n".join(f"- {r.get('title','')} by {r.get('creator','')} ({r.get('date','')})" for r in top)
        context_parts.append(f"Search Results:\n{res_text}")

    synthesis_prompt = f"""You are the YOUR_LIBRARY_NAME AI Assistant (YOUR_CITY, YOUR_COUNTRY). KU = YOUR_UNIVERSITY_NAME.
Be concise (3-5 sentences). Include relevant URLs. If search results are present, mention the top 2-3.

Context:
{chr(10).join(context_parts) if context_parts else 'No additional context.'}

Question: {question}
Answer:"""

    try:
        if use_claude:
            from langchain_anthropic import ChatAnthropic
            synth_llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0.2, max_tokens=600)
        else:
            synth_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2, max_tokens=600)
        answer = synth_llm.invoke(synthesis_prompt).content
    except Exception as ex:
        answer = tool_results.get("rag", {}).get("answer", f"Error: {str(ex)}")

    elapsed = time.time() - start
    return {
        "answer": answer,
        "intent": intent,
        "tools_used": tools_used,
        "search_results": tool_results.get("search", {}).get("results", []),
        "sources": tool_results.get("rag", {}).get("sources", []),
        "model_used": req.model,
        "response_time": round(elapsed, 2),
        "corrected_query": search_query,  # spell-corrected version for frontend recovery banner
    }


# ---- Rebuild index (protected) ----
@app.post("/rebuild")
async def rebuild_index(request: Request):
    if not verify_session(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    global vectorstore
    try:
        import shutil, glob as _glob

        # Delete old FAISS index files so we rebuild from scratch
        if os.path.exists(FAISS_INDEX_PATH):
            shutil.rmtree(FAISS_INDEX_PATH)
            print(f"Deleted old FAISS index at {FAISS_INDEX_PATH}")

        # List all knowledge files found
        kb_files = _glob.glob(os.path.join(KNOWLEDGE_DIR, "*.txt"))
        print(f"Knowledge files found: {len(kb_files)}")
        for f in kb_files:
            print(f"  - {os.path.basename(f)} ({os.path.getsize(f)} bytes)")

        docs = load_documents()
        if not docs:
            return {"error": "No knowledge files found", "kb_dir": KNOWLEDGE_DIR, "files": []}

        # Force rebuild — ignore any cached index
        vectorstore = build_vectorstore(docs, force_rebuild=True)
        chunks = vectorstore.index.ntotal

        return {
            "status": "ok",
            "chunks": chunks,
            "documents": len(docs),
            "files": [os.path.basename(f) for f in kb_files],
            "kb_dir": KNOWLEDGE_DIR
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


# ===== ADMIN LOGIN =====
@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page():
    return """<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KU Library AI — Admin Login</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#f0f4f8;display:flex;justify-content:center;align-items:center;min-height:100vh}
.login-box{background:#fff;border-radius:16px;padding:40px;width:360px;box-shadow:0 4px 24px rgba(0,0,0,.1);text-align:center}
h1{color:#003366;font-size:1.3rem;margin-bottom:6px}
.subtitle{color:#6b7280;font-size:.84rem;margin-bottom:24px}
input{width:100%;padding:12px 14px;border:1.5px solid #d1d5db;border-radius:10px;font-size:.92rem;margin-bottom:14px}
input:focus{outline:none;border-color:#003366}
.btn{width:100%;padding:12px;background:#003366;color:#fff;border:none;border-radius:10px;font-weight:700;font-size:.92rem;cursor:pointer}
.btn:hover{background:#004488}
.error{color:#dc2626;font-size:.82rem;margin-bottom:10px;display:none}
</style></head><body>
<div class="login-box">
  <h1>🔐 Admin Login</h1>
  <div class="subtitle">KU Library AI Dashboard</div>
  <div class="error" id="err">Incorrect password. Try again.</div>
  <form onsubmit="return doLogin(event)">
    <input type="password" id="pw" placeholder="Enter admin password" autofocus>
    <button type="submit" class="btn">Login</button>
  </form>
</div>
<script>
async function doLogin(e){
  e.preventDefault();
  const pw=document.getElementById('pw').value;
  const r=await fetch('/admin/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pw})});
  if(r.ok){window.location.href='/admin';}
  else{document.getElementById('err').style.display='block';document.getElementById('pw').value='';document.getElementById('pw').focus();}
  return false;
}
</script></body></html>"""


@app.post("/admin/auth")
async def admin_auth(request: Request, response: Response):
    data = await request.json()
    if data.get("password") == ADMIN_PASSWORD:
        token = create_session()
        resp = Response(content=json.dumps({"status": "ok"}), media_type="application/json")
        resp.set_cookie("admin_session", token, httponly=True, max_age=86400, samesite="lax")
        return resp
    raise HTTPException(status_code=401, detail="Invalid password")


@app.get("/admin/logout")
async def admin_logout(request: Request):
    token = request.cookies.get("admin_session")
    if token and token in admin_sessions:
        del admin_sessions[token]
    resp = RedirectResponse(url="/admin/login")
    resp.delete_cookie("admin_session")
    return resp


# ===== ADMIN DASHBOARD (protected) =====
WORKER_URL = os.environ.get("WORKER_URL", "https://your-worker.workers.dev")

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    if not verify_session(request):
        return RedirectResponse(url="/admin/login")

    config = {}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT key, value FROM bot_config").fetchall()
    conn.close()
    for r in rows: config[r["key"]] = r["value"]

    def esc(s):
        return (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KU Library AI — Admin</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#f0f4f8;color:#1a1a2e;padding:20px;max-width:1200px;margin:0 auto}}
h1{{color:#003366;font-size:1.3rem;margin-bottom:4px}}
.sub{{color:#6b7280;font-size:.82rem;margin-bottom:14px}}
.tabs{{display:flex;gap:2px;border-bottom:2px solid #d1d5db;margin-bottom:14px}}
.tab{{padding:8px 16px;cursor:pointer;font-weight:600;font-size:.84rem;color:#6b7280;border:none;background:none;border-bottom:3px solid transparent;margin-bottom:-2px}}
.tab.active{{color:#003366;border-bottom-color:#003366}}
.tc{{display:none}}.tc.active{{display:block}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:16px}}
.stat{{background:#fff;border-radius:10px;padding:12px;border:1px solid #d1d5db;text-align:center}}
.stat .n{{font-size:1.6rem;font-weight:800;color:#003366}}.stat .l{{font-size:.76rem;color:#6b7280}}
.card{{background:#fff;border-radius:10px;padding:14px;border:1px solid #d1d5db;margin-bottom:12px}}
.card h2{{font-size:.9rem;color:#003366;margin-bottom:8px}}
table{{width:100%;border-collapse:collapse;font-size:.78rem}}
th{{background:#003366;color:#fff;padding:6px 8px;text-align:left}}
td{{padding:5px 8px;border-bottom:1px solid #e5e7eb}}
tr:hover{{background:#f9fafb}}
.badge{{padding:2px 7px;border-radius:8px;font-size:.68rem;font-weight:600}}
.err{{color:#dc2626;font-size:.72rem}}
canvas{{max-height:180px}}
.fg{{margin-bottom:12px}}
.fg label{{display:block;font-weight:700;font-size:.82rem;color:#003366;margin-bottom:3px}}
.fg .h{{font-size:.72rem;color:#6b7280;margin-bottom:3px}}
textarea,input[type=text],select{{width:100%;padding:9px;border:1.5px solid #d1d5db;border-radius:8px;font-family:inherit;font-size:.82rem;resize:vertical}}
textarea:focus,input:focus,select:focus{{outline:none;border-color:#003366}}
.btn{{padding:9px 20px;border:none;border-radius:8px;font-weight:700;cursor:pointer;font-size:.84rem}}
.bp{{background:#003366;color:#fff}}.bp:hover{{background:#004488}}
.bg{{background:#059669;color:#fff}}
.br{{background:#dc2626;color:#fff}}
.toggle{{display:flex;align-items:center;gap:8px}}
.toggle input{{width:18px;height:18px;accent-color:#003366}}
.st{{padding:8px 14px;border-radius:8px;font-size:.8rem;font-weight:600;display:none;margin-top:8px}}
.st.ok{{background:#d1fae5;color:#065f46;display:block}}
.st.er{{background:#fecaca;color:#991b1b;display:block}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
@media(max-width:768px){{.two{{grid-template-columns:1fr}}}}
#loading{{text-align:center;padding:40px;color:#6b7280}}
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
</head><body>
<h1>📊 KU Library AI — Admin <span style="float:right;display:flex;gap:6px;align-items:center"><button onclick="location.reload()" class="btn bp" style="padding:5px 12px;font-size:.76rem">🔄 Refresh</button><a href="/admin/logout" style="font-size:.76rem;color:#dc2626;text-decoration:none;padding:5px 12px;border:1.5px solid #dc2626;border-radius:8px;font-weight:600">🔒 Logout</a></span></h1>
<div class="sub">YOUR_LIBRARY_NAME AI Agent</div>

<div class="tabs">
  <div class="tab active" onclick="st(this,'analytics')">📈 Analytics</div>
  <div class="tab" onclick="st(this,'behavior')">🤖 Bot Behavior</div>
  <div class="tab" onclick="st(this,'queries')">📋 Query Log</div>
  <div class="tab" onclick="st(this,'system')">⚙️ System</div>
</div>

<div class="tc active" id="t-analytics"><div id="loading">Loading analytics from Cloudflare D1…</div></div>

<div class="tc" id="t-behavior">
<div class="card"><h2>🤖 Bot Behavior</h2><p style="font-size:.8rem;color:#6b7280;margin-bottom:12px">Changes apply immediately.</p>
<div class="fg">
  <label>Welcome Message</label>
  <div class="h">First message users see. Use the toolbar for formatting — HTML is supported.</div>
  <div style="display:flex;gap:4px;margin-bottom:4px;flex-wrap:wrap">
    <button type="button" onclick="fmtWelcome('bold')" title="Bold" style="padding:3px 8px;border:1px solid #d1d5db;border-radius:4px;background:#fff;cursor:pointer;font-weight:700">B</button>
    <button type="button" onclick="fmtWelcome('italic')" title="Italic" style="padding:3px 8px;border:1px solid #d1d5db;border-radius:4px;background:#fff;cursor:pointer;font-style:italic">I</button>
    <button type="button" onclick="fmtWelcome('link')" title="Link" style="padding:3px 8px;border:1px solid #d1d5db;border-radius:4px;background:#fff;cursor:pointer">🔗</button>
    <button type="button" onclick="fmtWelcome('br')" title="Line break" style="padding:3px 8px;border:1px solid #d1d5db;border-radius:4px;background:#fff;cursor:pointer">↵</button>
    <button type="button" onclick="fmtWelcome('emoji')" title="Bee emoji" style="padding:3px 8px;border:1px solid #d1d5db;border-radius:4px;background:#fff;cursor:pointer">🐝</button>
    <button type="button" onclick="previewWelcome()" style="padding:3px 10px;border:1px solid #003366;border-radius:4px;background:#f0f4ff;color:#003366;cursor:pointer;font-size:.75rem;font-weight:600">👁 Preview</button>
    <button type="button" onclick="document.getElementById('welcome-preview').style.display='none'" style="padding:3px 8px;border:1px solid #d1d5db;border-radius:4px;background:#fff;cursor:pointer;font-size:.75rem">✕</button>
  </div>
  <textarea id="c-welcome_message" rows="4" style="font-family:monospace;font-size:.82rem">{esc(config.get('welcome_message',''))}</textarea>
  <div id="welcome-preview" style="display:none;margin-top:6px;padding:10px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;font-size:.85rem">
    <strong style="font-size:.72rem;color:#6b7280;display:block;margin-bottom:4px">PREVIEW:</strong>
    <div id="welcome-preview-content"></div>
  </div>
</div>
<div class="fg"><label>Bot Personality / System Prompt</label><div class="h">Core instructions for every LLM call.</div><textarea id="c-bot_personality" rows="4">{esc(config.get('bot_personality',''))}</textarea></div>
<div class="fg"><label>Custom Instructions</label><div class="h">Extra guidance, e.g. "During Ramadan, mention reduced hours."</div><textarea id="c-custom_instructions" rows="3">{esc(config.get('custom_instructions',''))}</textarea></div>
<div class="fg"><label>📢 Announcement Banner</label><div class="h">Shows at top of chat. Leave empty to hide.</div><textarea id="c-announcement" rows="2">{esc(config.get('announcement',''))}</textarea></div>
<div class="two"><div class="fg"><label>Default Model</label><select id="c-default_model"><option value="gpt" {'selected' if config.get('default_model')=='gpt' else ''}>ChatGPT</option><option value="claude" {'selected' if config.get('default_model')=='claude' else ''}>Claude</option></select></div>
<div class="fg"><label>Max Results</label><select id="c-max_results"><option value="3" {'selected' if config.get('max_results')=='3' else ''}>3</option><option value="5" {'selected' if config.get('max_results')=='5' else ''}>5</option><option value="10" {'selected' if config.get('max_results')=='10' else ''}>10</option></select></div></div>
<div id="sv" class="st"></div><button class="btn bp" onclick="saveConfig()">💾 Save</button>
</div></div>

<div class="tc" id="t-queries"><div id="recent-loading">Loading query log…</div></div>

<div class="tc" id="t-system">
<div class="card"><h2>⚙️ Controls</h2>
<div class="fg"><div class="toggle"><input type="checkbox" id="c-maintenance_mode" {'checked' if config.get('maintenance_mode')=='true' else ''}><label><strong>Maintenance Mode</strong></label></div></div>
<div class="fg"><label>Maintenance Message</label><textarea id="c-maintenance_message" rows="2">{esc(config.get('maintenance_message',''))}</textarea></div>
<div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
  <button class="btn bp" onclick="saveConfig()">💾 Save Config</button>
  <button class="btn bg" onclick="rebuildIdx()">🔄 Rebuild RAG</button>
  <button class="btn" style="background:#dc2626;color:#fff;border:none;padding:8px 14px;border-radius:8px;font-weight:600;cursor:pointer" onclick="restartSpace()">♻️ Restart Space</button>
  <button class="btn" style="background:#7c3aed;color:#fff;border:none;padding:8px 14px;border-radius:8px;font-weight:600;cursor:pointer" onclick="clearCache()">🗑️ Clear FAISS Cache</button>
</div>
<div id="sys" class="st"></div>
<div id="rebuild-files"></div>
</div>

<div class="card"><h2>🟢 Live Status</h2>
<div id="status-panel" style="font-size:.85rem">Loading status…</div>
</div>

<div class="card"><h2>System Info</h2><table>
<tr><td><strong>Knowledge Files</strong></td><td>{len(glob.glob(os.path.join(KNOWLEDGE_DIR,'*.txt')))} files</td></tr>
<tr><td><strong>OpenAI API</strong></td><td>{'✅ Configured' if os.environ.get('OPENAI_API_KEY') else '❌ Missing'}</td></tr>
<tr><td><strong>Anthropic API</strong></td><td>{'✅ Configured' if os.environ.get('ANTHROPIC_API_KEY') else '❌ Missing'}</td></tr>
<tr><td><strong>PRIMO API</strong></td><td>✅ Via Cloudflare Worker</td></tr>
<tr><td><strong>Admin Password</strong></td><td>{'✅ Set' if os.environ.get('ADMIN_PASSWORD') else '❌ Missing'}</td></tr>
<tr><td><strong>Cloudflare D1</strong></td><td>Connected via Worker</td></tr>
</table></div></div>

<script>
const W='{WORKER_URL}';
function st(el,t){{document.querySelectorAll('.tab').forEach(e=>e.classList.remove('active'));document.querySelectorAll('.tc').forEach(e=>e.classList.remove('active'));el.classList.add('active');document.getElementById('t-'+t).classList.add('active');}}

// Fetch analytics from Cloudflare D1
fetch(W+'/analytics').then(r=>r.json()).then(d=>{{
  const el=document.getElementById('t-analytics');
  el.innerHTML=`
  <div class="grid">
    <div class="stat"><div class="n">${{d.total}}</div><div class="l">Total</div></div>
    <div class="stat"><div class="n">${{d.today}}</div><div class="l">Today</div></div>
    <div class="stat"><div class="n">${{d.week}}</div><div class="l">This Week</div></div>
    <div class="stat"><div class="n">${{(d.avg_time||0).toFixed(1)}}s</div><div class="l">Avg Time</div></div>
    <div class="stat"><div class="n">${{d.errors}}</div><div class="l">Errors</div></div>
  </div>
  <div class="two">
    <div class="card"><h2>Tool Usage</h2><table><tr><th>Tool</th><th>Count</th></tr>${{d.tools.map(t=>`<tr><td>${{t.tool_used}}</td><td>${{t.c}}</td></tr>`).join('')}}</table></div>
    <div class="card"><h2>Model Usage</h2><table><tr><th>Model</th><th>Count</th></tr>${{d.models.map(m=>`<tr><td>${{m.model}}</td><td>${{m.c}}</td></tr>`).join('')}}</table></div>
  </div>
  <div class="two">
    <div class="card"><h2>Hourly</h2><canvas id="hc"></canvas></div>
    <div class="card"><h2>Daily (14d)</h2><canvas id="dc"></canvas></div>
  </div>
  <div class="card"><h2>Popular (Top 20)</h2><table><tr><th>Question</th><th>Count</th></tr>${{d.popular.map(p=>`<tr><td>${{(p.question||'').substring(0,70)}}</td><td>${{p.c}}</td></tr>`).join('')}}</table></div>`;
  if(d.hourly.length)new Chart(document.getElementById('hc'),{{type:'bar',data:{{labels:d.hourly.map(h=>h.hour+':00'),datasets:[{{label:'Q',data:d.hourly.map(h=>h.c),backgroundColor:'#003366'}}]}},options:{{responsive:true,plugins:{{legend:{{display:false}}}}}}}});
  if(d.daily.length)new Chart(document.getElementById('dc'),{{type:'line',data:{{labels:d.daily.map(x=>(x.day||'').slice(5)),datasets:[{{label:'Q',data:d.daily.map(x=>x.c),borderColor:'#003366',backgroundColor:'rgba(0,51,102,0.1)',fill:true,tension:.3}}]}},options:{{responsive:true,plugins:{{legend:{{display:false}}}}}}}});
}}).catch(e=>{{document.getElementById('t-analytics').innerHTML='<div class="card" style="color:#dc2626">Failed to load analytics: '+e.message+'<br>Make sure D1 is initialized: <a href="'+W+'/analytics/init" target="_blank">Click here to init DB</a></div>';}});

// Fetch recent queries
fetch(W+'/analytics/recent').then(r=>r.json()).then(d=>{{
  const el=document.getElementById('t-queries');
  el.innerHTML='<div class="card"><h2>Recent (50)</h2><table><tr><th>Time</th><th>Question</th><th>Tool</th><th>Model</th><th>Results</th><th>Status</th></tr>'+(d.results||[]).map(r=>`<tr><td>${{(r.timestamp||'').substring(0,19)}}</td><td title="${{r.question}}">${{(r.question||'').substring(0,55)}}</td><td><span class="badge" style="background:#e0e7ff">${{r.tool_used}}</span></td><td>${{r.model}}</td><td>${{r.result_count}}</td><td class="err">${{r.error||'✓'}}</td></tr>`).join('')+'</table></div>';
}}).catch(e=>{{document.getElementById('t-queries').innerHTML='<div class="card" style="color:#dc2626">'+e.message+'</div>';}});

function fmtWelcome(type){{
  const ta=document.getElementById('c-welcome_message');
  const start=ta.selectionStart, end=ta.selectionEnd;
  const sel=ta.value.substring(start,end);
  let insert='';
  if(type==='bold') insert=`<strong>${{sel||'bold text'}}</strong>`;
  else if(type==='italic') insert=`<em>${{sel||'italic text'}}</em>`;
  else if(type==='link'){{const url=prompt('Enter URL:','https://YOUR_LIBRARY_URL');if(!url)return;insert=`<a href="${{url}}" target="_blank">${{sel||'link text'}}</a>`;}}
  else if(type==='br') insert='<br>';
  else if(type==='emoji') insert='🐝';
  ta.setRangeText(insert, start, end, 'end');
  ta.focus();
}}
function previewWelcome(){{
  const html=document.getElementById('c-welcome_message').value;
  document.getElementById('welcome-preview-content').innerHTML=html;
  document.getElementById('welcome-preview').style.display='block';
}}
async function saveConfig(){{
  const keys=['welcome_message','bot_personality','custom_instructions','announcement','default_model','max_results','maintenance_message'];
  const data={{}};keys.forEach(k=>{{data[k]=document.getElementById('c-'+k).value;}});
  data.maintenance_mode=document.getElementById('c-maintenance_mode').checked?'true':'false';
  const r=await fetch('/admin/config',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(data)}});
  const res=await r.json();
  const s=document.getElementById('sv')||document.getElementById('sys');
  s.className=res.status==='ok'?'st ok':'st er'; s.textContent=res.status==='ok'?'✅ Saved!':'❌ Error';
  setTimeout(()=>s.style.display='none',3000);
}}
async function rebuildIdx(){{
  const s=document.getElementById('sys');s.className='st ok';s.textContent='🔄 Rebuilding...';s.style.display='block';
  const r=await fetch('/rebuild',{{method:'POST'}});const res=await r.json();
  if(res.status==='ok'){{
    s.textContent='✅ Rebuilt: '+res.chunks+' chunks from '+res.documents+' files';
    // Show file list so we can verify which files are loaded
    const fileList=document.getElementById('rebuild-files');
    if(fileList && res.files){{
      fileList.innerHTML='<details style="margin-top:8px;font-size:.78rem"><summary style="cursor:pointer;color:var(--ku-blue)">View '+res.files.length+' files loaded</summary><ul style="margin:6px 0 0 16px">'+res.files.sort().map(f=>'<li>'+f+'</li>').join('')+'</ul></details>';
    }}
  }}else{{
    s.textContent='❌ '+(res.error||JSON.stringify(res));
  }}
  s.className=res.status==='ok'?'st ok':'st er';
  loadStatus(); // refresh status after rebuild
}}

async function clearCache(){{
  const s=document.getElementById('sys');s.className='st ok';s.textContent='🗑️ Clearing FAISS cache...';s.style.display='block';
  try{{
    const r=await fetch('/clear-cache',{{method:'POST'}});
    const res=await r.json();
    if(res.status==='ok'){{
      s.textContent='✅ Cache cleared. Found '+res.kb_files_found+' KB files. Now click Rebuild RAG.';
      const fl=document.getElementById('rebuild-files');
      if(fl)fl.innerHTML='<details open style="margin-top:8px;font-size:.78rem"><summary style="cursor:pointer;color:var(--ku-blue)">Files found ('+res.kb_files_found+')</summary><ul style="margin:6px 0 0 16px">'+res.kb_files.map(f=>'<li>'+f+'</li>').join('')+'</ul></details>';
    }}else{{s.textContent='❌ '+(res.error||JSON.stringify(res));s.className='st er';}}
  }}catch(e){{s.textContent='❌ '+e.message;s.className='st er';}}
}}

async function restartSpace(){{
  if(!confirm('Restart the HF Space? The service will be unavailable for ~30-60 seconds.')) return;
  const s=document.getElementById('sys');s.className='st ok';s.textContent='♻️ Restarting...';s.style.display='block';
  try {{
    await fetch('/restart',{{method:'POST'}});
    s.textContent='♻️ Space restarting — please wait 30-60 seconds then refresh this page.';
    // Poll until back online
    let attempts=0;
    const poll=setInterval(async()=>{{
      attempts++;
      try{{
        const r=await fetch('/status');
        if(r.ok){{clearInterval(poll);s.textContent='✅ Space is back online!';s.className='st ok';loadStatus();}}
      }}catch(e){{
        s.textContent=`♻️ Still restarting... (${{attempts*5}}s elapsed)`;
      }}
      if(attempts>24){{clearInterval(poll);s.textContent='⚠️ Restart taking longer than expected. Try refreshing the page.';}}
    }},5000);
  }}catch(e){{s.textContent='❌ '+e.message;s.className='st er';}}
}}

async function loadStatus(){{
  const el=document.getElementById('status-panel');
  if(!el) return;
  try{{
    const r=await fetch('/status');
    if(!r.ok){{el.innerHTML='<span style="color:#dc2626">❌ HF Space not responding</span>';return;}}
    const d=await r.json();
    const uptimeMin=Math.round((d.uptime_secs||0)/60);
    const memColor=d.mem_pct>85?'#dc2626':d.mem_pct>70?'#d97706':'#16a34a';
    el.innerHTML=`
      <table style="width:100%">
        <tr><td><strong>Space Status</strong></td><td><span style="color:#16a34a;font-weight:700">✅ Running</span></td></tr>
        <tr><td><strong>Vectorstore</strong></td><td>${{d.vectorstore==='ready'?'✅ Ready ('+d.chunks+' chunks, '+d.kb_files+' files)':'❌ Not initialized'}}</td></tr>
        <tr><td><strong>OpenAI API</strong></td><td>${{d.openai?'✅ Configured':'❌ Missing'}}</td></tr>
        <tr><td><strong>Anthropic API</strong></td><td>${{d.anthropic?'✅ Configured':'❌ Missing'}}</td></tr>
        <tr><td><strong>PRIMO API</strong></td><td>✅ Via Cloudflare Worker</td></tr>
        <tr><td><strong>Memory Usage</strong></td><td><span style="color:${{memColor}};font-weight:700">${{d.mem_pct}}%</span> (${{d.mem_used_mb}}MB / ${{d.mem_total_mb}}MB)</td></tr>
        <tr><td><strong>Uptime</strong></td><td>${{uptimeMin < 60 ? uptimeMin+'m' : Math.floor(uptimeMin/60)+'h '+uptimeMin%60+'m'}}</td></tr>
      </table>
      <div style="margin-top:8px;font-size:.74rem;color:#6b7280">Last checked: ${{new Date().toLocaleTimeString()}}</div>`;
  }}catch(e){{
    el.innerHTML='<span style="color:#dc2626">❌ Cannot reach HF Space: '+e.message+'</span>';
  }}
}}

// Load status on page load and every 30 seconds
loadStatus();
setInterval(loadStatus, 30000);
</script>
</body></html>"""


# ---- Clear FAISS cache endpoint ----
@app.post("/clear-cache")
async def clear_cache(request: Request):
    if not verify_session(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        import shutil
        removed = []
        for path in ["/data/faiss_index", "faiss_index"]:
            if os.path.exists(path):
                shutil.rmtree(path)
                removed.append(path)
        # Also list current knowledge files
        kb_files = glob.glob(os.path.join(KNOWLEDGE_DIR, "*.txt"))
        return {
            "status": "ok",
            "removed_paths": removed,
            "kb_files_found": len(kb_files),
            "kb_files": [os.path.basename(f) for f in sorted(kb_files)]
        }
    except Exception as e:
        return {"error": str(e)}


# ---- Restart Space endpoint ----
@app.post("/restart")
async def restart_space(request: Request):
    if not verify_session(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    import threading
    def do_restart():
        import time as t
        t.sleep(1)
        os.kill(os.getpid(), 9)  # Force restart — HF Space will auto-restart
    threading.Thread(target=do_restart, daemon=True).start()
    return {"status": "restarting", "message": "Space is restarting. Please wait 30-60 seconds."}


# ---- Status endpoint (no auth needed — for frontend health checks) ----
@app.get("/status")
async def get_status():
    # Read container-level memory from /sys/fs/cgroup (accurate for HF Spaces)
    # psutil reads the host machine memory which is misleading on shared containers
    try:
        # cgroup v2 (HF Spaces uses this)
        with open('/sys/fs/cgroup/memory.current') as f:
            mem_used_bytes = int(f.read().strip())
        with open('/sys/fs/cgroup/memory.max') as f:
            val = f.read().strip()
            mem_total_bytes = int(val) if val != 'max' else 16 * 1024**3  # 16GB default
        mem_used_mb = round(mem_used_bytes / 1024 / 1024)
        mem_total_mb = round(mem_total_bytes / 1024 / 1024)
        mem_pct = round(mem_used_bytes / mem_total_bytes * 100)
    except:
        # Fallback: try cgroup v1
        try:
            with open('/sys/fs/cgroup/memory/memory.usage_in_bytes') as f:
                mem_used_bytes = int(f.read().strip())
            with open('/sys/fs/cgroup/memory/memory.limit_in_bytes') as f:
                mem_total_bytes = int(f.read().strip())
            mem_used_mb = round(mem_used_bytes / 1024 / 1024)
            mem_total_mb = round(mem_total_bytes / 1024 / 1024)
            mem_pct = round(mem_used_bytes / mem_total_bytes * 100)
        except:
            mem_used_mb = mem_total_mb = mem_pct = 0

    kb_files = glob.glob(os.path.join(KNOWLEDGE_DIR, "*.txt"))
    chunks = vectorstore.index.ntotal if vectorstore else 0

    return {
        "status": "ok",
        "vectorstore": "ready" if vectorstore else "not_initialized",
        "chunks": chunks,
        "kb_files": len(kb_files),
        "openai": bool(os.environ.get("OPENAI_API_KEY")),
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "primo": bool(os.environ.get("PRIMO_API_KEY")) or True,  # Key lives in Cloudflare Worker
        "mem_used_mb": mem_used_mb,
        "mem_total_mb": mem_total_mb,
        "mem_pct": mem_pct,
        "uptime_secs": round(time.time() - START_TIME),
    }


# ---- Admin stats from D1 (kept for API compatibility) ----
@app.get("/admin/stats")
async def admin_stats(request: Request):
    if not verify_session(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    # Stats now come from Cloudflare D1 via /analytics endpoint
    return {"message": "Use Cloudflare Worker /analytics endpoint for D1 data"}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    total = conn.execute("SELECT COUNT(*) as c FROM queries").fetchone()["c"]
    today = conn.execute("SELECT COUNT(*) as c FROM queries WHERE timestamp >= date('now')").fetchone()["c"]
    tools = {r["tool_used"]: r["c"] for r in conn.execute("SELECT tool_used, COUNT(*) as c FROM queries GROUP BY tool_used").fetchall()}
    models = {r["model"]: r["c"] for r in conn.execute("SELECT model, COUNT(*) as c FROM queries GROUP BY model").fetchall()}
    conn.close()
    return {"total": total, "today": today, "tools": tools, "models": models}


# ---- Admin Config GET/POST (protected) ----
@app.get("/admin/config")
async def admin_get_config(request: Request):
    if not verify_session(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT key, value, updated_at FROM bot_config").fetchall()
    conn.close()
    return {r["key"]: {"value": r["value"], "updated_at": r["updated_at"]} for r in rows}


@app.post("/admin/config")
async def admin_set_config(request: Request):
    if not verify_session(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    data = await request.json()
    settings = data.get("settings", data) if isinstance(data, dict) else data
    for key, value in settings.items():
        set_config(key, str(value))
    return {"status": "ok", "updated": list(settings.keys())}


# ---- Public config (for frontend) ----
@app.get("/config")
async def public_config():
    return {
        "welcome_message": get_config("welcome_message"),
        "bot_personality": get_config("bot_personality"),
        "custom_instructions": get_config("custom_instructions"),
        "announcement": get_config("announcement"),
        "default_model": get_config("default_model", "gpt"),
        "maintenance_mode": get_config("maintenance_mode", "false"),
        "maintenance_message": get_config("maintenance_message"),
        "max_results": get_config("max_results", "5"),
    }


# ---- Clear logs ----
@app.post("/admin/clear-logs")
async def clear_logs():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM queries")
    conn.commit()
    conn.close()
    return {"status": "ok", "message": "All logs cleared"}
