// ============================================================
// Cloudflare Worker — Claude + OpenAI + PRIMO + D1 Analytics
// 
// SECRETS: ANTHROPIC_API_KEY, OPENAI_API_KEY, PRIMO_API_KEY
// D1 BINDING: DB → ku-library-analytics
// ============================================================

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { ...CORS, 'Content-Type': 'application/json' } });
const err = (msg, status = 500) => json({ error: { message: msg } }, status);

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') return new Response(null, { headers: CORS });
    const p = new URL(request.url).pathname;

    if (p === '/claude')           return proxyClaude(request, env);
    if (p === '/openai')           return proxyOpenAI(request, env);
    if (p === '/primo')            return proxyPRIMO(request, env);
    if (p === '/log')              return logQuery(request, env);
    if (p === '/analytics')        return getAnalytics(env);
    if (p === '/analytics/recent') return getRecent(env);
    if (p === '/analytics/init')   return initDB(env);

    return err('Not found', 404);
  }
};

// ===== D1 ANALYTICS =====
async function initDB(env) {
  if (!env.DB) return err('D1 not bound. Add [[d1_databases]] binding in wrangler.toml');
  try {
    await env.DB.exec("CREATE TABLE IF NOT EXISTS queries (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, question TEXT NOT NULL, tool_used TEXT, model TEXT, response_time REAL DEFAULT 0, result_count INTEGER DEFAULT 0, error TEXT)");
    return json({ status: 'ok', message: 'Database initialized' });
  } catch (e) { return err('Init: ' + e.message); }
}

async function logQuery(request, env) {
  if (!env.DB) return json({ status: 'ok', warning: 'no DB' });
  try {
    const b = await request.json();
    await env.DB.prepare(
      "INSERT INTO queries (timestamp,question,tool_used,model,response_time,result_count,error) VALUES (datetime('now'),?,?,?,?,?,?)"
    ).bind(b.question||'', b.tool||'unknown', b.model||'gpt', b.response_time||0, b.result_count||0, b.error||null).run();
    return json({ status: 'ok' });
  } catch (e) { return json({ status: 'ok', warning: e.message }); }
}

async function getAnalytics(env) {
  if (!env.DB) return err('D1 not bound');
  try {
    const total = await env.DB.prepare("SELECT COUNT(*) as c FROM queries").first();
    const today = await env.DB.prepare("SELECT COUNT(*) as c FROM queries WHERE timestamp>=date('now')").first();
    const week = await env.DB.prepare("SELECT COUNT(*) as c FROM queries WHERE timestamp>=date('now','-7 days')").first();
    const avgTime = await env.DB.prepare("SELECT COALESCE(AVG(response_time),0) as a FROM queries").first();
    const errors = await env.DB.prepare("SELECT COUNT(*) as c FROM queries WHERE error IS NOT NULL AND error != ''").first();
    const tools = await env.DB.prepare("SELECT COALESCE(tool_used,'unknown') as tool_used, COUNT(*) as c FROM queries GROUP BY tool_used ORDER BY c DESC").all();
    const models = await env.DB.prepare("SELECT COALESCE(model,'gpt') as model, COUNT(*) as c FROM queries GROUP BY model ORDER BY c DESC").all();
    const popular = await env.DB.prepare("SELECT question, COUNT(*) as c FROM queries WHERE question IS NOT NULL AND question != '' GROUP BY question ORDER BY c DESC LIMIT 20").all();
    const hourly = await env.DB.prepare("SELECT substr(timestamp,12,2) as hour, COUNT(*) as c FROM queries WHERE timestamp IS NOT NULL GROUP BY hour ORDER BY hour").all();
    const daily = await env.DB.prepare("SELECT substr(timestamp,1,10) as day, COUNT(*) as c FROM queries WHERE timestamp IS NOT NULL GROUP BY day ORDER BY day DESC LIMIT 14").all();

    return json({
      total: total?.c||0, today: today?.c||0, week: week?.c||0,
      avg_time: avgTime?.a||0, errors: errors?.c||0,
      tools: (tools.results||[]), models: (models.results||[]),
      popular: (popular.results||[]), hourly: (hourly.results||[]),
      daily: (daily.results||[]).reverse()
    });
  } catch (e) { return err('Analytics: ' + e.message); }
}

async function getRecent(env) {
  if (!env.DB) return err('D1 not bound');
  try {
    const r = await env.DB.prepare("SELECT * FROM queries ORDER BY id DESC LIMIT 50").all();
    return json({ results: r.results||[] });
  } catch (e) { return err('Recent: ' + e.message); }
}

// ===== API PROXIES =====
async function proxyClaude(request, env) {
  try {
    if (!env.ANTHROPIC_API_KEY) return err('ANTHROPIC_API_KEY not configured');
    const body = await request.json();
    const payload = { model: body.model||'claude-sonnet-4-20250514', max_tokens: body.max_tokens||500, messages: body.messages };
    if (body.system) payload.system = body.system;
    if (body.tools) payload.tools = body.tools;
    const headers = { 'Content-Type':'application/json', 'x-api-key': env.ANTHROPIC_API_KEY, 'anthropic-version':'2023-06-01' };

    // Retry up to 2 times on 429
    let r, attempts = 0;
    while (attempts <= 2) {
      r = await fetch('https://api.anthropic.com/v1/messages', { method:'POST', headers, body: JSON.stringify(payload) });
      if (r.status !== 429) break;
      attempts++;
      if (attempts <= 2) await new Promise(res => setTimeout(res, 1000 * attempts));
    }

    if (r.status === 429) {
      return json({
        content: [{ type:'text', text:'⚠️ The AI service is currently busy. Please try again in a few seconds, or switch to ChatGPT using the toggle above.' }]
      }, 200);
    }

    return new Response(JSON.stringify(await r.json()), { status: r.status, headers: {...CORS,'Content-Type':'application/json'} });
  } catch (e) { return err('Claude proxy: '+e.message); }
}

async function proxyOpenAI(request, env) {
  try {
    if (!env.OPENAI_API_KEY) return err('OPENAI_API_KEY not configured');
    const body = await request.json();
    const payload = JSON.stringify({
      model: body.model||'gpt-4o-mini',
      max_tokens: body.max_tokens||500,
      messages: body.messages
    });
    const headers = { 'Content-Type':'application/json', 'Authorization':`Bearer ${env.OPENAI_API_KEY}` };

    // Retry up to 2 times on 429 with exponential backoff
    let r, attempts = 0;
    while (attempts <= 2) {
      r = await fetch('https://api.openai.com/v1/chat/completions', { method:'POST', headers, body: payload });
      if (r.status !== 429) break;
      attempts++;
      if (attempts <= 2) await new Promise(res => setTimeout(res, 1000 * attempts)); // 1s, 2s
    }

    if (r.status === 429) {
      return json({
        choices: [{ message: { content: '⚠️ The AI service is currently busy due to high demand. Please try again in a few seconds, or switch to Claude using the toggle above.' } }]
      }, 200); // Return 200 so frontend handles gracefully
    }

    return new Response(JSON.stringify(await r.json()), { status: r.status, headers: {...CORS,'Content-Type':'application/json'} });
  } catch (e) { return err('OpenAI proxy: '+e.message); }
}

async function proxyPRIMO(request, env) {
  try {
    if (!env.PRIMO_API_KEY) return err('PRIMO_API_KEY not configured');
    const body = await request.json();
    const q = body.query||'';
    const limit = Math.min(body.limit||5, 20);
    const offset = body.offset||0;
    const vid = 'YOUR_PRIMO_VID';
    const scope = body.scope||'MyInst_and_CI';
    const tab = body.tab||'Everything';
    let facets = '';
    if (body.peer_reviewed) facets += '&qInclude=facet_tlevel,exact,peer_reviewed';
    if (body.open_access) facets += '&qInclude=facet_tlevel,exact,open_access';
    if (body.resource_type) facets += '&qInclude=facet_rtype,exact,'+encodeURIComponent(body.resource_type);
    if (body.year_from||body.year_to) {
      const yf = body.year_from||'1900';
      const yt = body.year_to||new Date().getFullYear().toString();
      facets += '&multiFacets=facet_searchcreationdate,include,'+yf+'%7C,%7C'+yt;
    }
    const base = 'https://api-eu.hosted.exlibrisgroup.com/primo/v1/search';
    const qs = `?vid=${vid}&tab=${tab}&scope=${scope}&q=any,contains,${encodeURIComponent(q)}&lang=en&sort=rank&limit=${limit}&offset=${offset}&apikey=${env.PRIMO_API_KEY}${facets}`;
    let r = await fetch(base+qs, { headers:{'Accept':'application/json'} });
    if (!r.ok) r = await fetch(base.replace('api-eu','api-na')+qs, { headers:{'Accept':'application/json'} });
    if (!r.ok) r = await fetch(base.replace('api-eu','api-ap')+qs, { headers:{'Accept':'application/json'} });
    if (!r.ok) return err('PRIMO API error '+r.status, r.status);
    return json(parsePrimo(await r.json()));
  } catch (e) { return err('PRIMO proxy: '+e.message); }
}

function parsePrimo(data) {
  const total = data.info?.total||0;
  const results = (data.docs||[]).map(doc => {
    const d=doc.pnx?.display||{}, a=doc.pnx?.addata||{}, s=doc.pnx?.search||{}, c=doc.pnx?.control||{}, l=doc.pnx?.links||{};
    const dateVal = (s.creationdate||a.risdate||a.date||d.creationdate||[''])[0];
    return {
      id:(c.recordid||[''])[0], title:(d.title||['Untitled'])[0],
      creator:(d.creator||d.contributor||[]).join('; ')||'Unknown',
      date:(dateVal||'').replace(/\D+$/,'').trim()||'',
      type:(d.type||[''])[0], source:(d.source||a.jtitle||[''])[0],
      description:((d.description||[''])[0]||'').substring(0,600),
      doi:(a.doi||[null])[0], volume:(a.volume||[null])[0],
      issue:(a.issue||[null])[0], spage:(a.spage||[null])[0], epage:(a.epage||[null])[0],
      openaccess:(d.oa||[''])[0]==='free_for_read',
      link:(l.openurl||l.linktorsrc||[''])[0]||null,
    };
  });
  return { total, results };
}
