<script lang="ts">
  // Página de inicio con la sesión abierta. Sin sesión lleva a /ingresar, y
  // con un paso pendiente (contraseña temporal o 2FA) lleva a ese paso. Las
  // pantallas de cada rol llegan en las fases siguientes.
  import { onMount } from 'svelte';

  import { mensajeDe } from '../../lib/api';
  import { cerrarSesion, exigirSesion, type Rol, type Yo } from '../../lib/sesion';
  import Aviso from '../base/Aviso.svelte';
  import Boton from '../base/Boton.svelte';
  import Tarjeta from '../base/Tarjeta.svelte';

  const ROLES = new Map<Rol, string>([
    ['ALUMNO', 'Alumno'],
    ['DOCENTE', 'Docente'],
    ['ADMIN', 'Administración'],
  ]);

  let yo: Yo | null = $state(null);
  let error = $state('');
  let ocupado = $state(false);

  onMount(async () => {
    try {
      yo = await exigirSesion('inicio');
    } catch (fallo) {
      error = mensajeDe(fallo);
    }
  });

  async function salir(): Promise<void> {
    ocupado = true;
    await cerrarSesion();
  }
</script>

{#if yo}
  <Tarjeta titulo="Hola, {yo.nombre}">
    <p class="texto-suave">Ingresaste como {ROLES.get(yo.rol) ?? yo.rol}.</p>
    <Boton variante="secundario" ancho {ocupado} onclick={salir}>Cerrar sesión</Boton>
  </Tarjeta>
{:else if error}
  <Aviso mensaje={error} />
{/if}
