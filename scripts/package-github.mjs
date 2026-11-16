import { copyFile, mkdir, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises';
import { dirname, resolve, sep } from 'node:path';
import { createHash } from 'node:crypto';

const root = resolve(import.meta.dirname, '..');
const out = resolve(root, 'github_ready');
if (!out.startsWith(root + sep)) throw new Error('Salida fuera del proyecto');
const fixed = ['.gitignore', 'README.md', 'package.json', 'package-lock.json', 'vercel.json',
  'scripts/build.mjs', 'scripts/package-github.mjs', 'scripts/serve-local.mjs', 'src/index.html', 'src/app.js', 'src/app.css', 'src/worker.mjs',
  'src/bridge.py', 'engine/engine-manifest.json', 'vendor_wheels/wheels-manifest.json'];
const engine = ['data_models.py', 'normalize.py', 'readers.py', 'consolidated.py',
  'reconcile.py', 'decisions.py', 'export_results.py'];
const wheels = ['et_xmlfile-2.0.0-py3-none-any.whl',
  'defusedxml-0.7.1-py2.py3-none-any.whl',
  'openpyxl-3.1.5-py2.py3-none-any.whl'];
const files = [...fixed, ...engine.map(name => `engine/${name}`),
  ...wheels.map(name => `vendor_wheels/${name}`)];
const manifest = {};
await rm(out, { recursive: true, force: true });
for (const name of files) {
  const source = resolve(root, name);
  const destination = resolve(out, name);
  let bytes = await readFile(source);
  if (name === 'package.json') {
    const descriptor = JSON.parse(bytes.toString('utf8'));
    delete descriptor.scripts.test;
    bytes = Buffer.from(JSON.stringify(descriptor, null, 2) + '\n');
  }
  await mkdir(dirname(destination), { recursive: true });
  if (name === 'package.json') await writeFile(destination, bytes);
  else await copyFile(source, destination);
  manifest[name] = createHash('sha256').update(bytes).digest('hex');
}
await writeFile(resolve(out, 'SOURCE-MANIFEST.json'), JSON.stringify(manifest, null, 2) + '\n');
const entries = await readdir(out, { recursive: true });
if (entries.some(path => /\.(xlsx|xlsm|xls|csv|tsv|env)$/i.test(path))) {
  throw new Error('Se encontró un archivo de datos o entorno en el paquete GitHub');
}
const sizes = await Promise.all(files.map(async name => ({ name,
  size: (await stat(resolve(out, name))).size })));
const largest = sizes.sort((a, b) => b.size - a.size)[0];
console.log(`GitHub: ${files.length + 1} archivos; mayor ${largest.name} (${largest.size} bytes)`);
