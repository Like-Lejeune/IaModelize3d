<script lang="ts">
  import Icon from './Icon.svelte';
  import { t, toggleLang, i18n } from '$lib/i18n.svelte';
  import { session, refreshMe, setConsent } from '$lib/session.svelte';
  import { onMount, type Snippet } from 'svelte';

  let { children }: { children?: Snippet } = $props();
  let open = $state(false);
  let theme = $state<'auto' | 'light' | 'dark'>('auto');

  onMount(() => {
    refreshMe();
    document.documentElement.lang = i18n.lang;
    try {
      const v = localStorage.getItem('fw_theme');
      if (v === 'light' || v === 'dark') theme = v;
    } catch {
      /* storage unavailable */
    }
    applyTheme();
    const id = setInterval(refreshMe, 30000);
    return () => clearInterval(id);
  });

  function applyTheme() {
    if (theme === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', theme);
  }

  function cycleTheme() {
    const dark = theme === 'dark' || (theme === 'auto' && matchMedia('(prefers-color-scheme: dark)').matches);
    theme = dark ? 'light' : 'dark';
    try {
      localStorage.setItem('fw_theme', theme);
    } catch {
      /* ignore */
    }
    applyTheme();
  }

  const pct = $derived(session.me ? Math.min(100, (session.me.today_usd / Math.max(0.01, session.me.limit_usd)) * 100) : 0);
  const money = (v: number) => `$${v.toFixed(2)}`;
</script>

<header class="hdr">
  <a class="logo" href="/" aria-label="Formwright">
    <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true"><rect width="32" height="32" rx="8" fill="var(--text)" /><path d="M9 24V8h14v4h-9.5v3.5H21v4h-7.5V24z" fill="var(--accent)" /></svg>
    <span class="name">Formwright</span>
  </a>
  <div class="mid">{@render children?.()}</div>
  <div class="right">
    {#if session.me}
      <button class="usage" onclick={() => (open = !open)} aria-expanded={open} aria-haspopup="dialog" title={t('usage_hint')}>
        <span class="lbl">{t('usage')}</span>
        <span class="bar" aria-hidden="true"><span style:width="{pct}%"></span></span>
        <span class="mono">{t('usage_of', { a: money(session.me.today_usd), b: money(session.me.limit_usd) })}</span>
        <span class="mono short">{money(session.me.today_usd)}</span>
      </button>
    {/if}
    <button class="btn ghost icon small" onclick={cycleTheme} aria-label={t('theme')} title={t('theme')}><Icon name="sun" size={16} /></button>
    <button class="btn ghost small lang" onclick={toggleLang} aria-label="Language">{t('lang')}</button>
  </div>
  {#if open && session.me}
    <div class="pop card" role="dialog" aria-label={t('usage')}>
      <div class="row" style="justify-content: space-between">
        <strong>{t('usage')}</strong>
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
      <button class="btn small" onclick={() => (open = false)}>{t('close')}</button>
    </div>
  {/if}
</header>

<style>
  .hdr {
    position: sticky;
    top: 0;
    z-index: 40;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 14px;
    background: color-mix(in srgb, var(--bg) 85%, transparent);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--line);
    min-height: 54px;
  }
  .logo {
    display: flex;
    align-items: center;
    gap: 9px;
    color: var(--text);
    text-decoration: none;
    font-weight: 700;
    letter-spacing: -0.02em;
    font-size: 16px;
  }
  .mid {
    flex: 1;
    min-width: 0;
  }
  .right {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .usage {
    display: flex;
    align-items: center;
    gap: 8px;
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 999px;
    padding: 4px 10px;
    font-size: var(--fs-xs);
    color: var(--text-2);
  }
  .usage .lbl {
    color: var(--muted);
  }
  .bar {
    width: 36px;
    height: 5px;
    background: var(--panel-3);
    border-radius: 3px;
    overflow: hidden;
    display: inline-block;
  }
  .bar span,
  .meter span {
    display: block;
    height: 100%;
    background: var(--accent);
  }
  .meter {
    height: 6px;
    background: var(--panel-3);
    border-radius: 3px;
    overflow: hidden;
  }
  .lang {
    font-weight: 650;
  }
  .pop {
    position: absolute;
    right: 12px;
    top: 56px;
    width: min(340px, calc(100vw - 24px));
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    box-shadow: var(--shadow-lg);
  }
  .pop p {
    margin: 0;
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
  @media (max-width: 640px) {
    .name,
    .usage .lbl,
    .usage .mono {
      display: none;
    }
    .usage .mono.short {
      display: inline;
    }
    .usage .bar {
      width: 36px;
    }
  }
</style>
