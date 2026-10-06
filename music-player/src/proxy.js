// Range-fähiger Stream-Proxy. Safari auf iOS spielt Audio nur mit Range-Requests (206) sauber ab.
import { Readable } from 'node:stream';

const PASS = ['content-type', 'content-length', 'content-range', 'accept-ranges', 'last-modified', 'etag'];

/**
 * @returns {Promise<number>} HTTP-Status der Quelle (z. B. 403 → URL abgelaufen)
 */
export async function proxy(req, res, url, { headers = {}, contentType, cache = 'no-store', retryOn } = {}) {
  const ac = new AbortController();
  res.on('close', () => ac.abort());

  const h = { ...headers };
  if (req.headers.range) h.Range = req.headers.range;
  if (req.headers['if-range']) h['If-Range'] = req.headers['if-range'];

  const upstream = await fetch(url, {
    method: req.method === 'HEAD' ? 'HEAD' : 'GET',
    headers: h,
    signal: ac.signal,
    redirect: 'follow',
  });

  if (retryOn?.includes(upstream.status)) {
    await upstream.body?.cancel();
    return upstream.status;
  }

  res.status(upstream.status);
  for (const k of PASS) {
    const v = upstream.headers.get(k);
    if (v) res.setHeader(k, v);
  }
  const type = upstream.headers.get('content-type') ?? '';
  if (contentType && (!type || /octet-stream|video\//.test(type))) res.setHeader('content-type', contentType);
  res.setHeader('cache-control', cache);

  if (!upstream.body || req.method === 'HEAD') {
    res.end();
    return upstream.status;
  }
  Readable.fromWeb(upstream.body)
    .on('error', () => res.destroy())
    .pipe(res);
  return upstream.status;
}
