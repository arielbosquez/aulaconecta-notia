// Estado de la sesión en el navegador (sección 14.1).
//
// Cada página protegida pregunta a la API quién es la persona (`auth/yo`) y,
// si no hay sesión, la lleva a /ingresar. Es solo comodidad: la seguridad
// real está en la API, que rechaza cualquier petición sin una sesión válida.
// Tampoco se guarda nada: el navegador vuelve a preguntar en cada página.

import { ErrorApi, pedir } from './api';

export type Rol = 'ALUMNO' | 'DOCENTE' | 'ADMIN';

export interface Yo {
  nombre: string;
  rol: Rol;
  pendientes: { cambiar_password: boolean; enrolar_mfa: boolean };
}

export type Pagina = 'inicio' | 'cambiar-clave' | 'activar-2fa';

const RUTAS = new Map<Pagina, string>([
  ['inicio', '/'],
  ['cambiar-clave', '/cambiar-clave/'],
  ['activar-2fa', '/seguridad/2fa/'],
]);

export const RUTA_INGRESAR = '/ingresar/';

/** Lleva a otra página sin dejar la actual en el historial. */
export function irA(ruta: string): void {
  window.location.replace(ruta);
}

/** Devuelve la sesión actual, o `null` si no hay una. */
export async function obtenerSesion(): Promise<Yo | null> {
  try {
    return await pedir<Yo>('/api/auth/yo');
  } catch (error) {
    if (error instanceof ErrorApi && error.estado === 401) return null;
    throw error;
  }
}

/**
 * La página que le toca a la persona según lo que tenga pendiente: primero
 * cambiar la contraseña temporal, después activar el 2FA y al final el inicio.
 */
export function paginaQueCorresponde(yo: Yo): Pagina {
  if (yo.pendientes.cambiar_password) return 'cambiar-clave';
  if (yo.pendientes.enrolar_mfa) return 'activar-2fa';
  return 'inicio';
}

export function rutaDe(pagina: Pagina): string {
  return RUTAS.get(pagina) ?? '/';
}

/**
 * Exige una sesión para mostrar la página. Sin sesión lleva a /ingresar; con
 * un paso pendiente lleva a ese paso. Devuelve `null` cuando redirige.
 */
export async function exigirSesion(pagina: Pagina): Promise<Yo | null> {
  const yo = await obtenerSesion();
  if (!yo) {
    irA(RUTA_INGRESAR);
    return null;
  }
  const destino = paginaQueCorresponde(yo);
  if (destino !== pagina) {
    irA(rutaDe(destino));
    return null;
  }
  return yo;
}

/** Cierra la sesión de este navegador y vuelve a /ingresar. */
export async function cerrarSesion(): Promise<void> {
  try {
    await pedir('/api/auth/logout', { metodo: 'POST' });
  } finally {
    irA(RUTA_INGRESAR);
  }
}
