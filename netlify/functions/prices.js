// Farm Fayre calc API v3 — server-side calculation.
// Raw price data NEVER leaves this function. The browser receives only:
//   /api/breeds  — category/breed structure (names, no prices)
//   /api/price   — one price + trend for a specific breed/weight (hint bar)
//   /api/compare — computed comparison result (cards, tally, trend)
const fs = require('fs');
const path = require('path');

let DATA = null;
let FACTORY = null;
const FACTORY_CANDIDATES = [
  require('path').resolve(process.cwd(), '_data/factory_moves.json'),
  require('path').resolve(__dirname, '_data/factory_moves.json'),
  require('path').resolve(__dirname, '../../_data/factory_moves.json'),
  '/var/task/_data/factory_moves.json',
];
function loadFactory() {
  if (FACTORY !== null) return FACTORY;
  for (const p of FACTORY_CANDIDATES) {
    try { FACTORY = JSON.parse(fs.readFileSync(p, 'utf8')); return FACTORY; } catch(e) {}
  }
  FACTORY = false; // sentinel: not available
  return FACTORY;
}
const PUBLIC_TO_INTERNAL = {
  'male/bullocks': 'male/bullocks',
  'male/bulls': 'male/weanling_bulls',
  'female/heifers': 'female/heifers',
  'female/dry_cows': 'female/dry_fat_cows',
};
function factoryInterim(sex, category, mean, weekEnding) {
  // Returns {factoryMoveCents, estimate, coefficient} when the factory moved
  // >= trigger since the settled mart week; otherwise null.
  const f = loadFactory();
  if (!f || !f.moves) return null;
  // Staleness guard: a factory move only overlays LIVE if its week postdates the
  // settled mart week. If factory week <= mart week, the mart set already absorbed
  // it - re-applying would double-count. (Most weeks: DAFM lags mart, so no overlay.)
  if (!f.week || !weekEnding || new Date(f.week) <= new Date(weekEnding)) return null;
  const key = PUBLIC_TO_INTERNAL[sex + '/' + category];
  if (!key) return null;
  const mv = f.moves[key];
  const trig = f.trigger_cents || 10;
  const coef = f.coefficient || 0.75;
  if (mv == null || Math.abs(mv) < trig) return null;
  const estimate = Math.round((mean + coef * mv / 100) * 20) / 20; // 5c rounding
  return { factoryMoveCents: mv, estimate, coefficient: coef, factoryWeek: f.week };
}
const CANDIDATES = [
  path.resolve(process.cwd(), '_data/market_data.json'),
  path.resolve(__dirname, '_data/market_data.json'),
  path.resolve(__dirname, '../../_data/market_data.json'),
  '/var/task/_data/market_data.json',
];
function loadData() {
  if (DATA) return DATA;
  for (const p of CANDIDATES) {
    try { DATA = JSON.parse(fs.readFileSync(p, 'utf8')); return DATA; } catch(e) {}
  }
  throw new Error('data not found');
}

// ---- Calc functions (ported from client JS, identical logic) ----

function findBandPrice(breedBands, weight) {
  // Quarter-zone linear taper (v3.1): bottom 25% of each band blends linearly
  // with the lower band (50/50 at the boundary), middle 50% is the pure band
  // price, top 25% blends linearly toward the upper band. Continuous everywhere.
  const bands = Object.keys(breedBands);
  if (!bands.length) return null;
  const parsed = bands.map(b => { const [lo, hi] = b.split('-').map(Number); return { band: b, lo, hi }; }).sort((a, b) => a.lo - b.lo);
  const cur = arr => (arr && arr.length) ? arr[arr.length - 1] : null;

  const inside = parsed.find(p => weight >= p.lo && weight < p.hi);
  if (!inside) {
    const nearest = weight < parsed[0].lo ? parsed[0] : parsed[parsed.length - 1];
    return { mean: cur(breedBands[nearest.band]), bandName: nearest.band, blended: false };
  }

  const insideCurrent = cur(breedBands[inside.band]);
  const width = inside.hi - inside.lo;
  const q = width * 0.25;
  const pos = weight - inside.lo;

  let neighbor = null, wInside = 1;
  if (pos < q) {
    neighbor = parsed.find(p => p.hi === inside.lo) || null;
    wInside = 0.5 + 0.5 * (pos / q);
  } else if (pos > width - q) {
    neighbor = parsed.find(p => p.lo === inside.hi) || null;
    wInside = 0.5 + 0.5 * ((width - pos) / q);
  }

  if (!neighbor) return { mean: insideCurrent, bandName: inside.band, blended: false };
  const neighborCurrent = cur(breedBands[neighbor.band]);
  if (neighborCurrent == null) return { mean: insideCurrent, bandName: inside.band, blended: false };
  if (insideCurrent == null) return { mean: neighborCurrent, bandName: neighbor.band, blended: false };
  return { mean: insideCurrent * wInside + neighborCurrent * (1 - wInside),
           bandName: inside.band + ' & ' + neighbor.band, blended: true };
}

function analyzeTrade(W, mean, ffBid, N) {
  const closeWeight = W * 0.975;
  const ringWeight  = W * 0.9375;
  const ffPerHead   = closeWeight * ffBid;
  const martSellerAvg    = ringWeight * mean;
  const martSellerTop    = ringWeight * mean * 1.05;
  const martSellerBottom = ringWeight * mean * 0.95;
  const phantomGood = W * 0.0075 * mean;
  const phantomAvg  = W * 0.0175 * mean;
  const agent = 20;
  const foregone = 0.31 * 70 * mean * Math.min(1, W / 500);
  const martBuyerGood = ringWeight * mean + phantomGood + agent + foregone;
  const martBuyerAvg  = ringWeight * mean + phantomAvg  + agent + foregone;
  const newspaperKg = mean * 1.085;
  const newspaperPerHead = ringWeight * newspaperKg;
  const sellerAvgDelta    = ffPerHead - martSellerAvg;
  const sellerTopDelta    = ffPerHead - martSellerTop;
  const sellerBottomDelta = ffPerHead - martSellerBottom;
  const buyerGoodDelta    = martBuyerGood - ffPerHead;
  const buyerAvgDelta     = martBuyerAvg  - ffPerHead;
  const landedGoodKg = Math.round(W * 0.93);
  const landedAvgKg  = Math.round(W * 0.92);
  return {
    W, mean, ffBid, N, closeWeight, ringWeight, ffPerHead,
    martSellerAvg, martSellerTop, martSellerBottom,
    martBuyerGood, martBuyerAvg,
    phantomGood, phantomAvg, agent, foregone,
    landedGoodKg, landedAvgKg,
    newspaperKg, newspaperPerHead,
    sellerAvgDelta, sellerTopDelta, sellerBottomDelta,
    buyerGoodDelta, buyerAvgDelta,
    sellerAvgLoss:    sellerAvgDelta    * N,
    sellerTopLoss:    sellerTopDelta    * N,
    sellerBottomLoss: sellerBottomDelta * N,
    buyerGoodCost:    buyerGoodDelta    * N,
    buyerAvgCost:     buyerAvgDelta     * N,
    ffTotal:          ffPerHead         * N,
    martBuyerGoodTotal: martBuyerGood   * N,
    martBuyerAvgTotal:  martBuyerAvg    * N,
  };
}

function pickTallyScenarios(a) {
  if (a.sellerAvgLoss <= 0) {
    return {
      seller: { label: "Seller's downside avoided", value: a.sellerBottomLoss, caption: "If the trade tanks at the mart" },
      buyer:  { label: "Buyer's cost", value: a.buyerGoodCost, caption: "Even on a good day at the mart" }
    };
  }
  const combinedPerHead = (a.sellerAvgLoss + a.buyerAvgCost) / a.N;
  if (combinedPerHead > 200) {
    return {
      seller: { label: "Seller's loss", value: a.sellerAvgLoss, caption: "Assuming average mart price" },
      buyer:  { label: "Buyer's cost", value: a.buyerGoodCost, caption: "Even on a good day at the mart" }
    };
  }
  return {
    seller: { label: "Seller's loss", value: a.sellerAvgLoss, caption: "Assuming average mart price" },
    buyer:  { label: "Buyer's cost", value: a.buyerAvgCost,  caption: "On a bad day at the mart" }
  };
}

function fillTrend(raw) {
  const p = raw.slice();
  const knownCount = p.filter(x => x != null && !isNaN(x)).length;
  if (knownCount < 2) return null;
  if (p[3] == null || isNaN(p[3])) return null;
  for (let pass = 0; pass < 5; pass++) {
    if (p[2]==null && p[1]!=null && p[3]!=null) p[2]=(p[1]+p[3])/2;
    if (p[1]==null && p[0]!=null && p[2]!=null) p[1]=(p[0]+p[2])/2;
    if (p[0]==null && p[1]!=null) p[0]=p[1];
    if (p[1]==null && p[2]!=null && p[3]!=null) p[1]=p[2]-(p[3]-p[2]);
    if (p[2]==null && p[0]!=null && p[3]!=null) { p[2]=p[0]+(p[3]-p[0])*2/3; if(p[1]==null) p[1]=p[0]+(p[3]-p[0])*1/3; }
    if (p.every(x => x != null)) break;
  }
  if (!p.every(x => x != null)) return null;
  let firstKnownIdx = 3;
  for (let i=0;i<4;i++) if(raw[i]!=null && !isNaN(raw[i])){firstKnownIdx=i;break;}
  return { filled: p, firstKnownIdx };
}

function trendLabel(filled) {
  const range = Math.max(...filled) - Math.min(...filled);
  if (range < 0.05) return { label: 'Steady', cls: 'steady' };
  const segs = [filled[1]-filled[0], filled[2]-filled[1], filled[3]-filled[2]];
  const realSegs = segs.filter(s => Math.abs(s) > 0.005);
  if (realSegs.length === 0) return { label: 'Steady', cls: 'steady' };
  if (realSegs.every(s => s > 0)) return { label: 'Trending up', cls: 'up' };
  if (realSegs.every(s => s < 0)) return { label: 'Trending down', cls: 'down' };
  return { label: 'Volatile', cls: 'choppy' };
}

function getBandTrendPrices(breedBands, weight) {
  const bands = Object.keys(breedBands || {});
  if (!bands.length) return null;
  const parsed = bands.map(b => { const [lo,hi]=b.split('-').map(Number); return {band:b,lo,hi}; }).sort((a,b)=>a.lo-b.lo);
  let inside = parsed.find(p => weight >= p.lo && weight < p.hi);
  if (!inside) inside = weight < parsed[0].lo ? parsed[0] : parsed[parsed.length-1];
  const prices = breedBands[inside.band];
  if (!Array.isArray(prices) || prices.length < 4) return null;
  return { bandName: inside.band, prices: prices.slice(-4) };
}

function getFlag(data, sex, category, breed, bandName) {
  if (!data.flags) return '';
  const bands = bandName.includes('&') ? bandName.split(' & ') : [bandName];
  for (const b of bands) {
    const f = data.flags[sex + '/' + category + '/' + breed + '/' + b.trim()];
    if (f === 'DERIVED') return ' (est.)';
    if (f === 'FLAGGED') return ' \u26A0';
  }
  return '';
}

function saturdayWeekDates(weeks) {
  return weeks.map(w => {
    const d = new Date(w);
    const daysBack = (d.getDay() + 1) % 7;
    d.setDate(d.getDate() - daysBack);
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return d.getDate() + ' ' + months[d.getMonth()];
  });
}

function buildTrend(breedBands, weight, weeks) {
  const bd = getBandTrendPrices(breedBands, weight);
  if (!bd) return null;
  const fill = fillTrend(bd.prices);
  if (!fill) return null;
  const lbl = trendLabel(fill.filled);
  fill.filled = fill.filled.map(v => Math.round(v * 20) / 20);
  return { filled: fill.filled, firstKnownIdx: fill.firstKnownIdx, label: lbl.label, cls: lbl.cls, bandName: bd.bandName, dates: saturdayWeekDates(weeks.slice(-4)) };
}

// ---- Route handlers ----

function handleBreeds(data) {
  const cats = {};
  for (const [sex, sd] of Object.entries(data.categories)) {
    cats[sex] = { label: sd.label, subcategories: {} };
    for (const [sub, subd] of Object.entries(sd.subcategories)) {
      cats[sex].subcategories[sub] = { label: subd.label, breeds: Object.keys(subd.breeds).sort() };
    }
  }
  return { week_ending: data.week_ending, categories: cats, breed_names: data.breed_names || {} };
}

const r5 = v => Math.round(v * 20) / 20;
function handlePrice(data, body) {
  const { sex, category, breed, weight } = body || {};
  if (!sex || !category || !breed || !weight) return { error: 'missing fields' };
  const breedBands = data.categories?.[sex]?.subcategories?.[category]?.breeds?.[breed];
  if (!breedBands) return { error: 'breed not found' };
  const lookup = findBandPrice(breedBands, parseFloat(weight));
  if (!lookup || lookup.mean == null) return { error: 'no data for this weight' };
  lookup.mean = r5(lookup.mean);
  const flag = getFlag(data, sex, category, breed, lookup.bandName);
  const trend = buildTrend(breedBands, parseFloat(weight), data.weeks);
  const interim = factoryInterim(sex, category, lookup.mean, data.week_ending);
  return { mean: lookup.mean, bandName: lookup.bandName, blended: lookup.blended, flag, trend, interim, weekEnding: data.week_ending };
}

function handleCompare(data, body) {
  const { sex, category, breed, weight, ffBid, headCount, name, side } = body || {};
  if (!sex || !category || !breed || !weight || !ffBid || !headCount || !side) return { error: 'missing fields' };
  const w = parseFloat(weight), bid = parseFloat(ffBid), n = parseInt(headCount);
  const breedBands = data.categories?.[sex]?.subcategories?.[category]?.breeds?.[breed];
  if (!breedBands) return { error: 'breed not found' };
  const lookup = findBandPrice(breedBands, w);
  if (!lookup || lookup.mean == null) return { error: 'No mart data available for this breed x weight.' };
  const mean = r5(lookup.mean);
  const interim = factoryInterim(sex, category, mean, data.week_ending);
  const basisMean = interim ? interim.estimate : mean;
  const a = analyzeTrade(w, basisMean, bid, n);
  const tally = pickTallyScenarios(a);
  const flag = getFlag(data, sex, category, breed, lookup.bandName);
  const trend = buildTrend(breedBands, w, data.weeks);
  const subLabel = data.categories[sex]?.subcategories[category]?.label || category;
  // Scenario tag (mirrors client logic)
  let scenarioUsed = 'default_avg_avg';
  if (a.sellerAvgLoss <= 0) scenarioUsed = 'edge1_redmond_bottom_good';
  else if (((a.sellerAvgLoss + a.buyerAvgCost) / n) > 200) scenarioUsed = 'edge2_extreme_avg_good';
  const tallyTotal = tally.seller.value + Math.max(0, tally.buyer.value);
  return { weekEnding: data.week_ending, side, mean, flag, subLabel, bandName: lookup.bandName, interim, basis: interim ? 'estimate' : 'settled',
           analysis: a, tally, tallyTotal, tallyPerHead: tallyTotal / n,
           scenarioUsed, trend, breedNames: data.breed_names || {} };
}

// ---- Lambda handler ----
const CORS = {
  'Access-Control-Allow-Origin': 'https://calc.farmfayre.com',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
  'X-Robots-Tag': 'noindex, nofollow',
};
function respond(status, body, cache) {
  return { statusCode: status, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': cache || (status===200 ? 'public, max-age=300, s-maxage=300' : 'no-store'), ...CORS }, body: JSON.stringify(body) };
}

exports.handler = async (event) => {
  if (event.httpMethod === 'OPTIONS') return { statusCode: 204, headers: CORS };
  try {
    const data = loadData();
    const p = (event.path || '').replace(/.*\/api\//, '');
    if (p === 'breeds' && event.httpMethod === 'GET') return respond(200, handleBreeds(data));
    if (event.httpMethod !== 'POST') return respond(405, { error: 'method not allowed' });
    let body; try { body = JSON.parse(event.body || '{}'); } catch(e) { return respond(400, { error: 'invalid JSON' }); }
    if (p === 'price') { const r = handlePrice(data, body); return respond(r.error ? 400 : 200, r); }
    if (p === 'compare') { const r = handleCompare(data, body); return respond(r.error ? 400 : 200, r); }
    return respond(404, { error: 'not found' });
  } catch(e) { return respond(503, { error: 'temporarily unavailable' }); }
};
