import { createHash } from 'node:crypto';
import { copyFile, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { dirname, resolve, relative, sep } from 'node:path';

const ROOT = resolve(import.meta.dirname, '..');
const DIST = resolve(ROOT, 'dist');
const sourceFiles = ['src/index.html', 'src/app.js', 'src/app.css', 'src/worker.mjs'];
const engineFiles = ['data_models.py', 'normalize.py', 'readers.py', 'consolidated.py',
  'reconcile.py', 'decisions.py', 'export_results.py'];
const runtimeFiles = ['pyodide.mjs', 'pyodide.asm.mjs', 'pyodide.asm.wasm',
  'python_stdlib.zip', 'pyodide-lock.json'];
const wheelFiles = ['et_xmlfile-2.0.0-py3-none-any.whl',
  'defusedxml-0.7.1-py2.py3-none-any.whl',
  'openpyxl-3.1.5-py2.py3-none-any.whl'];

function hash(bytes) { return createHash('sha256').update(bytes).digest('hex'); }
async function verifyManifest(path, folder) {
  const manifest = JSON.parse(await readFile(resolve(ROOT, path), 'utf8'));
  for (const [name, expected] of Object.entries(manifest)) {
    const actual = hash(await readFile(resolve(ROOT, folder, name)));
    if (actual !== expected) throw new Error(`Hash distinto: ${name}`);
  }
  return manifest;
}
async function copy(from, to, hashes = null) {
  const bytes = await readFile(resolve(ROOT, from));
  const target = resolve(DIST, to);
  await mkdir(dirname(target), { recursive: true });
  await copyFile(resolve(ROOT, from), target);
  if (hashes) hashes[`./${to.replaceAll('\\', '/')}`] = hash(bytes);
}

if (!DIST.startsWith(ROOT + sep)) throw new Error('Destino de build fuera del proyecto');
await verifyManifest('engine/engine-manifest.json', 'engine');
await verifyManifest('vendor_wheels/wheels-manifest.json', 'vendor_wheels');
const wheelDirectory = await readdir(resolve(ROOT, 'vendor_wheels'));
if (wheelDirectory.filter(name => name.endsWith('.whl')).sort().join('|') !== [...wheelFiles].sort().join('|')) {
  throw new Error('Ruedas Python inesperadas');
}
await rm(DIST, { recursive: true, force: true });
await mkdir(DIST, { recursive: true });
for (const name of sourceFiles) await copy(name, name.replace(/^src\//, ''));
const hashes = {};
for (const name of engineFiles) await copy(`engine/${name}`, `engine/${name}`, hashes);
await copy('src/bridge.py', 'engine/bridge.py', hashes);
for (const name of wheelFiles) await copy(`vendor_wheels/${name}`, `vendor/wheels/${name}`, hashes);
for (const name of runtimeFiles) {
  await copy(`node_modules/pyodide/${name}`, `vendor/pyodide/${name}`);
}
await writeFile(resolve(DIST, 'asset-manifest.json'), JSON.stringify(hashes, null, 2) + '\n');
const all = await readdir(DIST, { recursive: true });
if (all.some(name => /\.(xlsx|xlsm|xls|csv|tsv)$/i.test(name))) throw new Error('Datos en el paquete');
const sizes = await Promise.all(runtimeFiles.map(async name => ({
  name, bytes: (await readFile(resolve(DIST, 'vendor/pyodide', name))).byteLength,
})));
console.log(`Paquete estático: ${all.filter(name => name.includes('.')).length} rutas; mayor recurso ${Math.max(...sizes.map(item => item.bytes))} bytes`);
