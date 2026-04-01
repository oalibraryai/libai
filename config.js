// ============================================================
//  LibBee Configuration — EDIT THIS FILE FOR YOUR LIBRARY
//  This is the ONLY file you need to edit to set up LibBee
// ============================================================

const LIBBEE_CONFIG = {

  // ── Infrastructure URLs (set after deploying HF Space and Cloudflare Worker) ──
  WORKER_URL:    'https://YOUR-WORKER.workers.dev',      // Cloudflare Worker URL
  HF_SPACE_URL:  'https://YOUR-USERNAME-libbee.hf.space', // Hugging Face Space URL

  // ── Library Identity ──
  LIBRARY_NAME:  'Your Library Name',
  BOT_NAME:      'LibBee',
  BOT_TAGLINE:   'Your Library AI Assistant',
  UNIVERSITY:    'Your University Name',

  // ── Library Website URLs ──
  LIBRARY_URL:   'https://library.youruniversity.edu',
  ASKUS_URL:     'https://library.youruniversity.edu/askus',
  ERESOURCES_URL:'https://library.youruniversity.edu/eresources',

  // ── Branding ──
  PRIMARY_COLOR: '#003366',   // Main colour (header, buttons)
  ACCENT_COLOR:  '#C8922A',   // Accent colour

  // ── Library Catalog (PRIMO) — leave blank if not using PRIMO ──
  PRIMO_VID:     '',          // e.g. 'YOUR_VID_HERE'
  PRIMO_BASE:    '',          // e.g. 'https://yourlib.primo.exlibrisgroup.com/discovery/search'
  PRIMO_AI_URL:  '',          // e.g. 'https://yourlib.primo.exlibrisgroup.com/discovery/researchAssistant?...'

  // ── Koha Catalog — leave blank if not using Koha ──
  KOHA_URL:      '',          // e.g. 'https://koha.yourlibrary.org'

  // ── Institutional Repository — leave blank if none ──
  REPOSITORY_URL: '',         // e.g. 'https://repository.youruniversity.edu'

};
