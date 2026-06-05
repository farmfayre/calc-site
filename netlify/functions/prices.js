// Farm Fayre price data function.
// Serves the weekly public dataset from a bundled, non-served file so the data
// is not downloadable as a named static file. Deterrence against casual copying
// and competitor monitoring -- not secrecy (the calc must read it client-side).
//
// Reliability: response carries a 5-minute CDN cache, so most requests are served
// from Netlify's edge without invoking this function at all. The data file is
// bundled via [functions] included_files in netlify.toml.

const fs = require('fs');
const path = require('path');

let CACHE = null; // per-container memory cache; refreshed on each deploy (new container)

const CANDIDATES = [
  path.resolve(process.cwd(), '_data/market_data.json'),
  path.resolve(__dirname, '_data/market_data.json'),
  path.resolve(__dirname, '../../_data/market_data.json'),
  '/var/task/_data/market_data.json',
];

function loadData() {
  if (CACHE) return CACHE;
  let lastErr = null;
  for (const p of CANDIDATES) {
    try {
      CACHE = JSON.parse(fs.readFileSync(p, 'utf8'));
      return CACHE;
    } catch (e) { lastErr = e; }
  }
  throw lastErr || new Error('data file not found');
}

exports.handler = async (event) => {
  if (event.httpMethod && event.httpMethod !== 'GET') {
    return { statusCode: 405, body: 'Method Not Allowed' };
  }
  try {
    const data = loadData();
    return {
      statusCode: 200,
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
        'Cache-Control': 'public, max-age=300, s-maxage=300',
        'Access-Control-Allow-Origin': 'https://calc.farmfayre.com',
        'X-Robots-Tag': 'noindex, nofollow',
      },
      body: JSON.stringify(data),
    };
  } catch (e) {
    // Soft failure -> front-end retries, then shows a graceful message.
    return {
      statusCode: 503,
      headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
      body: JSON.stringify({ error: 'temporarily unavailable' }),
    };
  }
};
