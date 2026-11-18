// Cliente de la API de NotIA (sección 14.2).
//
// - Mismo origen y cookies: `credentials: 'same-origin'`. Los tokens viajan
//   en cookies HttpOnly que este código nunca ve.
// - CSRF: en los métodos que modifican datos se envía la cabecera X-CSRFToken
//   con el valor de la cookie csrftoken (la única cookie legible).
// - Renovación: si la API responde 401 porque el token de acceso venció, se
//   pide un par nuevo una sola vez y se repite la petición. Las peticiones que
//   lleguen a la vez comparten esa misma renovación: si cada una renovara por
//   su cuenta, el mismo refresco se usaría dos veces y el servidor lo
//   registraría como reutilizado.
// - Errores: siempre un ErrorApi con un mensaje en español listo para mostrar.
// - Nada se guarda en localStorage ni sessionStorage.

const COOKIE_CSRF = 'csrftoken';
const METODOS_SEGUROS = new Set(['GET', 'HEAD', 'OPTIONS']);

// Rutas que no se reintentan tras renovar: o son la renovación misma, o
// responden 401 por motivos que una sesión nueva no arregla.
const SIN_RENOVACION = new Set([
  '/api/auth/csrf',
  '/api/auth/login',
  '/api/auth/refresh',
  '/api/auth/logout',
  '/api/auth/mfa/verificar',
]);

const MENSAJE_SIN_CONEXION =
  'No pudimos conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.';
const MENSAJE_INESPERADO = 'Ocurrió un error inesperado. Inténtalo de nuevo más tarde.';

export type Detalle = Record<string, string[]>;

export class ErrorApi extends Error {
  readonly estado: number;
  readonly codigo: string;
  readonly detalle: Detalle | undefined;
  readonly #porCampo: Map<string, string[]>;

  constructor(estado: number, codigo: string, mensaje: string, detalle?: Detalle) {
    super(mensaje);
    this.name = 'ErrorApi';
    this.estado = estado;
    this.codigo = codigo;
    this.detalle = detalle;
    this.#porCampo = new Map(Object.entries(detalle ?? {}));
  }

  /** Primer mensaje de error de un campo, si el servidor lo indicó. */
  errorDe(campo: string): string | undefined {
    return this.#porCampo.get(campo)?.[0];
  }

  /** Todos los mensajes de error de un campo, unidos en una frase. */
  erroresDe(campo: string): string | undefined {
    return this.#porCampo.get(campo)?.join(' ');
  }
}

interface Opciones {
  metodo?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  cuerpo?: unknown;
}

function leerCookie(nombre: string): string | undefined {
  for (const parte of document.cookie.split(';')) {
    const [clave, ...resto] = parte.trim().split('=');
    if (clave === nombre) return decodeURIComponent(resto.join('='));
  }
  return undefined;
}

async function asegurarCsrf(): Promise<string> {
  const actual = leerCookie(COOKIE_CSRF);
  if (actual) return actual;
  await enviar('/api/auth/csrf', {});
  const nueva = leerCookie(COOKIE_CSRF);
  if (!nueva) throw new ErrorApi(0, 'csrf_invalido', MENSAJE_INESPERADO);
  return nueva;
}

async function enviar(ruta: string, { metodo = 'GET', cuerpo }: Opciones): Promise<Response> {
  const cabeceras: Record<string, string> = { Accept: 'application/json' };
  if (cuerpo !== undefined) cabeceras['Content-Type'] = 'application/json';
  if (!METODOS_SEGUROS.has(metodo)) cabeceras['X-CSRFToken'] = await asegurarCsrf();
  try {
    return await fetch(ruta, {
      method: metodo,
      credentials: 'same-origin',
      cache: 'no-store',
      redirect: 'error',
      headers: cabeceras,
      body: cuerpo === undefined ? null : JSON.stringify(cuerpo),
    });
  } catch {
    throw new ErrorApi(0, 'sin_conexion', MENSAJE_SIN_CONEXION);
  }
}

async function errorDe(respuesta: Response): Promise<ErrorApi> {
  try {
    const datos: unknown = await respuesta.json();
    if (datos && typeof datos === 'object' && 'codigo' in datos && 'mensaje' in datos) {
      const { codigo, mensaje, detalle } = datos as {
        codigo: unknown;
        mensaje: unknown;
        detalle?: unknown;
      };
      if (typeof codigo === 'string' && typeof mensaje === 'string') {
        const detalleValido =
          detalle && typeof detalle === 'object' ? (detalle as Detalle) : undefined;
        return new ErrorApi(respuesta.status, codigo, mensaje, detalleValido);
      }
    }
  } catch {
    // La respuesta no era JSON: se usa el mensaje genérico.
  }
  return new ErrorApi(respuesta.status, 'error_inesperado', MENSAJE_INESPERADO);
}

let renovacionEnCurso: Promise<boolean> | null = null;

/** Pide un par de tokens nuevo. Las llamadas simultáneas comparten la misma petición. */
export function renovarSesion(): Promise<boolean> {
  renovacionEnCurso ??= enviar('/api/auth/refresh', { metodo: 'POST' })
    .then((respuesta) => respuesta.ok)
    .catch(() => false)
    .finally(() => {
      renovacionEnCurso = null;
    });
  return renovacionEnCurso;
}

/**
 * Llama a la API y devuelve el cuerpo JSON (o `undefined` si la respuesta no
 * trae cuerpo). Ante cualquier error lanza un ErrorApi.
 */
export async function pedir<T = unknown>(ruta: string, opciones: Opciones = {}): Promise<T> {
  let respuesta = await enviar(ruta, opciones);

  if (respuesta.status === 401 && !SIN_RENOVACION.has(ruta)) {
    if (await renovarSesion()) {
      respuesta = await enviar(ruta, opciones);
    }
  }

  if (!respuesta.ok) throw await errorDe(respuesta);
  if (respuesta.status === 204) return undefined as T;
  try {
    return (await respuesta.json()) as T;
  } catch {
    throw new ErrorApi(respuesta.status, 'error_inesperado', MENSAJE_INESPERADO);
  }
}

/** El mensaje que corresponde mostrar para cualquier error capturado. */
export function mensajeDe(error: unknown): string {
  return error instanceof ErrorApi ? error.message : MENSAJE_INESPERADO;
}
