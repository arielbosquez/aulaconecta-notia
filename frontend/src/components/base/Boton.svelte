<script lang="ts">
  import type { Snippet } from 'svelte';

  // Botón base. "primario" para la acción principal de la pantalla (una sola),
  // "secundario" para las demás y "texto" para acciones menores como Volver.
  interface Props {
    variante?: 'primario' | 'secundario' | 'texto';
    tipo?: 'button' | 'submit';
    deshabilitado?: boolean;
    // Mientras espera al servidor: no se puede pulsar de nuevo y lo anuncia.
    ocupado?: boolean;
    ancho?: boolean;
    onclick?: (evento: MouseEvent) => void;
    children: Snippet;
  }

  let {
    variante = 'primario',
    tipo = 'button',
    deshabilitado = false,
    ocupado = false,
    ancho = false,
    onclick,
    children,
  }: Props = $props();
</script>

<button
  type={tipo}
  class="boton {variante}"
  class:ancho
  disabled={deshabilitado || ocupado}
  aria-busy={ocupado}
  {onclick}
>
  {@render children()}
</button>

<style>
  .boton {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    min-height: var(--alto-control);
    padding: 0 1.5rem;
    border-radius: var(--radio);
    font: 700 1.125rem/1.2 var(--letra-texto);
    cursor: pointer;
    transition:
      background-color 120ms ease,
      border-color 120ms ease,
      color 120ms ease;
  }

  .ancho {
    width: 100%;
  }

  .primario {
    border: 0;
    background: var(--senal);
    color: #fff;
  }

  .primario:hover:not(:disabled) {
    background: var(--senal-oscura);
  }

  .secundario {
    border: 2px solid var(--tinta);
    background: var(--superficie);
    color: var(--tinta);
  }

  .secundario:hover:not(:disabled) {
    background: var(--senal-suave);
  }

  .texto {
    min-height: 44px;
    padding: 0 0.5rem;
    border: 0;
    background: transparent;
    color: var(--senal);
    text-decoration: underline;
    text-underline-offset: 0.18em;
  }

  .boton:disabled {
    cursor: not-allowed;
    opacity: 0.6;
  }

  .boton[aria-busy='true'] {
    cursor: progress;
  }
</style>
