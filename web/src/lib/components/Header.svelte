<script lang="ts">
  import Icon from './Icon.svelte';
  import Logo from './Logo.svelte';
  import ThemePicker from './ThemePicker.svelte';
  import { t, toggleLang } from '$lib/i18n.svelte';
  import { usd } from '$lib/device/i18n';
  import { session, refreshMe } from '$lib/session.svelte';
  import { theme } from '$lib/theme/theme.svelte';
  import { page } from '$app/state';
  import { shop } from '$lib/shop/api';
  import { st } from '$lib/shop/i18n';
  import { onMount, type Snippet } from 'svelte';

  // bare: no bar at all, only the settings and the language in the page's corner (the home page); the links stay in the settings
  let { children, bare = false }: { children?: Snippet; bare?: boolean } = $props();
  let open = $state(false);
  let wrap = $state<HTMLElement>();

  // Formwright Parts: the board link only for the Axo farm's operators
  let operator = $state(false);
  const path = $derived(page.url.pathname);
  const at = (p: string) => path === p || path.startsWith(`${p}/`);

  onMount(() => {
    refreshMe();
    shop.me().then((m) => (operator = m.is_operator)).catch(() => {});
    const id = setInterval(refreshMe, 30000);
    return () => clearInterval(id);
  });

  // pages size themselves against the header (sticky tabs, full-height studio)
  let headerEl = $state<HTMLElement>();
  $effect(() => {
    if (bare || !headerEl || typeof ResizeObserver === 'undefined') return;
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
  const money = (v: number) => usd(v);
  // the day's spend belongs to the settings; it comes up here only when it is about to matter
  const nearLimit = $derived(pct >= 80);
</script>

<!-- composedPath, not contains: the theme toggle swaps its icon on click, detaching the target -->
<svelte:window onclick={(e) => open && wrap && !e.composedPath().includes(wrap) && (open = false)} onkeydown={(e) => e.key === 'Escape' && (open = false)} />

<header class="hd" class:bare bind:this={headerEl}>
  <div class="hd-inner">
    {#if !bare}
      <a class="brand" href="/" aria-label="Formwright">
        <Logo size={26} />
        <span class="name">Formwright</span>
      </a>
      <nav class="nav" aria-label={st('nav.menu')}>
        <a href="/replays" class:on={at('/replays')}><Icon name="play" size={16} /><span>{t('replays')}</span></a>
        <a href="/parts" class:on={at('/parts') && !path.startsWith('/parts/new')}><Icon name="package" size={16} /><span>{st('nav.parts')}</span></a>
        <a href="/parts#orders" class:on={at('/orders')}><Icon name="history" size={16} /><span>{st('nav.orders')}</span></a>
        {#if operator}<a href="/ops" class:on={at('/ops')}><Icon name="printer" size={16} /><span>{st('nav.ops')}</span></a>{/if}
      </nav>
      <div class="mid">{@render children?.()}</div>
    {/if}
    <div class="actions" bind:this={wrap}>
      {#if !bare}
        <a class="btn icon parts" class:here={at('/parts') || at('/orders') || at('/ops')} href={operator ? '/ops' : '/parts'} aria-label={st(operator ? 'nav.ops' : 'nav.parts')} title={st(operator ? 'nav.ops' : 'nav.parts')}>
          <Icon name={operator ? 'printer' : 'package'} size={18} />
        </a>
      {/if}
      {#if session.me && nearLimit}
        <button class="usage" onclick={() => (open = !open)} aria-expanded={open} aria-haspopup="dialog" title={t('usage_hint')}>
          {t('usage')}: {t('usage_of', { a: money(session.me.today_usd), b: money(session.me.limit_usd) })}
        </button>
      {/if}
      <button class="btn icon" onclick={() => (open = !open)} onpointerenter={() => theme.preload()} aria-expanded={open} aria-haspopup="dialog" aria-label={t('settings')} title={t('settings')}>
        <Icon name="gear" size={18} />
      </button>
      <button class="btn icon lang" onclick={toggleLang} aria-label={t('language')}>{t('lang')}</button>
      {#if open}
        <div class="pop" role="dialog" aria-label={t('settings')}>
          <section class="links">
            <h3 class="section-title">{st('nav.menu')}</h3>
            <div class="row">
              <a class="btn small" href="/replays" onclick={() => (open = false)}><Icon name="play" size={14} /> {t('replays')}</a>
              <a class="btn small" href="/parts" onclick={() => (open = false)}><Icon name="package" size={14} /> {st('nav.parts')}</a>
              <a class="btn small" href="/parts#orders" onclick={() => (open = false)}><Icon name="history" size={14} /> {st('nav.orders')}</a>
              {#if operator}<a class="btn small" href="/ops" onclick={() => (open = false)}><Icon name="printer" size={14} /> {st('nav.ops')}</a>{/if}
            </div>
          </section>
          <section>
            <h3 class="section-title">{t('theme')}</h3>
            <ThemePicker />
          </section>
          {#if session.me}
            <section>
              <div class="prow">
                <h3 class="section-title">{t('usage')}</h3>
              </div>
              <div class="meter"><span style:width="{pct}%"></span></div>
              <div class="small">{t('usage_of', { a: money(session.me.today_usd), b: money(session.me.limit_usd) })}</div>
              <p class="small muted">{t('usage_hint')}</p>
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
  .hd.bare {
    position: absolute;
    right: 0;
    width: auto;
    background: none;
    border-bottom: none;
  }
  .bare .actions {
    background: none;
  }
  .bare .btn.icon {
    border-color: transparent;
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
    gap: 8px;
    color: var(--on-surface);
    text-decoration: none;
    flex-shrink: 0;
    margin-right: var(--space-3);
    font-size: var(--text-lg);
    font-weight: var(--font-weight-semibold);
  }
  .mid {
    flex: 1;
    min-width: 0;
  }
  .nav {
    display: flex;
    align-items: center;
    gap: 2px;
    flex-shrink: 0;
  }
  .nav a {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 38px;
    padding: 0 12px;
    border-radius: var(--radius-btn);
    color: var(--on-surface-var);
    font-size: var(--text-md);
    font-weight: var(--font-weight-semibold);
    text-decoration: none;
    transition:
      background-color var(--dur-fast) var(--ease-standard),
      color var(--dur-fast) var(--ease-standard);
  }
  .nav a:hover {
    background: var(--surface-high);
    color: var(--on-surface);
  }
  .nav a.on {
    color: var(--on-surface);
    background: var(--surface-high);
  }
  /* the links fold into one icon (and the settings menu) where the room runs out */
  .btn.icon.parts {
    display: none;
  }
  .btn.icon.parts.here {
    color: var(--on-surface);
  }
  .hd-inner:has(.mid > :global(*)) .nav span {
    display: none;
  }
  .actions {
    position: relative;
    /* a page's bar that runs out of room slides under these buttons instead of covering them */
    z-index: 1;
    background: var(--surface-container-low);
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin-left: auto;
    flex-shrink: 0;
  }
  /* a plain line of text, only near the day's limit */
  .usage {
    border: none;
    background: none;
    padding: 0 var(--space-2);
    color: var(--warn-text);
    font: inherit;
    font-size: var(--text-md);
    font-variant-numeric: tabular-nums;
    cursor: pointer;
  }
  .meter {
    background: var(--surface-high);
    border-radius: var(--radius-xs);
    overflow: hidden;
  }
  .meter {
    height: 6px;
  }
  .meter span {
    display: block;
    height: 100%;
    background: var(--primary);
  }
  .lang {
    font-size: var(--text-md);
    font-weight: var(--font-weight-bold);
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
  @media (max-width: 1100px) {
    .hd-inner:has(.mid > :global(*)) .nav {
      display: none;
    }
  }
  @media (max-width: 720px) {
    .hd-inner {
      padding: var(--space-3) var(--space-4);
    }
    .nav {
      display: none;
    }
    .hd-inner:not(:has(.mid > :global(*))) .btn.icon.parts {
      display: inline-flex;
    }
  }
  @media (max-width: 640px) {
    .name {
      display: none;
    }
  }
  /* phones in the studio: the title, the snap button and settings need the room more than the spend meter */
  @media (max-width: 420px) {
    .usage {
      display: none;
    }
  }
</style>
