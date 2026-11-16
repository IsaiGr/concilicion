"use strict";

const $ = id => document.getElementById(id);
const show = (id, visible) => { $(id).hidden = !visible; };
const node = (tag, className, value) => {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (value !== undefined) element.textContent = String(value);
  return element;
};
function message(value, bad = false) {
  const box = $('message');
  box.textContent = value;
  box.className = bad ? 'message error' : 'message';
  box.hidden = !value;
}

class LocalEngine {
  constructor() {
    this.alive = true;
    this.nextId = 1;
    this.pending = new Map();
    this.worker = new Worker('./worker.mjs', { type: 'module' });
    this.ready = new Promise((resolve, reject) => {
      this.resolveReady = resolve;
      this.rejectReady = reject;
    });
    this.worker.onmessage = event => {
      const response = event.data;
      if (!this.alive) return;
      if (response.type === 'ready') { this.resolveReady(); return; }
      if (response.type === 'fatal') {
        this.rejectReady(new Error(response.message));
        this.failAll(new Error(response.message));
        return;
      }
      const pending = this.pending.get(response.id);
      if (!pending) return;
      this.pending.delete(response.id);
      if (response.type === 'error') pending.reject(new Error(response.message));
      else pending.resolve(response);
    };
    this.worker.onerror = () => {
      if (!this.alive) return;
      const error = new Error('El motor local dejó de responder. Cierra la revisión y vuelve a intentarlo.');
      this.rejectReady(error);
      this.failAll(error);
    };
  }
  failAll(error) {
    for (const pending of this.pending.values()) pending.reject(error);
    this.pending.clear();
  }
  async request(type, fields = {}, transfer = []) {
    await this.ready;
    if (!this.alive) throw new Error('Revisión cerrada');
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      try { this.worker.postMessage({ id, type, ...fields }, transfer); }
      catch (error) { this.pending.delete(id); reject(error); }
    });
  }
  close() {
    if (!this.alive) return;
    this.alive = false;
    this.rejectReady(new Error('Revisión cerrada'));
    this.failAll(new Error('Revisión cerrada'));
    this.worker.terminate();
  }
}

let engine;
let generation = 0;
let currentPage = 1;
let currentPages = 1;
let active = false;

function startEngine() {
  const local = new LocalEngine();
  engine = local;
  $('analyze-button').disabled = true;
  local.ready.then(() => {
    if (engine === local) { $('analyze-button').disabled = false; message('Motor local listo. Selecciona un XLSX.'); }
  }).catch(error => { if (engine === local) message(error.message, true); });
}

function reset() {
  generation++;
  engine?.close();
  active = false;
  currentPage = 1;
  currentPages = 1;
  $('file-input').value = '';
  show('upload-section', true);
  show('result-section', false);
  $('metrics').replaceChildren();
  $('warnings').replaceChildren();
  $('attention').replaceChildren();
  $('items').replaceChildren();
  $('decisions').replaceChildren();
  startEngine();
}

function render(data) {
  currentPage = data.page;
  currentPages = data.pages;
  const metrics = $('metrics');
  metrics.replaceChildren();
  for (const [count, label] of [[data.scans, 'Filas analizables'],
    [data.candidate_count, 'Con candidatos'], [data.attention_count, 'En Atención']]) {
    const card = node('div', 'metric');
    card.append(node('strong', '', count), node('span', '', label));
    metrics.append(card);
  }
  const warnings = $('warnings');
  warnings.replaceChildren();
  show('warnings', data.warnings.length > 0);
  if (data.warnings.length) {
    warnings.append(node('h3', '', 'Avisos'));
    for (const warning of data.warnings) warnings.append(node('div', 'warning', warning));
  }
  const attention = $('attention');
  attention.replaceChildren();
  if (!data.attention.length) attention.append(node('p', '', 'Sin filas en Atención.'));
  for (const row of data.attention) {
    attention.append(node('div', 'attention-row', `${row.sheet}, fila ${row.row}: ${row.reason}`));
  }
  if (data.attention_count > data.attention.length) {
    attention.append(node('p', '', `Se muestran las primeras ${data.attention.length} filas de Atención.`));
  }
  const items = $('items');
  items.replaceChildren();
  if (!data.items.length) items.append(node('p', '', 'No hay partidas analizables en esta página.'));
  for (const item of data.items) {
    const box = node('article', 'item');
    const head = node('div', 'item-head');
    head.append(node('div', 'item-title', `${item.part} · ${item.quantity} pieza(s) · fila ${item.row}`),
      node('span', 'state', item.state));
    box.append(head, node('p', '', `Batch: ${item.batch}`));
    if (item.reason) box.append(node('p', '', item.reason));
    for (const candidate of item.candidates) {
      const card = node('div', 'candidate');
      card.append(node('strong', '', `DN ${candidate.dn} · ${candidate.expected} esperadas`),
        node('p', '', `China: ${candidate.sheet}, fila ${candidate.row} · Tránsito: ${candidate.transit}`));
      if (candidate.issue) card.append(node('p', '', candidate.issue));
      const form = node('form', 'assign-form');
      const quantityLabel = node('label', '', 'Cantidad');
      const quantity = node('input');
      quantity.type = 'number'; quantity.min = '1';
      quantity.max = String(Math.min(item.quantity, candidate.expected)); quantity.required = true;
      quantityLabel.append(quantity);
      const reasonLabel = node('label', '', 'Motivo de la decisión');
      const reason = node('input');
      reason.type = 'text'; reason.maxLength = 500; reason.required = true;
      reasonLabel.append(reason);
      const button = node('button', 'primary', 'Confirmar'); button.type = 'submit';
      form.append(quantityLabel, reasonLabel, button);
      form.addEventListener('submit', async event => {
        event.preventDefault(); button.disabled = true;
        const token = generation;
        try {
          const response = await engine.request('assign', {
            scan_row: item.row, china_sheet: candidate.sheet, china_row: candidate.row,
            quantity: Number(quantity.value), reason: reason.value,
          });
          if (token !== generation) return;
          render(response.data);
          message('Reparto confirmado. Puedes retirarlo antes de cerrar.');
        } catch (error) { if (token === generation) message(error.message, true); }
        finally { button.disabled = false; }
      });
      card.append(form); box.append(card);
    }
    items.append(box);
  }
  const decisions = $('decisions');
  decisions.replaceChildren();
  if (!data.decisions.length) decisions.append(node('p', '', 'Aún no hay repartos confirmados.'));
  for (const decision of data.decisions) {
    const line = node('div', 'decision-row');
    const remove = node('button', 'quiet', 'Retirar'); remove.type = 'button';
    remove.addEventListener('click', async () => {
      remove.disabled = true;
      const token = generation;
      try {
        const response = await engine.request('remove', {
          scan_row: decision.scan_row, china_sheet: decision.china_sheet,
          china_row: decision.china_row,
        });
        if (token !== generation) return;
        render(response.data);
        message('Reparto retirado.');
      } catch (error) { if (token === generation) message(error.message, true); }
      finally { remove.disabled = false; }
    });
    line.append(node('span', '', `Escaneo ${decision.scan_row} → ${decision.dn}: ${decision.quantity} pieza(s). ${decision.reason}`), remove);
    decisions.append(line);
  }
  $('page-label').textContent = `Página ${currentPage} de ${currentPages}`;
  $('prev-page').disabled = currentPage <= 1;
  $('next-page').disabled = currentPage >= currentPages;
}

$('upload-form').addEventListener('submit', async event => {
  event.preventDefault();
  const file = $('file-input').files[0];
  if (!file || !file.name.toLowerCase().endsWith('.xlsx') || file.size > 8_000_000) {
    message('Selecciona un XLSX de hasta 8 MB.', true); return;
  }
  const token = generation;
  const button = $('analyze-button'); button.disabled = true;
  message('Analizando el libro en este navegador…');
  try {
    const buffer = await file.arrayBuffer();
    $('file-input').value = '';
    if (token !== generation) return;
    const response = await engine.request('analyze', { buffer }, [buffer]);
    if (token !== generation) return;
    active = true;
    show('upload-section', false);
    show('result-section', true);
    render(response.data);
    message('Revisión lista en este navegador. El libro no se envió al servidor.');
  } catch (error) { if (token === generation) message(error.message, true); }
  finally { button.disabled = false; }
});

$('export-button').addEventListener('click', async () => {
  if (!active) return;
  const token = generation;
  const button = $('export-button'); button.disabled = true;
  try {
    const response = await engine.request('export');
    if (token !== generation) return;
    const blob = new Blob([response.buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = 'Resultado-conciliacion.xlsx';
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    message('Resultado descargado. La revisión sigue abierta hasta pulsar Cerrar.');
  } catch (error) { if (token === generation) message(error.message, true); }
  finally { button.disabled = false; }
});

$('close-button').addEventListener('click', () => { reset(); message('Revisión cerrada. La siguiente carga comienza en blanco.'); });
for (const [id, offset] of [['prev-page', -1], ['next-page', 1]]) {
  $(id).addEventListener('click', async () => {
    if (!active) return;
    const token = generation;
    try {
      const response = await engine.request('page', { page: currentPage + offset });
      if (token === generation) render(response.data);
    } catch (error) { if (token === generation) message(error.message, true); }
  });
}
startEngine();
