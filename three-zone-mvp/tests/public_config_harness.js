'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const configSrc = fs.readFileSync(path.join(__dirname, '..', '..', 'docs', 'config.js'), 'utf8');
const siteSrc = fs.readFileSync(path.join(__dirname, '..', '..', 'docs', 'site.js'), 'utf8');

function load(src, windowObj, extras) {
  const sandbox = {
    window: windowObj,
    module: { exports: {} },
    exports: {},
    console,
    fetch: extras && extras.fetch,
    setTimeout,
    clearTimeout,
  };
  if (windowObj === undefined) delete sandbox.window;
  vm.runInNewContext(src + '\nthis.exported = (typeof module !== "undefined" && module.exports) ? module.exports : null;', sandbox, { filename: 'harness.js' });
  return sandbox.exported;
}

async function main() {
  const production = 'https://three-zone-sports.onrender.com';
  const results = { origin: {}, memberAppUrl: {}, fetch: {}, site: {} };

  results.origin.noWindow = load(configSrc, undefined)._origin();
  results.origin.localhost = load(configSrc, { location: { hostname: 'localhost' } })._origin();
  results.origin.loopback = load(configSrc, { location: { hostname: '127.0.0.1' } })._origin();
  results.origin.pages = load(configSrc, { location: { hostname: '3zonesports.com' } })._origin();
  results.origin.www = load(configSrc, { location: { hostname: 'www.3zonesports.com' } })._origin();
  results.origin.override = load(configSrc, {
    location: { hostname: '3zonesports.com' },
    __THREE_ZONE_BACKEND_URL__: 'https://example.test///',
  })._origin();

  const cfg = load(configSrc, { location: { hostname: '3zonesports.com' } });
  results.memberAppUrl.empty = await cfg.memberAppUrl();
  results.memberAppUrl.root = await cfg.memberAppUrl('/');
  results.memberAppUrl.query = await cfg.memberAppUrl('/?event=evt_x');
  results.memberAppUrl.encoded = await cfg.memberAppUrl('/?event=' + encodeURIComponent('evt_"<>'));

  const okFetch = load(configSrc, { location: { hostname: '3zonesports.com' } }, {
    fetch: async () => ({
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      json: async () => ({ events: [{ title: 'ok' }] }),
    }),
  });
  results.fetch.ok = await okFetch.fetch('/api/public/live');

  const failFetch = load(configSrc, { location: { hostname: '3zonesports.com' } }, {
    fetch: async () => ({
      ok: false,
      status: 503,
      headers: { get: () => 'text/html' },
      json: async () => ({}),
    }),
  });
  try {
    await failFetch.fetch('/api/public/live');
    results.fetch.fail = null;
  } catch (err) {
    results.fetch.fail = { message: err.message, code: err.code, status: err.status };
  }

  const htmlFetch = load(configSrc, { location: { hostname: '3zonesports.com' } }, {
    fetch: async () => ({
      ok: true,
      status: 200,
      headers: { get: () => 'text/html' },
      json: async () => ({}),
    }),
  });
  try {
    await htmlFetch.fetch('/api/public/live');
    results.fetch.html = null;
  } catch (err) {
    results.fetch.html = { message: err.message, code: err.code };
  }

  const badJson = load(configSrc, { location: { hostname: '3zonesports.com' } }, {
    fetch: async () => ({
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      json: async () => { throw new Error('bad json'); },
    }),
  });
  try {
    await badJson.fetch('/api/public/live');
    results.fetch.badJson = null;
  } catch (err) {
    results.fetch.badJson = { message: err.message, code: err.code };
  }

  const healthOk = load(configSrc, { location: { hostname: '3zonesports.com' } }, {
    fetch: async () => ({
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      json: async () => ({ status: 'ok' }),
    }),
  });
  results.fetch.healthOk = await healthOk.checkHealth();

  const healthDown = load(configSrc, { location: { hostname: '3zonesports.com' } }, {
    fetch: async () => { throw new Error('network'); },
  });
  results.fetch.healthDown = await healthDown.checkHealth();

  const site = load(siteSrc, undefined);
  results.site.uniqueEmpty = site.uniqueBy([], 'team');
  results.site.uniqueDupes = site.uniqueBy(
    [{ team: 'A' }, { team: 'A' }, { team: '  ' }, { team: 'B' }, { team: '' }, {}],
    'team',
  ).map((row) => row.team);
  results.site.timeEmpty = site.formatWhen(0);
  results.site.timeBad = site.formatWhen('nope');
  results.site.timeOk = site.formatWhen(1700000000);
  results.site.gameHref = site.gameHref('evt_"<>');
  results.site.archiveHref = site.archiveHref('arc 1');

  process.stdout.write(JSON.stringify(results));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
