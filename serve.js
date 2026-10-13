'use strict';

const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');

const htmlPath = path.join(__dirname, '原型', 'V9 Agent-Floor.html');
const port = Number(process.env.PORT || 4173);

if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new RangeError('PORT must be an integer between 1 and 65535');
}

http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://127.0.0.1').pathname;

  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.writeHead(405, { Allow: 'GET, HEAD' });
    res.end();
    return;
  }

  if (pathname !== '/' && pathname !== '/index.html') {
    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('Not found');
    return;
  }

  res.writeHead(200, {
    'Content-Type': 'text/html; charset=utf-8',
    'Cache-Control': 'no-store',
  });

  if (req.method === 'HEAD') {
    res.end();
    return;
  }

  const stream = fs.createReadStream(htmlPath);
  stream.on('error', () => {
    if (!res.headersSent) res.writeHead(500);
    res.end('Unable to read the Agent Floor page');
  });
  stream.pipe(res);
}).listen(port, '127.0.0.1', () => {
  console.log(`Agent Floor is available at http://127.0.0.1:${port}/`);
});
