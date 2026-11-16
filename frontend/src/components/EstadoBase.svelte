<script lang="ts">
  // Componente de arranque: confirma que Astro compila componentes Svelte 5
  // con TypeScript estricto. Se reemplaza por las pantallas reales en la Fase 1.
  interface Props {
    piezas: readonly string[];
  }

  let { piezas }: Props = $props();
</script>

<ul>
  {#each piezas as pieza (pieza)}
    <li>{pieza}</li>
  {/each}
</ul>
