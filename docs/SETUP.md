# 📖 LibBee — Complete Setup Guide

**Estimated time:** 45–60 minutes  
**Cost:** $0 (all free tiers)  
**Technical level:** Beginner friendly — no coding required

---

## Overview

You need to set up 3 platforms:

```
GitHub Pages          Cloudflare Worker        Hugging Face Space
(Chat interface)  →   (API proxy + DB)    →   (AI/RAG backend)
    index.html            worker.js               app.py
    config.js             D1 database             requirements.txt
                                                  knowledge/ files
```

---

## PHASE 1 — Get the Code (5 minutes)

### Step 1: Fork this GitHub Repository

1. Go to: `github.com/[org]/libbee`
2. Click **Fork** (top right)
3. Select your GitHub account
4. Click **Create Fork**
5. You now have your own copy at:
   `github.com/[your-username]/libbee`

---

## PHASE 2 — Hugging Face Space (15 minutes)

### Step 2: Create Hugging Face Account

1. Go to: [huggingface.co](https://huggingface.co)
2. Click **Sign Up** — free, no credit card
3. Verify your email

### Step 3: Create a New Space

1. Click your profile picture → **New Space**
2. Fill in:
   - **Space name:** `libbee` (or `your-library-ai`)
   - **License:** MIT
   - **SDK:** `Gradio` — then change to `Static` then back — actually select **nothing/blank** and we will use FastAPI auto-detection
   - **Visibility:** Public
3. Click **Create Space**

> **Note:** HF Spaces automatically detects FastAPI from `app.py` — no SDK selection needed.

### Step 4: Upload Backend Files

1. In your new Space → click **Files** tab
2. Click **Add file** → **Upload files**
3. Upload from your forked repo's `backend/` folder:
   - `app.py`
   - `requirements.txt`
4. Click **Commit changes**

### Step 5: Create Knowledge Folder

1. In the Files tab → click **Add file** → **Create new file**
2. Name it: `knowledge/placeholder.txt`
3. Content: `This is a placeholder. Add your library knowledge files here.`
4. Click **Commit new file**
5. Upload your library `.txt` files into `knowledge/`
   (See [KNOWLEDGE_BASE.md](KNOWLEDGE_BASE.md) for how to write these)

### Step 6: Set API Keys as Secrets

1. In your Space → click **Settings** tab
2. Scroll to **Variables and Secrets**
3. Click **New Secret** for each:

| Secret Name | Value | Where to get |
|-------------|-------|-------------|
| `GROQ_API_KEY` | your Groq key | [console.groq.com](https://console.groq.com) → API Keys → Create |
| `ADMIN_PASSWORD` | choose a strong password | anything you choose |
| `OPENAI_API_KEY` | your OpenAI key *(optional)* | [platform.openai.com](https://platform.openai.com) → API Keys |
| `ANTHROPIC_API_KEY` | your Anthropic key *(optional)* | [console.anthropic.com](https://console.anthropic.com) → API Keys |

4. Click **Save** after each secret

### Step 7: Wait for Build

1. Go to **App** tab in your Space
2. Wait for status: `Building` → `Running` (takes 2–5 minutes)
3. Once Running, test it — open this URL in your browser:
   ```
   https://[your-username]-libbee.hf.space/year
   ```
   You should see: `{"year": 2026}`

4. **Copy your HF Space URL** — you need it later:
   ```
   https://[your-username]-libbee.hf.space
   ```

---

## PHASE 3 — Cloudflare Worker + Database (15 minutes)

### Step 8: Create Cloudflare Account

1. Go to: [cloudflare.com](https://cloudflare.com)
2. Click **Sign Up** — free
3. Verify your email

### Step 9: Create D1 Database

1. In Cloudflare dashboard → left sidebar → **Workers & Pages**
2. Click **D1 SQL Database** → **Create database**
3. Name: `libbee-analytics`
4. Click **Create**
5. **Copy your Database ID** from the settings — you need it later

### Step 10: Initialize the Database

1. In your new D1 database → click **Console** tab
2. Paste and run this SQL:

```sql
CREATE TABLE IF NOT EXISTS queries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT NOT NULL,
  question TEXT,
  tool_used TEXT,
  model TEXT,
  response_time REAL DEFAULT 0,
  result_count INTEGER DEFAULT 0,
  error TEXT
);

CREATE TABLE IF NOT EXISTS bot_config (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT
);
```

3. Click **Execute**

> **Alternatively:** Skip this step — the Worker has a `/analytics/init` endpoint that creates the tables automatically. Just open `https://your-worker.workers.dev/analytics/init` once after deploying the Worker.

### Step 11: Deploy Cloudflare Worker

1. In Cloudflare → **Workers & Pages** → **Create**
2. Click **Create Worker**
3. Name: `libbee-worker`
4. Click **Deploy**
5. Click **Edit Code**
6. **Delete all existing code**
7. Open `worker/worker.js` from your GitHub repo
8. **Copy all the code** and paste it into the editor
9. Click **Deploy**

### Step 12: Bind D1 Database to Worker

1. In your Worker → **Settings** tab → **Bindings**
2. Click **Add** → **D1 Database**
3. Variable name: `DB`
4. D1 database: `libbee-analytics`
5. Click **Deploy**

### Step 13: Set Worker Secrets

1. In your Worker → **Settings** → **Variables**
2. Under **Environment Variables** → **Add variable**:

| Variable Name | Value |
|---------------|-------|
| `GROQ_API_KEY` | same Groq key as HF Space |
| `OPENAI_API_KEY` | same OpenAI key *(optional)* |
| `ANTHROPIC_API_KEY` | same Anthropic key *(optional)* |
| `PRIMO_API_KEY` | from Ex Libris developer portal *(if using PRIMO)* |

3. Click **Save and Deploy**

4. **Copy your Worker URL:**
   ```
   https://libbee-worker.[your-subdomain].workers.dev
   ```

### Step 14: Initialize Database via URL

Open this in your browser (replace with your Worker URL):
```
https://libbee-worker.xxx.workers.dev/analytics/init
```
You should see: `{"status": "ok", "message": "Database initialized"}`

---

## PHASE 4 — Frontend / GitHub Pages (5 minutes)

### Step 15: Edit config.js

1. In your forked GitHub repo → `frontend/` folder
2. Click on `config.js`
3. Click the **pencil icon** (Edit)
4. Update these values:

```javascript
const LIBBEE_CONFIG = {

  // ── REQUIRED: Your two URLs ──
  WORKER_URL:    'https://libbee-worker.xxx.workers.dev',  // ← your Worker URL
  HF_SPACE_URL:  'https://yourusername-libbee.hf.space',  // ← your HF Space URL

  // ── Your library details ──
  LIBRARY_NAME:  'City Public Library',           // ← your library name
  BOT_NAME:      'LibBee',                        // ← keep or rename
  UNIVERSITY:    'Your University Name',           // ← if academic library

  // ── Your library website ──
  LIBRARY_URL:   'https://library.youruniversity.edu',
  ASKUS_URL:     'https://library.youruniversity.edu/askus',
  ERESOURCES_URL:'https://library.youruniversity.edu/eresources',

  // ── Colors (optional — customize your branding) ──
  PRIMARY_COLOR: '#003366',
  ACCENT_COLOR:  '#C8922A',

  // ── PRIMO catalog (leave blank if not using PRIMO) ──
  PRIMO_VID:     '',
  PRIMO_BASE:    '',

  // ── Koha catalog (leave blank if not using Koha) ──
  KOHA_URL:      '',
};
```

5. Click **Commit changes**

### Step 16: Enable GitHub Pages

1. In your GitHub repo → **Settings**
2. Click **Pages** (left sidebar)
3. Under **Source** → **Deploy from a branch**
4. Branch: `main` / Folder: `/frontend`
5. Click **Save**
6. Wait 1–2 minutes
7. Your chat is live at:
   ```
   https://[your-username].github.io/libbee
   ```

---

## PHASE 5 — Admin Panel Configuration (10 minutes)

### Step 17: Open Admin Panel

1. Go to: `https://[your-username]-libbee.hf.space/admin`
2. Enter your `ADMIN_PASSWORD`
3. Click **Login**

### Step 18: Configure Bot Behavior

1. Click **Bot Behavior** tab
2. Set:
   - **Welcome Message** — first message users see
   - **Bot Personality** — system prompt for all LLM calls
   - **Default Model** — GPT or Claude
   - **Max Search Results** — how many catalog results to show
3. Click **💾 Save Config**

### Step 19: Build Knowledge Base

1. Make sure you've uploaded `.txt` files to `knowledge/` in HF Space
2. In Admin → **System** tab
3. Click **🔄 Rebuild RAG**
4. Wait for: `✅ Rebuilt: X chunks from Y files`
5. Click the expandable list to verify your files are loaded

---

## PHASE 6 — Test (5 minutes)

### Step 20: Test Your Chatbot

Open your GitHub Pages URL and test:

| Test | Expected Result |
|------|----------------|
| Ask: `"What are the library hours?"` | Answer from your knowledge base |
| Ask: `"Find books on data science"` | Boolean search → catalog results |
| Ask: `"Who is the prime minister of France?"` | Two buttons → click AI → answer |
| Admin → System → Live Status | All green ✅ |
| Admin → Analytics | Shows query count |

---

## 🎉 You're Live!

Share your chat URL with library users:
```
https://[your-username].github.io/libbee
```

**Embed in your library website:**
```html
<iframe
  src="https://[your-username].github.io/libbee"
  width="100%"
  height="700px"
  frameborder="0">
</iframe>
```

---

## 🔧 Troubleshooting

| Problem | Solution |
|---------|----------|
| "AI service is waking up" | HF Space was idle — wait 30–60 seconds |
| Chat shows empty bubble | Check `config.js` URLs are correct |
| "0 chunks" after Rebuild RAG | Upload `.txt` files to `knowledge/` folder in HF Space first |
| Admin panel inaccessible | Check `ADMIN_PASSWORD` is set in HF Space secrets |
| Catalog search not working | Check `PRIMO_VID` or `KOHA_URL` in `config.js` |
| Analytics showing empty questions | Check Cloudflare Worker D1 binding is set to `DB` |

---

## 📞 Getting Help

- 📖 Docs: [github.com/[org]/libbee/docs](https://github.com)
- 💬 Discussions: [github.com/[org]/libbee/discussions](https://github.com)
- 🐛 Bugs: [github.com/[org]/libbee/issues](https://github.com)
