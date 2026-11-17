<script lang="ts">
  // CU-04: cambiar la contraseña. Con una contraseña temporal es obligatorio
  // antes de usar el resto del sistema. Dos pasos en la misma tarjeta: la
  // contraseña actual y la nueva. El servidor comprueba las dos juntas y
  // aplica la política (largo por rol, comunes, parecidas al correo).
  import { onMount } from 'svelte';

  import { ErrorApi, mensajeDe, pedir } from '../../lib/api';
  import {
    cerrarSesion,
    irA,
    obtenerSesion,
    paginaQueCorresponde,
    RUTA_INGRESAR,
    rutaDe,
    type Yo,
  } from '../../lib/sesion';
  import Aviso from '../base/Aviso.svelte';
  import Boton from '../base/Boton.svelte';
  import Campo from '../base/Campo.svelte';
  import Tarjeta from '../base/Tarjeta.svelte';

  let yo: Yo | null = $state(null);
  let paso: 1 | 2 = $state(1);
  let actual = $state('');
  let nueva = $state('');
  let repetida = $state('');
  let error = $state('');
  let errorNueva = $state('');
  let errorRepetida = $state('');
  let ocupado = $state(false);

  const temporal = $derived(yo?.pendientes.cambiar_password ?? false);
  const largo = $derived(yo && yo.rol !== 'ALUMNO' ? 12 : 10);

  onMount(async () => {
    try {
      yo = await obtenerSesion();
      if (!yo) irA(RUTA_INGRESAR);
    } catch (fallo) {
      error = mensajeDe(fallo);
    }
  });

  function seguir(evento: SubmitEvent): void {
    evento.preventDefault();
    error = actual ? '' : 'Escribe tu contraseña actual.';
    if (!error) paso = 2;
  }

  function volver(): void {
    paso = 1;
    nueva = '';
    repetida = '';
    errorNueva = '';
    errorRepetida = '';
  }

  async function guardar(evento: SubmitEvent): Promise<void> {
    evento.preventDefault();
    error = '';
    errorNueva = '';
    errorRepetida = nueva === repetida ? '' : 'Las dos contraseñas no coinciden.';
    if (errorRepetida) return;

    ocupado = true;
    try {
      await pedir('/api/auth/cambiar-password', {
        metodo: 'POST',
        cuerpo: { password_actual: actual, password_nueva: nueva },
      });
      // El servidor cerró las demás sesiones y entregó una nueva a este navegador.
      const sesion = await obtenerSesion();
      irA(sesion ? rutaDe(paginaQueCorresponde(sesion)) : RUTA_INGRESAR);
    } catch (fallo) {
      if (fallo instanceof ErrorApi && fallo.codigo === 'password_actual_incorrecta') {
        // El error es del paso 1: se vuelve a él con el mensaje.
        actual = '';
        volver();
        error = fallo.message;
      } else if (fallo instanceof ErrorApi && fallo.erroresDe('password_nueva')) {
        errorNueva = fallo.erroresDe('password_nueva') ?? fallo.message;
      } else {
        error = mensajeDe(fallo);
      }
    } finally {
      ocupado = false;
    }
  }
</script>

{#if yo}
  {#if paso === 1}
    <Tarjeta titulo={temporal ? 'Crea tu contraseña' : 'Cambiar contraseña'} paso={1} pasos={2}>
      <p class="texto-suave">
        {temporal
          ? 'Tu cuenta tiene una contraseña temporal. Antes de seguir, crea una que solo tú conozcas.'
          : 'Primero confirma tu contraseña actual.'}
      </p>
      <form class="formulario" onsubmit={seguir} novalidate>
        <Campo
          id="actual"
          etiqueta={temporal ? 'Contraseña temporal' : 'Contraseña actual'}
          tipo="password"
          autocompletar="current-password"
          largoMaximo={128}
          bind:valor={actual}
          enfocar
        />
        <Aviso mensaje={error} />
        <Boton tipo="submit" ancho>Continuar</Boton>
      </form>
      <div class="acciones">
        {#if temporal}
          <Boton variante="texto" onclick={cerrarSesion}>Cerrar sesión</Boton>
        {:else}
          <a href="/">Volver al inicio</a>
        {/if}
      </div>
    </Tarjeta>
  {:else}
    <Tarjeta titulo="Tu contraseña nueva" paso={2} pasos={2}>
      <form class="formulario" onsubmit={guardar} novalidate>
        <Campo
          id="nueva"
          etiqueta="Contraseña nueva"
          tipo="password"
          autocompletar="new-password"
          largoMaximo={128}
          ayuda="Al menos {largo} caracteres. Evita contraseñas comunes, solo números o parecidas a tu nombre o correo."
          error={errorNueva}
          bind:valor={nueva}
          enfocar
        />
        <Campo
          id="repetida"
          etiqueta="Repite la contraseña nueva"
          tipo="password"
          autocompletar="new-password"
          largoMaximo={128}
          error={errorRepetida}
          bind:valor={repetida}
        />
        <Aviso mensaje={error} />
        <Boton tipo="submit" ancho {ocupado}>{ocupado ? 'Guardando…' : 'Guardar contraseña'}</Boton>
      </form>
      <div class="acciones">
        <Boton variante="texto" onclick={volver}>Volver</Boton>
      </div>
    </Tarjeta>
  {/if}
{:else if error}
  <Aviso mensaje={error} />
{/if}

<style>
  .formulario {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .acciones {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.5rem;
  }
</style>
