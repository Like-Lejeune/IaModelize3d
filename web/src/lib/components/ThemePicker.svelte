<script lang="ts">
  import Swatch from './Swatch.svelte';
  import { t } from '$lib/i18n.svelte';
  import { theme } from '$lib/theme/theme.svelte';
  import { THEME_PRESETS, presetForSeed } from '$lib/theme/presets';

  const custom = $derived(!presetForSeed(theme.seed));

  const SWATCH_PX = 26;

  let liveFrame: number | undefined;
  let liveValue = '';

  // dragging the native colour picker previews every frame; the choice is saved on change
  function previewCustom(e: Event) {
    liveValue = (e.currentTarget as HTMLInputElement).value;
    if (liveFrame !== undefined) return;
    liveFrame = requestAnimationFrame(() => {
      liveFrame = undefined;
      theme.previewSeed(liveValue);
    });
  }

  // set as a property: a `value` attribute removed during hydration leaves Chrome warning about an empty colour input
  let customInput = $state<HTMLInputElement>();
  $effect(() => {
    if (customInput) customInput.value = theme.seed;
  });

  function pickCustom(e: Event) {
    if (liveFrame !== undefined) {
      cancelAnimationFrame(liveFrame);
      liveFrame = undefined;
    }
    void theme.setSeed((e.currentTarget as HTMLInputElement).value);
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="tp" onpointerenter={() => theme.preload()} onfocusin={() => theme.preload()}>
  <button
    type="button"
    class="mode pressable"
    onclick={() => theme.toggleMode()}
    aria-label={theme.mode === 'dark' ? t('theme_to_light') : t('theme_to_dark')}
    title={theme.mode === 'dark' ? t('theme_to_light') : t('theme_to_dark')}
  >
    {#if theme.mode === 'dark'}
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <circle cx="12" cy="12" r="4" />
        <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4" />
      </svg>
    {:else}
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M19 14.8A8.5 8.5 0 1 1 9.2 5a6.8 6.8 0 0 0 9.8 9.8z" />
      </svg>
    {/if}
  </button>

  <div class="seeds" role="group" aria-label={t('theme_color')}>
    {#each THEME_PRESETS as preset (preset.id)}
      <Swatch
        size={SWATCH_PX}
        color={preset.primary[theme.mode]}
        selected={theme.seed === preset.seed}
        label={t(`theme_preset_${preset.id}`)}
        tooltip={t(`theme_preset_${preset.id}`)}
        onclick={() => void theme.setSeed(preset.seed)}
      />
    {/each}

    <label class="custom" class:selected={custom} title={t('theme_custom')}>
      <span class="custom-face" style={custom ? `background:${theme.seed}` : undefined}></span>
      <input bind:this={customInput} type="color" oninput={previewCustom} onchange={pickCustom} aria-label={t('theme_custom')} />
    </label>
  </div>
</div>

<style>
  .tp {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }

  .seeds {
    display: flex;
    align-items: center;
    gap: 6px;
    --swatch-selected-ring: var(--on-surface);
  }

  .mode {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    padding: 0;
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-btn);
    background: transparent;
    color: var(--on-surface-var);
    cursor: pointer;
  }
  .mode:hover {
    color: var(--on-surface);
    border-color: var(--outline);
  }
  .mode:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: 2px;
  }
  .mode svg {
    width: 18px;
    height: 18px;
    stroke: currentColor;
    stroke-width: 1.8;
    stroke-linecap: round;
    stroke-linejoin: round;
    fill: none;
  }

  .custom {
    position: relative;
    display: inline-block;
    width: 26px;
    height: 26px;
    border-radius: var(--radius-swatch);
    cursor: pointer;
  }
  .custom-face {
    position: absolute;
    inset: 0;
    border: var(--border-width) solid var(--swatch-inner-ring);
    border-radius: inherit;
    background: conic-gradient(from 0deg, #ff5a5a, #ffd23f, #7ed957, #4bc8e0, #6a7bff, #c86af0, #ff5a5a);
  }
  .custom.selected .custom-face {
    outline: 2.5px solid var(--swatch-selected-ring);
    outline-offset: 0;
  }
  .custom input {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    margin: 0;
    padding: 0;
    border: none;
    opacity: 0;
    cursor: pointer;
  }
  .custom:focus-within .custom-face {
    outline: 2px solid var(--primary);
    outline-offset: 2px;
  }

  @media (max-width: 720px) {
    .tp {
      gap: var(--space-2);
    }
  }
</style>
