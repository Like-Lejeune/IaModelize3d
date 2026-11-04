<script lang="ts">
  // The replay player's controls, under the studio or the device workspace that plays the run: the scrubber with its
  // marks, pause, steps and speed; what to do with the run once it has been watched.
  import Icon from './Icon.svelte';
  import { api, errorText } from '$lib/api';
  import { t } from '$lib/i18n.svelte';
  import { SPEEDS, type ReplayPlayer } from '$lib/replay.svelte';
  import type { Mark } from '$lib/replaylog';
  import { session } from '$lib/session.svelte';

  let { player, onFork, exit }: { player: ReplayPlayer; onFork: () => void; exit: string } = $props();

  /** The moment under a dragged scrubber: the run jumps there on release. */
  let scrub = $state<number | null>(null);
  let copied = $state(false);
  let hidden = $state(false);
  let error = $state<string | null>(null);
  const clock = $derived(scrub ?? player.clock);
  const detail = $derived(player.store.detail);

  const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
  const pct = (s: number) => (player.duration ? (s / player.duration) * 100 : 0);
  const markTitle = (m: Mark) => t(`replay_mark_${m.kind}`, { n: m.n ?? '' });

  async function copyMoment() {
    try {
      await navigator.clipboard.writeText(player.momentUrl());
      copied = true;
      setTimeout(() => (copied = false), 1800);
    } catch {
      prompt('URL', player.momentUrl());
    }
  }

  async function takeDown() {
    if (!confirm(t('replay_hide_q'))) return;
    try {
      await api.replayHide(player.store.id);
      player.pause();
      hidden = true;
      if (detail) detail.public = false;
    } catch (e) {
      error = errorText(e);
    }
  }

  function onKey(e: KeyboardEvent) {
    const el = e.target as HTMLElement | null;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)) return;
    if (e.key === ' ' && el?.tagName !== 'BUTTON' && el?.tagName !== 'A') {
      e.preventDefault();
      player.toggle();
    } else if (e.key === 'ArrowRight') player.step(1);
    else if (e.key === 'ArrowLeft') player.step(-1);
  }
</script>

<svelte:window onkeydown={onKey} />

<div class="bar" role="group" aria-label={t('replay')}>
  {#if player.error}
    <p class="note err" role="alert">{player.error}</p>
    <a class="btn small ghost" href={exit}>{t('replay_open')}</a>
  {:else if player.empty}
    <p class="note">{t('replay_empty')}</p>
    <a class="btn small" href={exit}>{t('replay_open')}</a>
  {:else if hidden}
    <p class="note">{t('replay_hidden')}</p>
  {:else}
    <div class="track">
      <div class="ticks">
        {#each player.marks as m (m.seq)}
          <button class="tick k-{m.kind}" style:--at={pct(m.t) / 100} title={markTitle(m)} aria-label={markTitle(m)} tabindex="-1" onclick={() => player.seek(m.t)}></button>
        {/each}
      </div>
      <input
        type="range"
        min="0"
        max={player.duration || 1}
        step="0.1"
        value={clock}
        disabled={player.loading}
        aria-label={t('replay_seek')}
        aria-valuetext={fmt(clock)}
        oninput={(e) => (scrub = Number((e.currentTarget as HTMLInputElement).value))}
        onchange={(e) => {
          player.seek(Number((e.currentTarget as HTMLInputElement).value));
          scrub = null;
        }}
      />
    </div>
    <div class="ctrls">
      <button class="btn icon small" onclick={() => player.step(-1)} disabled={player.loading} title="{t('replay_prev')} (←)" aria-label={t('replay_prev')}><Icon name="track-prev" size={16} /></button>
      <button class="btn icon primary" onclick={() => player.toggle()} disabled={player.loading} title="{player.playing ? t('replay_pause') : player.finished ? t('replay_again') : t('replay_play')} (Space)" aria-label={player.playing ? t('replay_pause') : player.finished ? t('replay_again') : t('replay_play')}>
        {#if player.loading}<i class="ti ti-loader-2 spin" aria-hidden="true"></i>{:else if player.playing}<Icon name="pause" size={18} />{:else if player.finished}<Icon name="refresh" size={18} />{:else}<Icon name="play" size={18} />{/if}
      </button>
      <button class="btn icon small" onclick={() => player.step(1)} disabled={player.loading} title="{t('replay_next')} (→)" aria-label={t('replay_next')}><Icon name="track-next" size={16} /></button>
      <span class="time mono">{fmt(clock)} / {fmt(player.duration)}</span>
      <div class="speeds" role="radiogroup" aria-label={t('replay_speed')}>
        {#each SPEEDS as s (s)}
          <button role="radio" aria-checked={player.speed === s} class:on={player.speed === s} onclick={() => (player.speed = s)}>{s}×</button>
        {/each}
      </div>
      <!-- while it plays: whose run this is and what it costs; after it, the invitation to go on from it -->
      {#if player.finished}<span class="say">{t('replay_done')}</span>
      {:else}<span class="say">{t('replay_banner')}</span>{/if}
      <span class="spacer"></span>
      {#if error}<span class="err small" role="alert">{error}</span>{/if}
      {#if session.me?.tier === 'admin' && detail?.public}
        <button class="btn icon small ghost" onclick={takeDown} title={t('replay_hide')} aria-label={t('replay_hide')}><Icon name="eye-off" size={16} /></button>
      {/if}
      <button class="btn icon small ghost copy" onclick={copyMoment} disabled={player.loading} title={copied ? t('replay_copied') : t('replay_moment')} aria-label={t('replay_moment')}><Icon name={copied ? 'check' : 'copy'} size={16} /></button>
      <a class="btn small ghost hide-sm" href={exit}>{t('replay_open')}</a>
      <!-- a phone's header has the remix too: the bar keeps to one row until the run is over -->
      <button class="btn small" class:primary={player.finished} class:hide-sm={!player.finished} onclick={onFork}><Icon name="gitfork" size={14} /> {t('fork')}</button>
      {#if player.finished}<a class="btn small ghost hide-sm" href="/">{t('make_your_own')}</a>{/if}
    </div>
  {/if}
</div>

<style>
  .bar {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 6px var(--space-4) 8px;
    background: var(--surface-container);
    border-top: var(--border-width) solid var(--outline-variant);
  }
  .note {
    margin: 0;
    padding: 4px 0;
    font-size: var(--text-md);
  }
  .err {
    color: var(--error);
  }
  .track {
    position: relative;
    padding-top: 12px;
  }
  .track input {
    display: block;
    width: 100%;
    margin: 0;
  }
  /* the range input's thumb stops half its width short of each end: the marks keep to the same stretch */
  .ticks {
    position: absolute;
    inset: 0 8px auto;
    height: 12px;
  }
  .tick {
    position: absolute;
    left: calc(var(--at) * 100%);
    top: 2px;
    width: 3px;
    height: 10px;
    padding: 0;
    border: none;
    border-radius: 1px;
    background: var(--outline);
    transform: translateX(-50%);
    cursor: pointer;
  }
  .tick::before {
    content: '';
    position: absolute;
    inset: -2px -3px;
  }
  .tick:hover {
    background: var(--on-surface);
  }
  .k-version,
  .k-board {
    background: var(--primary);
  }
  .k-ask,
  .k-question {
    background: var(--on-surface);
  }
  .k-error {
    background: var(--error);
  }
  .ctrls {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
    flex-wrap: wrap;
  }
  .time {
    font-size: var(--text-md);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    color: var(--on-surface-var);
  }
  .speeds {
    display: inline-flex;
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-btn);
    overflow: hidden;
  }
  .speeds button {
    padding: 3px 8px;
    border: none;
    background: none;
    color: var(--on-surface-var);
    font: inherit;
    font-size: var(--text-md);
    font-variant-numeric: tabular-nums;
    cursor: pointer;
  }
  .speeds button:hover {
    background: var(--surface-high);
  }
  .speeds button.on {
    background: var(--primary);
    color: var(--on-primary);
  }
  .say {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--text-md);
    color: var(--on-surface-var);
    flex: 0 1 auto;
  }
  .spacer {
    flex: 1;
  }
  @media (max-width: 1000px) {
    .say {
      display: none;
    }
  }
  @media (max-width: 640px) {
    .hide-sm {
      display: none;
    }
    .speeds button {
      padding: 3px 6px;
    }
  }
  /* one row on a phone: the scrubber above already says how far it is */
  @media (max-width: 480px) {
    .time,
    .copy {
      display: none;
    }
    .speeds {
      margin-left: auto;
    }
  }
</style>
