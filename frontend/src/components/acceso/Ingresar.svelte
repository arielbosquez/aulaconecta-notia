<script lang="ts">
  // CU-01 y CU-02: ingresar con correo y contraseña y, para docentes y
  // administración con el 2FA activo, el código como paso 2.
  //
  // El paso 2 reemplaza a la tarjeta del paso 1 (no aparece al lado). El
  // servidor decide todo: si hay paso 2, qué mensaje mostrar y a dónde ir
  // después. Este componente solo muestra lo que el servidor respondió.
  import { onMount } from 'svelte';

  import { ErrorApi, mensajeDe, pedir } from '../../lib/api';
  import { irA, obtenerSesion, paginaQueCorresponde, rutaDe } from '../../lib/sesion';
  import Aviso from '../base/Aviso.svelte';
  import Boton from '../base/Boton.svelte';
  import Campo from '../base/Campo.svelte';
  import Tarjeta from '../base/Tarjeta.svelte';

  type Paso = 'credenciales' | 'codigo';

  let paso: Paso = $state('credenciales');
  let correo = $state('');
  let clave = $state('');
  let codigo = $state('');
  let conRecuperacion = $state(false);
  let error = $state('');
  let ocupado = $state(false);

  onMount(async () => {
    // Con una sesión ya abierta no tiene sentido volver a ingresar.
    try {
      const yo = await obtenerSesion();
      if (yo) irA(rutaDe(paginaQueCorresponde(yo)));
    } catch {
      // Sin conexión: se queda en el formulario y el error aparecerá al enviar.
    }
  });

  async function continuar(): Promise<void> {
    // Después de una contraseña o un código correctos, el servidor ya emitió
    // la sesión; la página que corresponde depende de lo que tenga pendiente.
    const yo = await obtenerSesion();
    irA(yo ? rutaDe(paginaQueCorresponde(yo)) : '/');
  }

  async function ingresar(evento: SubmitEvent): Promise<void> {
    evento.preventDefault();
    error = '';
    ocupado = true;
    try {
      const respuesta = await pedir<{ paso: string }>('/api/auth/login', {
        metodo: 'POST',
        cuerpo: { correo, password: clave },
      });
      if (respuesta.paso === 'mfa') {
        clave = '';
        codigo = '';
        conRecuperacion = false;
        paso = 'codigo';
      } else {
        await continuar();
      }
    } catch (fallo) {
      // Siempre el mensaje del servidor: no revela si el correo existe.
      error = mensajeDe(fallo);
      clave = '';
    } finally {
      ocupado = false;
    }
  }

  async function verificar(evento: SubmitEvent): Promise<void> {
    evento.preventDefault();
    error = '';
    ocupado = true;
    try {
      await pedir('/api/auth/mfa/verificar', { metodo: 'POST', cuerpo: { codigo } });
      await continuar();
    } catch (fallo) {
      if (fallo instanceof ErrorApi && fallo.codigo === 'ticket_invalido') {
        // Pasaron los 5 minutos del ticket: vuelve al paso 1.
        volver();
      }
      error = mensajeDe(fallo);
      codigo = '';
    } finally {
      ocupado = false;
    }
  }

  function volver(): void {
    paso = 'credenciales';
    clave = '';
    codigo = '';
    error = '';
  }

  function alternarRecuperacion(): void {
    conRecuperacion = !conRecuperacion;
    codigo = '';
    error = '';
  }
</script>

{#if paso === 'credenciales'}
  <Tarjeta titulo="Ingresar">
    <form class="formulario" onsubmit={ingresar} novalidate>
      <Campo
        id="correo"
        etiqueta="Correo institucional"
        tipo="email"
        autocompletar="username"
        modoTeclado="email"
        largoMaximo={254}
        bind:valor={correo}
        enfocar
      />
      <Campo
        id="clave"
        etiqueta="Contraseña"
        tipo="password"
        autocompletar="current-password"
        largoMaximo={128}
        bind:valor={clave}
      />
      <Aviso mensaje={error} />
      <Boton tipo="submit" ancho {ocupado}>{ocupado ? 'Ingresando…' : 'Ingresar'}</Boton>
    </form>
    <p class="ayuda">
      ¿Olvidaste tu contraseña? Pídele al colegio que la restablezca.
    </p>
  </Tarjeta>
{:else}
  <Tarjeta titulo="Segundo factor" paso={2} pasos={2}>
    <p class="texto-suave">
      {conRecuperacion
        ? 'Escribe uno de tus códigos de recuperación. Cada código sirve una sola vez.'
        : 'Escribe el código de 6 dígitos que muestra tu aplicación de autenticación.'}
    </p>
    <form class="formulario" onsubmit={verificar} novalidate>
      {#if conRecuperacion}
        <Campo
          id="recuperacion"
          etiqueta="Código de recuperación"
          autocompletar="off"
          largoMaximo={20}
          bind:valor={codigo}
          cifras
          enfocar
        />
      {:else}
        <Campo
          id="codigo"
          etiqueta="Código"
          autocompletar="one-time-code"
          modoTeclado="numeric"
          largoMaximo={6}
          bind:valor={codigo}
          cifras
          enfocar
        />
      {/if}
      <Aviso mensaje={error} />
      <Boton tipo="submit" ancho {ocupado}>{ocupado ? 'Verificando…' : 'Verificar'}</Boton>
    </form>
    <div class="acciones">
      <Boton variante="texto" onclick={volver}>Volver</Boton>
      <Boton variante="texto" onclick={alternarRecuperacion}>
        {conRecuperacion ? 'Usar el código de la aplicación' : 'Usar un código de recuperación'}
      </Boton>
    </div>
  </Tarjeta>
{/if}

<style>
  .formulario {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .ayuda {
    font-size: 0.9375rem;
    color: var(--tinta-suave);
  }

  .acciones {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 0.5rem;
  }
</style>
