// ============================================================
//  LibBee Configuration — EDIT THIS FILE FOR YOUR LIBRARY
//  This is the ONLY file you need to edit to set up LibBee
// ============================================================

const LIBBEE_CONFIG = {

  // ── REQUIRED: Infrastructure URLs ──
  WORKER_URL:    'https://curly-shape-865c.oalibraryai.workers.dev',
  HF_SPACE_URL:  'https://libraryai-libai.hf.space',

  // ── Library Identity ──
  LIBRARY_NAME:  'Calicut Universiy Library',         // Shown in header and welcome
  BOT_NAME:      'LibBee',                    // Bot name in header
  BOT_TAGLINE:   'Calicut University Library AI Assistant', // Subtitle in header
  UNIVERSITY:    'University of Calicut',       // University name
  COUNTRY:       'India',              // Country name

  // ── Library Website URLs ──
  LIBRARY_URL:    'https://library.uoc.ac.in/en/',
  ASKUS_URL:      'https://library.uoc.ac.in/en/',
  ERESOURCES_URL: 'https://library.uoc.ac.in/en/resources/digital-library',
  EVENTS_URL:     'https://library.youruniversity.edu/events',

  // ── Branding ──
  PRIMARY_COLOR:  '#003366',   // Header and button colour
  ACCENT_COLOR:   '#C8922A',   // Accent colour

  // ── Koha Catalog (REQUIRED for catalog search) ──
  KOHA_URL:       '',          // e.g. 'http://www.mgucat.mgu.ac.in/'

  // ── Institutional Repository (optional) ──
  REPOSITORY_URL: '',          // e.g. 'https://scholar.uoc.ac.in/home'

  // ── Default Model ──
  DEFAULT_MODEL:  'groq',      // 'groq' (free) | 'gpt' | 'claude'

  // ── PRIMO catalog (optional — leave blank if using Koha) ──
  PRIMO_VID:      '',
  PRIMO_BASE:     '',
  PRIMO_AI_URL:   '',

};
