<script lang="ts">
  // Campo de formulario con su etiqueta, ayuda y error asociados (WCAG 1.3.1
  // y 3.3.1). Para contraseñas agrega el botón Mostrar/Ocultar y avisa si
  // Bloq Mayús está activado.
  interface Props {
    id: string;
    etiqueta: string;
    valor: string;
    tipo?: 'text' | 'email' | 'password';
    autocompletar?: HTMLInputElement['autocomplete'];
    modoTeclado?: 'text' | 'numeric' | 'email';
    ayuda?: string;
    error?: string;
    requerido?: boolean;
    largoMaximo?: number;
    // Solo para códigos: letra de cifras y centrada.
    cifras?: boolean;
    enfocar?: boolean;
  }

  let {
    id,
    etiqueta,
    valor = $bindable(),
    tipo = 'text',
    autocompletar,
    modoTeclado,
    ayuda,
    error,
    requerido = true,
    largoMaximo,
    cifras = false,
    enfocar = false,
  }: Props = $props();

  let visible = $state(false);
  let mayusculas = $state(false);
  let campo: HTMLInputElement | undefined = $state();

  const esClave = $derived(tipo === 'password');
  const tipoReal = $derived(esClave && visible ? 'text' : tipo);
  const describe = $derived(
    [ayuda ? `${id}-ayuda` : '', error ? `${id}-error` : '', mayusculas ? `${id}-mayus` : '']
      .filter(Boolean)
      .join(' ') || undefined,
  );

  $effect(() => {
    if (enfocar) campo?.focus();
  });

  function revisarMayusculas(evento: KeyboardEvent): void {
    // getModifierState no existe en todos los eventos sintéticos.
    if (typeof evento.getModifierState === 'function') {
      mayusculas = evento.getModifierState('CapsLock');
    }
  }
</script>

<div class="campo">
  <label for={id}>{etiqueta}</label>
  {#if ayuda}
    <p id="{id}-ayuda" class="ayuda">{ayuda}</p>
  {/if}
  <div class="caja" class:con-boton={esClave}>
    <input
      bind:this={campo}
      {id}
      name={id}
      type={tipoReal}
      bind:value={valor}
      autocomplete={autocompletar}
      inputmode={modoTeclado}
      required={requerido}
      maxlength={largoMaximo}
      spellcheck="false"
      autocapitalize="off"
      aria-invalid={error ? 'true' : undefined}
      aria-describedby={describe}
      class:cifras
      onkeydown={esClave ? revisarMayusculas : undefined}
      onkeyup={esClave ? revisarMayusculas : undefined}
      onblur={() => (mayusculas = false)}
    />
    {#if esClave}
      <button
        type="button"
        class="mostrar"
        aria-controls={id}
        aria-pressed={visible}
        onclick={() => (visible = !visible)}
      >
        {visible ? 'Ocultar' : 'Mostrar'}
        <span class="visualmente-oculto">contraseña</span>
      </button>
    {/if}
  </div>
  {#if esClave && mayusculas}
    <p id="{id}-mayus" class="mayus" role="status">
      <svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
        <path d="M10 3l6 7h-3.5v4h-5v-4H4z M7.5 17h5" />
      </svg>
      Bloq Mayús está activado.
    </p>
  {/if}
  {#if error}
    <p id="{id}-error" class="error">{error}</p>
  {/if}
</div>

<style>
  .campo {
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
  }

  label {
    font-weight: 700;
  }

  .ayuda {
    font-size: 0.9375rem;
    color: var(--tinta-suave);
  }

  .caja {
    position: relative;
    display: flex;
  }

  input {
    width: 100%;
    min-height: 3.125rem;
    padding: 0 0.875rem;
    border: 2px solid var(--borde-campo);
    border-radius: var(--radio-chico);
    background: var(--superficie);
    color: var(--tinta);
    font: 400 1.125rem/1.2 var(--letra-texto);
  }

  .con-boton input {
    padding-right: 6.5rem;
  }

  input:focus-visible {
    border-color: var(--senal);
    outline-offset: 2px;
  }

  input[aria-invalid='true'] {
    border-color: var(--error-texto);
  }

  input.cifras {
    min-height: 4rem;
    font: 700 1.875rem/1 var(--letra-cifras);
    letter-spacing: 0.2em;
    text-align: center;
  }

  .mostrar {
    position: absolute;
    top: 50%;
    right: 0.375rem;
    min-width: 5.5rem;
    min-height: 44px;
    transform: translateY(-50%);
    border: 0;
    border-radius: 10px;
    background: transparent;
    color: var(--senal);
    font: 700 0.9375rem var(--letra-texto);
    cursor: pointer;
  }

  .mostrar:hover {
    background: var(--senal-suave);
  }

  .mayus {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.9375rem;
    font-weight: 700;
    color: var(--al-aire-texto);
  }

  .mayus svg {
    fill: none;
    stroke: currentColor;
    stroke-width: 1.8;
    stroke-linejoin: round;
  }

  .error {
    font-size: 0.9375rem;
    color: var(--error-texto);
  }
</style>
