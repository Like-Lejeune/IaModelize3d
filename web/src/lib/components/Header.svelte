<script lang="ts">
  import Icon from './Icon.svelte';
  import ThemePicker from './ThemePicker.svelte';
  import { t, toggleLang, i18n } from '$lib/i18n.svelte';
  import { session, refreshMe, setConsent } from '$lib/session.svelte';
  import { theme } from '$lib/theme/theme.svelte';
  import { onMount, type Snippet } from 'svelte';

  let { children }: { children?: Snippet } = $props();
  let open = $state(false);
  let wrap = $state<HTMLElement>();

  onMount(() => {
    refreshMe();
    document.documentElement.lang = i18n.lang;
    const id = setInterval(refreshMe, 30000);
    return () => clearInterval(id);
  });

  // pages size themselves against the header (sticky tabs, full-height studio)
  let headerEl = $state<HTMLElement>();
  $effect(() => {
    if (!headerEl || typeof ResizeObserver === 'undefined') return;
    const el = headerEl;
    const root = document.documentElement;
    const publish = () => root.style.setProperty('--header-h', `${el.offsetHeight}px`);
    publish();
    const ro = new ResizeObserver(publish);
    ro.observe(el);
    return () => {
      ro.disconnect();
      root.style.removeProperty('--header-h');
    };
  });

  const pct = $derived(session.me ? Math.min(100, (session.me.today_usd / Math.max(0.01, session.me.limit_usd)) * 100) : 0);
  const money = (v: number) => `$${v.toFixed(2)}`;
</script>

<!-- composedPath, not contains: the theme toggle swaps its icon on click, detaching the target -->
<svelte:window onclick={(e) => open && wrap && !e.composedPath().includes(wrap) && (open = false)} onkeydown={(e) => e.key === 'Escape' && (open = false)} />

<header class="hd" bind:this={headerEl}>
  <div class="hd-inner">
    <a class="brand" href="/" aria-label="Formwright">
      <svg class="mark" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="var(--on-surface)" /><path d="M9 24V8h14v4h-9.5v3.5H21v4h-7.5V24z" fill="var(--primary)" /></svg>
      <span class="name">Formwright</span>
    </a>
    <div class="mid">{@render children?.()}</div>
    <div class="actions" bind:this={wrap}>
      <a class="btn icon snap" href="/snap" aria-label={t('snap_title')} title={t('snap_title')}><Icon name="camera" size={18} /></a>
      {#if session.me}
        <button class="usage pressable" onclick={() => (open = !open)} aria-expanded={open} aria-haspopup="dialog" title={t('usage_hint')}>
          <span class="lbl">{t('usage')}</span>
          <span class="bar" aria-hidden="true"><span style:width="{pct}%"></span></span>
          <span class="mono">{t('usage_of', { a: money(session.me.today_usd), b: money(session.me.limit_usd) })}</span>
          <span class="mono short">{money(session.me.today_usd)}</span>
        </button>
      {/if}
      <button class="btn icon" onclick={() => (open = !open)} onpointerenter={() => theme.preload()} aria-expanded={open} aria-haspopup="dialog" aria-label={t('settings')} title={t('settings')}>
        <Icon name="palette" size={18} />
      </button>
      <button class="btn icon lang" onclick={toggleLang} aria-label="Language">{t('lang')}</button>
      {#if open}
        <div class="pop" role="dialog" aria-label={t('settings')}>
          <section>
            <h3 class="section-title">{t('theme')}</h3>
            <ThemePicker />
          </section>
          {#if session.me}
            <section>
              <div class="prow">
                <h3 class="section-title">{t('usage')}</h3>
                <span class="chip">{session.me.tier}</span>
              </div>
              <div class="meter"><span style:width="{pct}%"></span></div>
              <div class="mono small">{t('usage_of', { a: money(session.me.today_usd), b: money(session.me.limit_usd) })} · {session.me.jobs_today}</div>
              <p class="small muted">{t('usage_hint')}</p>
              <label class="consent">
                <input type="checkbox" checked={session.me.contributor_consent} onchange={(e) => setConsent((e.currentTarget as HTMLInputElement).checked)} />
                <span>
                  <strong class="small">{t('contributor')}</strong>
                  <span class="muted xs">{t('contributor_hint')}</span>
                </span>
              </label>
            </section>
          {/if}
        </div>
      {/if}
    </div>
  </div>
</header>

<style>
  .hd {
    background: var(--surface-container-low);
    border-bottom: var(--border-width) solid var(--outline-variant);
    color: var(--on-surface);
    position: sticky;
    top: 0;
    z-index: 100;
    width: 100%;
  }
  .hd-inner {
    display: flex;
    align-items: center;
    gap: var(--space-3) var(--space-2);
    padding: var(--space-3) var(--space-5);
    width: 100%;
  }
  .brand {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    color: var(--on-surface);
    text-decoration: none;
    flex-shrink: 0;
    margin-right: var(--space-2);
    font-size: var(--text-card-name);
    font-weight: var(--font-weight-bold);
    letter-spacing: -0.3px;
  }
  .mark {
    width: 34px;
    height: 34px;
    display: block;
  }
  .mid {
    flex: 1;
    min-width: 0;
  }
  .actions {
    position: relative;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin-left: auto;
    flex-shrink: 0;
  }
  .usage {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    height: 42px;
    padding: 0 14px;
    background: transparent;
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-btn);
    color: var(--on-surface);
    font-family: inherit;
    font-size: var(--text-card-from);
    font-weight: var(--font-weight-semibold);
    transition: background-color var(--dur-fast) var(--ease-standard);
  }
  .usage:hover {
    background: var(--surface-high);
  }
  .usage .lbl {
    color: var(--outline);
  }
  .bar,
  .meter {
    background: var(--surface-high);
    border-radius: 3px;
    overflow: hidden;
  }
  .bar {
    width: 36px;
    height: 5px;
    display: inline-block;
  }
  .meter {
    height: 6px;
  }
  .bar span,
  .meter span {
    display: block;
    height: 100%;
    background: var(--primary);
  }
  .lang {
    font-size: var(--text-card-from);
    font-weight: var(--font-weight-bold);
  }
  .btn.icon.snap {
    color: var(--primary);
  }
  .pop {
    position: absolute;
    right: 0;
    top: calc(100% + 8px);
    width: min(340px, calc(100vw - 32px));
    padding: var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    background: var(--surface-container);
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-pop);
  }
  .pop section {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .pop section + section {
    border-top: var(--border-width) solid var(--divider);
    padding-top: var(--space-4);
  }
  .pop p {
    margin: 0;
  }
  .prow {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .consent {
    display: flex;
    gap: 10px;
    align-items: flex-start;
    cursor: pointer;
  }
  .consent span {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .usage .short {
    display: none;
  }
  @media (max-width: 720px) {
    .hd-inner {
      padding: var(--space-3) var(--space-4);
    }
  }
  @media (max-width: 640px) {
    .name,
    .usage .lbl,
    .usage .mono {
      display: none;
    }
    .usage .mono.short {
      display: inline;
    }
  }
  /* phones in the studio: the title, the snap button and settings need the room more than the spend meter */
  @media (max-width: 420px) {
    .usage {
      display: none;
    }
  }
</style>
