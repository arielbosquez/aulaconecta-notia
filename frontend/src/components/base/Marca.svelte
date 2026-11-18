<script lang="ts">
  // Marca de NotIA: una onda de sonido dentro de un cuadrado redondeado.
  interface Props {
    // "clara" sobre fondos oscuros, "oscura" sobre papel.
    tono?: 'clara' | 'oscura';
    tamano?: number;
    conNombre?: boolean;
  }

  let { tono = 'oscura', tamano = 40, conNombre = true }: Props = $props();
</script>

<span class="marca" class:clara={tono === 'clara'}>
  <svg width={tamano} height={tamano} viewBox="0 0 44 44" aria-hidden="true" focusable="false">
    <rect class="fondo" width="44" height="44" rx="12" />
    <path class="onda" d="M9 22h4l3-8 4 16 4-12 3 8 3-4h5" />
  </svg>
  {#if conNombre}
    <span class="nombre">NotIA</span>
  {/if}
</span>

<style>
  .marca {
    display: inline-flex;
    align-items: center;
    gap: 0.75rem;
    color: var(--tinta);
  }

  .fondo {
    fill: var(--tinta);
  }

  .onda {
    fill: none;
    stroke: var(--papel);
    stroke-width: 2.6;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  .clara {
    color: var(--papel);
  }

  .clara .fondo {
    fill: var(--papel);
  }

  .clara .onda {
    stroke: var(--tinta);
  }

  .nombre {
    font-family: var(--letra-titulo);
    font-weight: 800;
    font-size: 2rem;
    letter-spacing: -0.02em;
  }
</style>
