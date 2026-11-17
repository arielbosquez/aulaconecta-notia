// Calcula los hashes de CSP del build de Astro.
//
// La Content-Security-Policy de NotIA no admite 'unsafe-inline'. Astro, sin
// embargo, deja en el HTML algunos scripts y estilos en línea (por ejemplo, el
// que hidrata las islas de Svelte). Este script recorre el HTML de dist/,
// calcula el SHA-256 de cada bloque en línea y escribe csp-hashes.json, que el
// middleware de Django lee al arrancar para permitir exactamente esos bloques.
//
// Astro trae una opción propia (security.csp), pero en un sitio estático solo
// agrega una etiqueta <meta>. NotIA envía la política como cabecera HTTP desde
// Django (así cubre también la API y admite frame-ancestors), y esa cabecera
// necesita conocer los hashes: por eso se calculan aquí.
//
// Uso:  node scripts/hash-csp.mjs [carpeta-dist] [archivo-de-salida]
// Se ejecuta solo después de "astro build" (ver el script "build" de package.json).

import { createHash } from 'node:crypto';
import { readdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Atributos de una etiqueta, respetando los ">" que estén dentro de comillas.
const ATRIBUTOS = String.raw`(?:"[^"]*"|'[^']*'|[^>"'])*`;

// Recorre el documento de izquierda a derecha: salta los comentarios y captura
// cada <script> o <style> completo, con su contenido tal como lo verá el navegador.
const BLOQUES = new RegExp(
  String.raw`<!--[\s\S]*?-->|<(script|style)\b(${ATRIBUTOS})>([\s\S]*?)</\1\s*>`,
  'gi',
);

const ATRIBUTO = /([^\s"'=<>/]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g;

// Lo que CSP no puede permitir con un hash de bloque: manejadores de eventos
// en línea (onclick=...) y atributos style="...".
const ETIQUETA_ABIERTA = new RegExp(String.raw`<[a-zA-Z][\w:-]*\b(${ATRIBUTOS})>`, 'g');

// Bloques <script> que el navegador trata como datos y nunca ejecuta.
const TIPOS_DE_DATOS = new Set(['application/json', 'application/ld+json']);

/** Devuelve los atributos de una etiqueta como mapa nombre → valor (en minúsculas el nombre). */
export function leerAtributos(texto) {
  const atributos = new Map();
  for (const [, nombre, comillasDobles, comillasSimples, sinComillas] of texto.matchAll(ATRIBUTO)) {
    atributos.set(nombre.toLowerCase(), comillasDobles ?? comillasSimples ?? sinComillas ?? '');
  }
  return atributos;
}

/** Hash de un bloque en el formato que usa CSP: 'sha256-<base64>' (sin las comillas). */
export function hashCsp(contenido) {
  return `sha256-${createHash('sha256').update(contenido, 'utf8').digest('base64')}`;
}

/**
 * Analiza un documento HTML.
 * Devuelve los hashes de sus scripts y estilos en línea y la lista de
 * atributos en línea que la CSP bloquearía.
 */
export function analizarHtml(html) {
  const script = new Set();
  const style = new Set();
  const bloqueados = [];

  const sinBloques = html.replace(BLOQUES, (_completo, etiqueta, atributosTexto, contenido) => {
    if (!etiqueta) return ''; // comentario
    const tipo = etiqueta.toLowerCase();
    const atributos = leerAtributos(atributosTexto);
    revisarAtributos(tipo, atributos, bloqueados);

    if (tipo === 'style') {
      if (contenido.length > 0) style.add(hashCsp(contenido));
    } else if (!atributos.has('src')) {
      const tipoMime = (atributos.get('type') ?? '').trim().toLowerCase();
      if (contenido.length > 0 && !TIPOS_DE_DATOS.has(tipoMime)) script.add(hashCsp(contenido));
    }
    return '';
  });

  for (const [completo, atributosTexto] of sinBloques.matchAll(ETIQUETA_ABIERTA)) {
    const nombre = /^<([\w:-]+)/.exec(completo)?.[1]?.toLowerCase() ?? '?';
    revisarAtributos(nombre, leerAtributos(atributosTexto), bloqueados);
  }

  return { script: [...script], style: [...style], bloqueados };
}

function revisarAtributos(etiqueta, atributos, bloqueados) {
  for (const nombre of atributos.keys()) {
    if (nombre === 'style' || /^on[a-z]+$/.test(nombre)) {
      bloqueados.push(`<${etiqueta} ${nombre}="…">`);
    }
  }
}

/** Lista, en orden estable, todos los .html de una carpeta y sus subcarpetas. */
export async function listarHtml(carpeta) {
  const entradas = await readdir(carpeta, { recursive: true, withFileTypes: true });
  return entradas
    .filter((entrada) => entrada.isFile() && entrada.name.toLowerCase().endsWith('.html'))
    .map((entrada) => join(entrada.parentPath, entrada.name))
    .sort();
}

/** Reúne los hashes de todo el build. */
export async function calcularHashes(carpetaDist) {
  const script = new Set();
  const style = new Set();
  const bloqueados = [];
  const archivos = await listarHtml(carpetaDist);

  for (const archivo of archivos) {
    const resultado = analizarHtml(await readFile(archivo, 'utf8'));
    resultado.script.forEach((hash) => script.add(hash));
    resultado.style.forEach((hash) => style.add(hash));
    for (const atributo of resultado.bloqueados) {
      bloqueados.push(`${relative(carpetaDist, archivo)}: ${atributo}`);
    }
  }

  return {
    archivos: archivos.length,
    hashes: { script: [...script].sort(), style: [...style].sort() },
    bloqueados,
  };
}

async function principal() {
  const raiz = resolve(dirname(fileURLToPath(import.meta.url)), '..');
  const carpetaDist = resolve(process.argv[2] ?? join(raiz, 'dist'));
  const salida = resolve(process.argv[3] ?? join(raiz, 'csp-hashes.json'));

  let resultado;
  try {
    resultado = await calcularHashes(carpetaDist);
  } catch (error) {
    if (error?.code === 'ENOENT') {
      console.error(`No existe ${carpetaDist}. Ejecuta primero "astro build".`);
      process.exitCode = 1;
      return;
    }
    throw error;
  }

  if (resultado.archivos === 0) {
    console.error(`No se encontró ningún archivo HTML en ${carpetaDist}.`);
    process.exitCode = 1;
    return;
  }

  if (resultado.bloqueados.length > 0) {
    console.error('La CSP de NotIA bloquearía estos atributos en línea:');
    for (const linea of resultado.bloqueados) console.error(`  - ${linea}`);
    console.error('Mueve los estilos a una clase CSS y los eventos al código del componente.');
    process.exitCode = 1;
    return;
  }

  await writeFile(salida, `${JSON.stringify(resultado.hashes, null, 2)}\n`, 'utf8');
  console.log(
    `CSP: ${resultado.archivos} páginas, ${resultado.hashes.script.length} scripts y ` +
      `${resultado.hashes.style.length} estilos en línea → ${relative(raiz, salida)}`,
  );
}

// Solo se ejecuta al llamarlo desde la terminal, no al importarlo en las pruebas.
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  await principal();
}
