<script lang="ts">
  // Activación del 2FA para docentes y administración (RS-06), en tres pasos
  // dentro de la misma tarjeta: escanear el QR, escribir un código y guardar
  // los códigos de recuperación. El QR y el secreto los genera el servidor; el
  // QR llega como imagen (URI data:) y se muestra con <img>, sin insertar HTML.
  import { onMount } from 'svelte';

  import { ErrorApi, mensajeDe, pedir } from '../../lib/api';
  import { cerrarSesion, exigirSesion, irA, type Yo } from '../../lib/sesion';
  import Aviso from '../base/Aviso.svelte';
  import Boton from '../base/Boton.svelte';
  import Campo from '../base/Campo.svelte';
  import Tarjeta from '../base/Tarjeta.svelte';

  interface Enrolamiento {
    qr: string;
    secreto: string;
  }

  let yo: Yo | null = $state(null);
  let paso: 1 | 2 | 3 = $state(1);
  let enrolamiento: Enrolamiento | null = $state(null);
  let codigo = $state('');
  let codigos: string[] = $state([]);
  let guardados = $state(false);
  let error = $state('');
  let ocupado = $state(false);
  let descarga = $state('');

  // El secreto en grupos de 4 para escribirlo a mano sin perderse.
  const secretoLegible = $derived(enrolamiento?.secreto.match(/.{1,4}/g)?.join(' ') ?? '');

  onMount(async () => {
    try {
      yo = await exigirSesion('activar-2fa');
      if (yo) await pedirQr();
    } catch (fallo) {
      error = mensajeDe(fallo);
    }
  });

  async function pedirQr(): Promise<void> {
    ocupado = true;
    error = '';
    try {
      enrolamiento = await pedir<Enrolamiento>('/api/auth/mfa/enrolar', { metodo: 'POST' });
    } catch (fallo) {
      error = mensajeDe(fallo);
    } finally {
      ocupado = false;
    }
  }

  async function confirmar(evento: SubmitEvent): Promise<void> {
    evento.preventDefault();
    error = '';
    ocupado = true;
    try {
      const respuesta = await pedir<{ codigos_recuperacion: string[] }>(
        '/api/auth/mfa/confirmar',
        { metodo: 'POST', cuerpo: { codigo } },
      );
      codigos = respuesta.codigos_recuperacion;
      // Archivo de texto para guardar los códigos; se crea en el navegador.
      descarga = URL.createObjectURL(
        new Blob([`Códigos de recuperación de NotIA\n\n${codigos.join('\n')}\n`], {
          type: 'text/plain;charset=utf-8',
        }),
      );
      enrolamiento = null;
      paso = 3;
    } catch (fallo) {
      error = mensajeDe(fallo);
      codigo = '';
      if (fallo instanceof ErrorApi && fallo.codigo === 'mfa_ya_activado') irA('/');
    } finally {
      ocupado = false;
    }
  }

  function terminar(): void {
    if (descarga) URL.revokeObjectURL(descarga);
    codigos = [];
    irA('/');
  }
</script>

{#if yo}
  {#if paso === 1}
    <Tarjeta titulo="Activa el segundo factor" paso={1} pasos={3}>
      <p class="texto-suave">
        Para proteger los datos de tus cursos, tu cuenta necesita un segundo factor. Abre tu
        aplicación de autenticación y escanea este código.
      </p>
      {#if enrolamiento}
        <img class="qr" src={enrolamiento.qr} alt="Código QR para tu aplicación de autenticación" />
        <div class="secreto">
          <p class="texto-suave">¿No puedes escanearlo? Escribe esta clave en la aplicación:</p>
          <p class="cifras clave" aria-label="Clave para escribir a mano">{secretoLegible}</p>
        </div>
      {/if}
      <Aviso mensaje={error} />
      <Boton ancho deshabilitado={!enrolamiento} {ocupado} onclick={() => (paso = 2)}>
        Ya lo escaneé
      </Boton>
      <div class="acciones">
        <Boton variante="texto" onclick={cerrarSesion}>Cerrar sesión</Boton>
        <Boton variante="texto" onclick={pedirQr}>Generar otro código</Boton>
      </div>
    </Tarjeta>
  {:else if paso === 2}
    <Tarjeta titulo="Escribe el código" paso={2} pasos={3}>
      <p class="texto-suave">Escribe el código de 6 dígitos que muestra ahora la aplicación.</p>
      <form class="formulario" onsubmit={confirmar} novalidate>
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
        <Aviso mensaje={error} />
        <Boton tipo="submit" ancho {ocupado}>{ocupado ? 'Verificando…' : 'Activar'}</Boton>
      </form>
      <div class="acciones">
        <Boton variante="texto" onclick={() => ((paso = 1), (error = ''))}>Volver</Boton>
      </div>
    </Tarjeta>
  {:else}
    <Tarjeta titulo="Guarda tus códigos de recuperación" paso={3} pasos={3}>
      <p>
        El segundo factor quedó activado. Si pierdes el teléfono, podrás entrar con uno de estos
        códigos. Cada uno sirve una sola vez y <strong>esta es la única vez que los verás</strong>.
      </p>
      <ol class="codigos cifras" aria-label="Códigos de recuperación">
        {#each codigos as unCodigo (unCodigo)}
          <li>{unCodigo}</li>
        {/each}
      </ol>
      <a class="descargar" href={descarga} download="notia-codigos-de-recuperacion.txt">
        Descargar los códigos
      </a>
      <label class="confirmacion">
        <input type="checkbox" bind:checked={guardados} />
        Guardé mis códigos en un lugar seguro.
      </label>
      <Boton ancho deshabilitado={!guardados} onclick={terminar}>Continuar</Boton>
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

  .qr {
    align-self: center;
    width: 13.75rem;
    height: 13.75rem;
    border: 1px solid var(--linea-suave);
    border-radius: var(--radio-chico);
    background: #fff;
    image-rendering: pixelated;
  }

  .secreto {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .clave {
    padding: 0.625rem 0.75rem;
    border-radius: var(--radio-chico);
    background: var(--papel);
    font-size: 1.0625rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    word-break: break-all;
  }

  .acciones {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 0.5rem;
  }

  .codigos {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.5rem 1.5rem;
    margin: 0;
    padding: 1rem 1rem 1rem 2.25rem;
    border-radius: var(--radio-chico);
    background: var(--papel);
    font-size: 1.125rem;
    font-weight: 700;
  }

  .descargar {
    align-self: flex-start;
  }

  .confirmacion {
    display: flex;
    gap: 0.625rem;
    align-items: center;
    min-height: 44px;
    font-weight: 700;
  }

  .confirmacion input {
    width: 1.375rem;
    height: 1.375rem;
    accent-color: var(--senal);
  }
</style>
