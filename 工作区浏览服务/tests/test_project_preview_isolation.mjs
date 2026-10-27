// Exercise the real file response policy in a browser; all requests are intercepted.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('..', import.meta.url));
const python = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium } = require('playwright');
const fixture = JSON.parse(execFileSync(python, ['-B', '-c', `
import json, tempfile
from pathlib import Path
from unittest.mock import patch
from starlette.requests import Request
from backend.services.projects import ProjectStore
original = ProjectStore.__init__
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    def isolated(self, projects, *, cache_directory=None, version=''):
        original(self, projects, cache_directory=root / 'cache' if cache_directory else None, version=version)
    with patch.object(ProjectStore, '__init__', isolated):
        from backend import main
    project = root / 'preview'
    project.mkdir()
    html = '''<!doctype html><body><p>Interactive preview</p><script>
    document.body.dataset.script = 'running';
    try { localStorage.getItem('workbench-marker'); document.body.dataset.storage = 'accessible'; }
    catch { document.body.dataset.storage = 'isolated'; }
    fetch('/mock-management', {method: 'POST'}).then(() => {
      document.body.dataset.connection = 'allowed';
    }).catch(() => { document.body.dataset.connection = 'blocked'; });
    </script></body>'''
    (project / 'preview.html').write_text(html, 'utf-8')
    with patch.object(main, 'store', ProjectStore(root)):
        response = main.project_file('preview', 'preview.html', Request({'type': 'http', 'headers': []}))
    print(json.dumps({'headers': dict(response.headers), 'body': html}))
`], { cwd: root, encoding: 'utf8' }));

const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
  const context = await browser.newContext();
  const requests = [];
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    requests.push(url.pathname);
    if (url.origin !== 'http://preview.invalid') return route.abort();
    if (url.pathname === '/workbench') return route.fulfill({ contentType: 'text/html', body: '<p>Isolated fixture</p>' });
    if (url.pathname === '/preview.html') return route.fulfill(fixture);
    return route.fulfill({ status: 403, body: 'unexpected fixture request' });
  });
  const page = await context.newPage();
  await page.goto('http://preview.invalid/workbench');
  await page.evaluate(() => localStorage.setItem('workbench-marker', 'fixture'));
  await page.goto('http://preview.invalid/preview.html');
  await page.waitForFunction(() => document.body.dataset.connection === 'blocked');
  assert.equal(await page.locator('body').getAttribute('data-script'), 'running');
  assert.equal(await page.locator('body').getAttribute('data-storage'), 'isolated');
  assert.ok(!requests.includes('/mock-management'), 'preview must not send management requests');
  await context.close();
  console.log('PASS: real project file policy preserves scripts, isolates origin, and blocks API connections');
} finally { await browser.close(); }
