// Pruebas de hash-csp.mjs con el ejecutor de pruebas que trae Node (npm run test:scripts).

import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

import { analizarHtml, calcularHashes, hashCsp, leerAtributos } from './hash-csp.mjs';

const esperado = (texto) => `sha256-${createHash('sha256').update(texto, 'utf8').digest('base64')}`;

test('el hash tiene el formato que acepta el middleware de Django', () => {
  assert.match(hashCsp('console.log(1)'), /^sha256-[A-Za-z0-9+/]{43}=$/);
  assert.equal(hashCsp('ñandú'), esperado('ñandú'));
});

test('calcula el hash del contenido exacto de scripts y estilos en línea', () => {
  const script = '\n  const a = 1 > 0;\n';
  const estilo = 'body{margin:0}';
  const html = `<html><head><style>${estilo}</style></head><body><script type="module">${script}</script></body></html>`;

  const resultado = analizarHtml(html);

  assert.deepEqual(resultado.script, [esperado(script)]);
  assert.deepEqual(resultado.style, [esperado(estilo)]);
  assert.deepEqual(resultado.bloqueados, []);
});

test('ignora scripts externos, bloques de datos, bloques vacíos y comentarios', () => {
  const html = [
    '<script src="/_astro/pagina.js"></script>',
    '<script type="module" src="/_astro/isla.js"></script>',
    '<script type="application/json">{"a":1}</script>',
    '<script></script>',
    '<style></style>',
    '<!-- <script>alert(1)</script> -->',
  ].join('');

  const resultado = analizarHtml(html);

  assert.deepEqual(resultado.script, []);
  assert.deepEqual(resultado.style, []);
});

test('no se confunde con un ">" dentro de un atributo ni con mayúsculas', () => {
  const html = '<SCRIPT data-nota="a > b">let x = 1;</SCRIPT>';
  assert.deepEqual(analizarHtml(html).script, [esperado('let x = 1;')]);
});

test('un comentario dentro de un script es parte de su contenido', () => {
  const contenido = 'let a = 1; <!-- nota --> let b = 2;';
  assert.deepEqual(analizarHtml(`<script>${contenido}</script>`).script, [esperado(contenido)]);
});

test('no repite hashes de bloques idénticos', () => {
  const html = '<script>let x;</script><p>texto</p><script>let x;</script>';
  assert.equal(analizarHtml(html).script.length, 1);
});

test('avisa de atributos en línea que la CSP bloquearía', () => {
  const html = '<main><button onclick="salir()">Salir</button><p style="color:red">x</p></main>';
  const { bloqueados } = analizarHtml(html);
  assert.deepEqual(bloqueados, ['<button onclick="…">', '<p style="…">']);
});

test('no confunde texto ni otros atributos con atributos bloqueados', () => {
  const html =
    '<p data-style="a" class="online">onclick="x" style="y"</p><a title="on style=1">z</a>';
  assert.deepEqual(analizarHtml(html).bloqueados, []);
});

test('lee atributos con y sin comillas', () => {
  const atributos = leerAtributos(` type=module SRC="/a.js" async data-x='1'`);
  assert.equal(atributos.get('type'), 'module');
  assert.equal(atributos.get('src'), '/a.js');
  assert.equal(atributos.get('async'), '');
  assert.equal(atributos.get('data-x'), '1');
});

test('recorre todas las páginas del build y ordena los hashes', async () => {
  const carpeta = await mkdtemp(join(tmpdir(), 'notia-csp-'));
  try {
    await mkdir(join(carpeta, 'alumno'), { recursive: true });
    await writeFile(join(carpeta, 'index.html'), '<script>uno()</script><style>a{}</style>');
    await writeFile(join(carpeta, 'alumno', 'index.html'), '<script>dos()</script><style>a{}</style>');
    await writeFile(join(carpeta, 'alumno', 'datos.txt'), '<script>no_es_html()</script>');

    const resultado = await calcularHashes(carpeta);

    assert.equal(resultado.archivos, 2);
    assert.deepEqual(resultado.hashes.script, [esperado('uno()'), esperado('dos()')].sort());
    assert.deepEqual(resultado.hashes.style, [esperado('a{}')]);
    assert.deepEqual(resultado.bloqueados, []);
  } finally {
    await rm(carpeta, { recursive: true, force: true });
  }
});
