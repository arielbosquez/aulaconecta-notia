<script lang="ts">
  import type { Snippet } from 'svelte';

  // Tarjeta de un paso: título, "Paso n de m" y el contenido. Al cambiar de
  // paso se reemplaza su contenido y el foco va al título, para que el lector
  // de pantalla anuncie el paso nuevo.
  interface Props {
    titulo: string;
    paso?: number;
    pasos?: number;
    children: Snippet;
  }

  let { titulo, paso, pasos, children }: Props = $props();
  let encabezado: HTMLHeadingElement | undefined = $state();
  let primera = true;

  $effect(() => {
    // Se lee "titulo" para repetir el efecto con cada paso nuevo.
    void titulo;
    if (primera) {
      primera = false;
      return;
    }
    encabezado?.focus();
  });
</script>

<section class="tarjeta" aria-labelledby="titulo-tarjeta">
  {#if paso && pasos}
    <p class="paso">Paso {paso} de {pasos}</p>
  {/if}
  <h1 id="titulo-tarjeta" tabindex="-1" bind:this={encabezado}>{titulo}</h1>
  {@render children()}
</section>

<style>
  .tarjeta {
    display: flex;
    flex-direction: column;
    gap: 1.125rem;
    width: min(100%, 30rem);
    padding: 2.5rem;
    border-radius: var(--radio-grande);
    background: var(--superficie);
    box-shadow: var(--sombra-tarjeta);
  }

  .paso {
    font-size: 0.9375rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--tinta-suave);
  }

  h1:focus {
    outline: none;
  }

  h1:focus-visible {
    outline: 3px solid var(--senal);
  }

  @media (max-width: 30rem) {
    .tarjeta {
      padding: 1.75rem 1.25rem;
    }
  }
</style>
