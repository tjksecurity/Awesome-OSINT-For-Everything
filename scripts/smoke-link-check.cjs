const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { createServer } = require('node:http');
const { mkdtemp, writeFile, rm } = require('node:fs/promises');
const { tmpdir } = require('node:os');
const path = require('node:path');

async function check(file) {
  const cli = require.resolve('markdown-link-check/markdown-link-check');
  const child = spawn(process.execPath, [cli, '-c', 'markdown-link-check-config.json', file], { stdio: ['ignore', 'pipe', 'pipe'] });
  let output = '';
  child.stdout.on('data', (data) => { output = (output + data).slice(-4000); });
  child.stderr.on('data', (data) => { output = (output + data).slice(-4000); });
  const timer = setTimeout(() => child.kill(), 15000);
  try { const [code] = await once(child, 'exit'); return { code, output }; }
  finally { clearTimeout(timer); }
}

async function main() {
  const temp = await mkdtemp(path.join(tmpdir(), 'osint-link-check-'));
  const server = createServer((request, response) => {
    response.writeHead(request.url === '/ok' ? 200 : 404);
    response.end();
  });
  try {
    server.listen(0, '127.0.0.1');
    await once(server, 'listening');
    const base = `http://127.0.0.1:${server.address().port}`;
    const valid = path.join(temp, 'valid.md');
    const broken = path.join(temp, 'broken.md');
    await writeFile(valid, `# Fixture\n\n[Valid](${base}/ok)\n`);
    await writeFile(broken, `# Fixture\n\n[Broken](${base}/missing)\n`);
    const good = await check(valid);
    const bad = await check(broken);
    assert.equal(good.code, 0, good.output);
    assert.equal(bad.code, 1, bad.output);
    console.log('Link checker accepts HTTP 200 and reports HTTP 404 with a failing exit code.');
  } finally {
    if (server.listening) await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    if (path.dirname(path.resolve(temp)) !== path.resolve(tmpdir()) || !path.basename(temp).startsWith('osint-link-check-')) {
      throw new Error('Refusing cleanup outside the newly created fixture directory');
    }
    await rm(temp, { recursive: true, force: true });
  }
}
main().catch((error) => { console.error(error.stack || error.message); process.exitCode = 1; });
