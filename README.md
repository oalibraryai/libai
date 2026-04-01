# 🐝 LibBee — Open Source AI Library Assistant

> Deploy a full AI-powered library chatbot in under 1 hour. No coding required after initial setup.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com/)

---

## ✨ What is LibBee?

LibBee is a production-grade AI assistant for academic and public libraries. It combines:

- 🤖 **Dual LLM support** — Groq (free/open source), GPT-4o-mini, or Claude Sonnet
- 📚 **RAG (Retrieval-Augmented Generation)** — answers from your own library knowledge base
- 🔍 **Catalog search** — Koha (open source) or Ex Libris PRIMO
- 🌐 **Web search** — for current events and general knowledge
- 📖 **PubMed + Consensus** — biomedical and scholarly search
- ⚙️ **Admin dashboard** — live monitoring, bot behavior control, RAG management
- 💰 **Near-zero cost** — runs entirely on free tiers ($0–30/month)

---

## 🚀 Quick Start

### What you need to create (one time):
| Platform | What | Cost |
|----------|------|------|
| GitHub | Fork this repo + enable Pages | Free |
| Hugging Face | New Space (FastAPI) | Free |
| Cloudflare | Worker + D1 database | Free |
| Groq | API key for LLM | Free |

### 4 Steps to Deploy:

**1. Fork this repo** → Enable GitHub Pages → edit `frontend/config.js` with your 2 URLs

**2. Create HF Space** → upload `backend/app.py` + `backend/requirements.txt` → set secrets

**3. Create Cloudflare Worker** → paste `worker/worker.js` → create D1 database → set secrets

**4. Open Admin Panel** → complete Setup Wizard → upload knowledge files → Rebuild RAG

📖 **Full step-by-step guide:** [docs/SETUP.md](docs/SETUP.md)

---

## 📁 Repository Structure

```
libbee/
├── frontend/
│   ├── index.html          ← Chat interface (GitHub Pages)
│   └── config.js           ← YOUR ONLY EDIT — 2 URLs + library name
│
├── backend/                ← Upload to Hugging Face Space
│   ├── app.py              ← FastAPI RAG backend
│   └── requirements.txt    ← Python dependencies
│
├── worker/                 ← Paste into Cloudflare Worker
│   └── worker.js           ← API proxy + analytics
│
├── knowledge/
│   └── examples/           ← Sample knowledge base files
│       ├── library_hours.txt
│       ├── borrowing_policy.txt
│       ├── databases.txt
│       └── faq.txt
│
└── docs/
    ├── SETUP.md            ← Complete deployment guide
    ├── KNOWLEDGE_BASE.md   ← How to write KB files
    └── CONFIGURATION.md    ← All config options
```

---

## 💰 Cost Breakdown

| Component | Free Tier | Estimated Cost |
|-----------|-----------|---------------|
| GitHub Pages | Unlimited | $0 |
| Cloudflare Workers | 100K req/day | $0 |
| Cloudflare D1 | 5M reads/day | $0 |
| Hugging Face Spaces | Free (restarts after idle) | $0 |
| Groq API (Llama 3.3) | 1,000 req/day | $0 |
| OpenAI GPT-4o-mini (optional) | — | ~$5–15/month |
| Anthropic Claude (optional) | — | ~$5–10/month |
| **TOTAL** | | **$0–30/month** |

---

## 🏛️ Used By

- Khalifa University Library, UAE *(original deployment)*
- *Your library here — submit a PR!*

---

## 📖 Documentation

| Guide | Description |
|-------|-------------|
| [SETUP.md](docs/SETUP.md) | Complete step-by-step deployment |
| [KNOWLEDGE_BASE.md](docs/KNOWLEDGE_BASE.md) | How to write knowledge files |
| [CONFIGURATION.md](docs/CONFIGURATION.md) | All config.js options explained |

---

## 🤝 Contributing

Pull requests welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

**Ways to contribute:**
- Add support for new library catalogs (Evergreen, FOLIO, WorldCat)
- Add new MCP tools (Scopus, Web of Science, IEEE)
- Translate knowledge base templates to other languages
- Share your library's deployment as a case study

---

## 📄 License

MIT License — free to use, modify, and distribute.
See [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgements

Built with: [LangChain](https://langchain.com) · [FAISS](https://github.com/facebookresearch/faiss) · [FastAPI](https://fastapi.tiangolo.com) · [Groq](https://groq.com) · [Hugging Face](https://huggingface.co) · [Cloudflare](https://cloudflare.com)
