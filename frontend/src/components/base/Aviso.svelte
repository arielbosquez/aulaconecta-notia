<script lang="ts">
  // Espacio fijo para un mensaje: siempre ocupa su lugar, haya mensaje o no,
  // así la tarjeta no salta cuando aparece un error. El lector de pantalla lo
  // anuncia una vez (role="alert" para errores, "status" para lo demás).
  interface Props {
    mensaje?: string;
    tipo?: 'error' | 'exito' | 'info';
  }

  let { mensaje = '', tipo = 'error' }: Props = $props();
</script>

<div class="espacio" role={tipo === 'error' ? 'alert' : 'status'} aria-live={tipo === 'error' ? 'assertive' : 'polite'}>
  {#if mensaje}
    <p class="aviso {tipo}">
      <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
        {#if tipo === 'exito'}
          <path d="M4.5 10.5l3.5 3.5 7.5-8" />
        {:else}
          <circle cx="10" cy="10" r="8.5" />
          <path d="M10 5.5v5.5M10 14v.5" />
        {/if}
      </svg>
      <span>{mensaje}</span>
    </p>
  {/if}
</div>

<style>
  .espacio {
    min-height: 3.75rem;
  }

  .aviso {
    display: flex;
    gap: 0.625rem;
    align-items: flex-start;
    padding: 0.75rem 0.875rem;
    border-radius: var(--radio-chico);
    font-size: 0.9375rem;
  }

  svg {
    flex: none;
    margin-top: 0.125rem;
    fill: none;
    stroke: currentColor;
    stroke-width: 2.2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  .error {
    background: var(--error-fondo);
    color: var(--error-texto);
  }

  .exito {
    background: var(--grabado-fondo);
    color: var(--grabado);
  }

  .info {
    background: var(--senal-suave);
    color: var(--tinta);
  }
</style>
