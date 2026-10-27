<script lang="ts">
  import { t, toggleLang, i18n } from '$lib/i18n.svelte';
  import { session, refreshMe, setConsent } from '$lib/session.svelte';
  import { onMount, type Snippet } from 'svelte';

  let { children }: { children?: Snippet } = $props();
  let open = $state(false);

  onMount(() => {
    refreshMe();
    document.documentElement.lang = i18n.lang;
    const id = setInterval(refreshMe, 30000);
    return () => clearInterval(id);
  });

  const pct = $derived(session.me ? Math.min(100, (session.me.today_usd / Math.max(0.01, session.me.limit_usd)) * 100) : 0);
</script>

<header class="hdr">
  <a class="logo" href="/" aria-label="Formwright home">
    <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true"><rect width="32" height="32" rx="7" fill="var(--text)" /><path d="M8 24V8h14v4H12.5v3.5H20v4h-7.5V24z" fill="var(--accent)" /></svg>
    <span>Formwright</span>
  </a>
  <div class="mid">{@render children?.()}</div>
  <div class="right">
    {#if session.me}
      <button class="usage chip" onclick={() => (open = !open)} aria-expanded={open} aria-haspopup="dialog" title={t('usage')}>
        <span class="bar"><span style:width="{pct}%"></span></span>
        ${session.me.today_usd.toFixed(2)} / ${session.me.limit_usd.toFixed(2)}
      </button>
    {/if}
    <button class="btn ghost small" onclick={toggleLang} aria-label="Switch language">{t('lang')}</button>
  </div>
  {#if open && session.me}
    <div class="pop card" role="dialog" aria-label={t('usage')}>
      <div class="row" style="justify-content: space-between">
        <strong>{t('usage')}</strong>
        <span class="chip">{session.me.tier}</span>
      </div>
      <div class="muted">${session.me.today_usd.toFixed(3)} · {session.me.jobs_today} jobs</div>
      <label class="consent">
        <input type="checkbox" checked={session.me.contributor_consent} onchange={(e) => setConsent((e.currentTarget as HTMLInputElement).checked)} />
        <span>
          <strong>{t('contributor')}</strong>
          <span class="muted small">{t('contributor_hint')}</span>
        </span>
      </label>
      <button class="btn small" onclick={() => (open = false)}>OK</button>
    </div>
  {/if}
</header>

<style>
  .hdr {
    position: sticky;
    top: 0;
    z-index: 20;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 14px;
    background: color-mix(in srgb, var(--bg) 88%, transparent);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--line);
    min-height: 52px;
  }
  .logo {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--text);
    text-decoration: none;
    font-weight: 700;
    letter-spacing: -0.01em;
  }
  .mid {
    flex: 1;
    min-width: 0;
    overflow: hidden;
  }
  .right {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .usage {
    cursor: pointer;
    font-family: var(--mono);
  }
  .bar {
    width: 34px;
    height: 5px;
    background: var(--line);
    border-radius: 3px;
    overflow: hidden;
    display: inline-block;
  }
  .bar span {
    display: block;
    height: 100%;
    background: var(--accent);
  }
  .pop {
    position: absolute;
    right: 12px;
    top: 52px;
    width: min(340px, calc(100vw - 24px));
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .consent {
    display: flex;
    gap: 10px;
    align-items: flex-start;
  }
  .consent span {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .small {
    font-size: 12.5px;
  }
  @media (max-width: 480px) {
    .logo span {
      display: none;
    }
  }
</style>
