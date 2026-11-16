import { loadPyodide } from './vendor/pyodide/pyodide.mjs';

const ENGINE = ['data_models.py', 'normalize.py', 'readers.py', 'consolidated.py',
  'reconcile.py', 'decisions.py', 'export_results.py'];
const WHEELS = ['et_xmlfile-2.0.0-py3-none-any.whl',
  'defusedxml-0.7.1-py2.py3-none-any.whl',
  'openpyxl-3.1.5-py2.py3-none-any.whl'];
let pyodide;
let currentPage = 1;

function url(path) { return new URL(path, import.meta.url); }

async function verifiedBytes(path, hashes) {
  const response = await fetch(url(path), { credentials: 'omit', cache: 'no-store' });
  if (!response.ok) throw new Error('No se pudo cargar un componente verificado');
  const bytes = new Uint8Array(await response.arrayBuffer());
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  const hex = [...digest].map(value => value.toString(16).padStart(2, '0')).join('');
  if (hex !== hashes[path]) throw new Error('Un componente no coincide con el paquete aprobado');
  return bytes;
}

async function initialize() {
  const response = await fetch(url('./asset-manifest.json'), { credentials: 'omit', cache: 'no-store' });
  if (!response.ok) throw new Error('No se pudo validar el paquete');
  const hashes = await response.json();
  pyodide = await loadPyodide({ indexURL: url('./vendor/pyodide/').href });
  const site = pyodide.runPython('import site; site.getsitepackages()[0]');
  for (const wheel of WHEELS) {
    const bytes = await verifiedBytes(`./vendor/wheels/${wheel}`, hashes);
    pyodide.unpackArchive(bytes, 'wheel', { extractDir: site });
  }
  pyodide.FS.mkdir('/engine');
  for (const name of ENGINE) {
    pyodide.FS.writeFile(`/engine/${name}`, await verifiedBytes(`./engine/${name}`, hashes));
  }
  pyodide.FS.writeFile('/engine/bridge.py', await verifiedBytes('./engine/bridge.py', hashes));
  pyodide.runPython("import sys; sys.path.insert(0, '/engine'); from bridge import *");
  self.postMessage({ type: 'ready' });
}

function requestJson(code, payload) {
  pyodide.globals.set('_request_json', JSON.stringify(payload));
  const answer = pyodide.runPython(code);
  return JSON.parse(answer);
}

function errorMessage(error) {
  const text = String(error?.message || '');
  if (text.includes('DataError: ')) {
    const detail = text.split('DataError: ').at(-1).split('\n')[0];
    return detail.slice(0, 240);
  }
  return 'No se pudo procesar el libro. Revisa su formato e inténtalo con una copia.';
}

async function handle(message) {
  if (!pyodide) throw new Error('El motor aún no está listo');
  if (message.type === 'analyze') {
    const buffer = message.buffer;
    if (!(buffer instanceof ArrayBuffer) || !buffer.byteLength || buffer.byteLength > 8_000_000) {
      throw new Error('Selecciona un XLSX válido de hasta 8 MB');
    }
    pyodide.FS.writeFile('/input.xlsx', new Uint8Array(buffer));
    try {
      const data = JSON.parse(pyodide.runPython('analyze_file()'));
      currentPage = 1;
      self.postMessage({ id: message.id, type: 'view', data });
    } finally {
      pyodide.FS.unlink('/input.xlsx');
    }
    return;
  }
  if (message.type === 'page') {
    const page = Number(message.page);
    if (!Number.isInteger(page)) throw new Error('Página inválida');
    const data = requestJson('page_json(json.loads(_request_json)["page"])', { page });
    currentPage = page;
    self.postMessage({ id: message.id, type: 'view', data });
    return;
  }
  if (message.type === 'assign') {
    const data = requestJson('add_decision(**json.loads(_request_json))', {
      scan_row: message.scan_row, china_sheet: message.china_sheet,
      china_row: message.china_row, quantity: message.quantity,
      reason: message.reason, page: currentPage,
    });
    self.postMessage({ id: message.id, type: 'view', data });
    return;
  }
  if (message.type === 'remove') {
    const data = requestJson('remove_decision(**json.loads(_request_json))', {
      scan_row: message.scan_row, china_sheet: message.china_sheet,
      china_row: message.china_row, page: currentPage,
    });
    self.postMessage({ id: message.id, type: 'view', data });
    return;
  }
  if (message.type === 'export') {
    const value = pyodide.runPython('result_bytes()');
    const bytes = value.toJs();
    value.destroy();
    const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    self.postMessage({ id: message.id, type: 'export', buffer }, [buffer]);
    return;
  }
  throw new Error('Acción desconocida');
}

let queue = Promise.resolve();
self.onmessage = event => {
  const message = event.data;
  queue = queue.then(() => handle(message)).catch(error => {
    self.postMessage({ id: message.id, type: 'error', message: errorMessage(error) });
  });
};
initialize().catch(() => self.postMessage({ type: 'fatal', message: 'No se pudo iniciar el motor local.' }));
