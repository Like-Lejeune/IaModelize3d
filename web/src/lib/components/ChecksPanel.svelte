<script lang="ts">
  import { t } from '$lib/i18n.svelte';
  import type { CheckReport, Issue } from '$lib/types';

  let {
    checks,
    selected = null,
    onSelect,
    building = false,
  }: { checks: CheckReport | null; selected?: Issue | null; onSelect: (i: Issue | null) => void; building?: boolean } = $props();

  const s = $derived(checks?.stats);
</script>

<div class="checks">
  {#if !checks}
    <p class="muted">{t('no_program')}</p>
  {:else}
    <div class="sum">
      <div class="score" class:ok={checks.ok} class:bad={!checks.ok}>{checks.score}</div>
      <div class="stats">
        {#if s}
          <div><span class="muted">{t('size')}</span> <span class="mono">{s.size.map((v) => v.toFixed(1)).join(' × ')} mm</span></div>
          <div><span class="muted">{t('weight')}</span> <span class="mono">~{s.estGrams.toFixed(1)} {t('grams')}</span> · <span class="muted">{t('time')}</span> <span class="mono">~{Math.round(s.estMinutes)} {t('minutes')}</span></div>
          <div class="muted small">{checks.level} · {s.triangles} tris · {Math.round(checks.ms)} ms{building ? ' · …' : ''}</div>
        {/if}
      </div>
    </div>
    {#if !checks.issues.length}
      <p class="ok-msg">✓ {t('no_issues')}</p>
    {/if}
    <ul class="issues">
      {#each checks.issues as is, i (i)}
        <li>
          <button class="issue" class:on={selected === is} onclick={() => onSelect(selected === is ? null : is)} aria-pressed={selected === is}>
            <span class="chip {is.severity === 'error' ? 'err' : is.severity === 'warn' ? 'warn' : 'info'}">{is.severity}</span>
            <span class="msg">{is.message}</span>
          </button>
          {#if selected === is && is.hints.length}
            <ul class="hints">
              {#each is.hints as h (h)}<li>{h}</li>{/each}
            </ul>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .checks {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .sum {
    display: flex;
    gap: 12px;
    align-items: center;
  }
  .score {
    width: 52px;
    height: 52px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    font-weight: 700;
    font-size: 18px;
    border: 3px solid var(--line);
    flex: none;
  }
  .score.ok {
    border-color: var(--ok);
    color: var(--ok);
  }
  .score.bad {
    border-color: var(--err);
    color: var(--err);
  }
  .stats {
    font-size: 13.5px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .small {
    font-size: 12px;
  }
  .ok-msg {
    color: var(--ok);
    margin: 0;
  }
  .issues {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .issue {
    width: 100%;
    text-align: left;
    display: flex;
    gap: 8px;
    align-items: flex-start;
    background: var(--panel-2);
    border: 1px solid var(--line);
    border-radius: 9px;
    padding: 7px 9px;
    font-size: 13px;
  }
  .issue.on {
    border-color: var(--accent);
  }
  .msg {
    overflow-wrap: anywhere;
  }
  .hints {
    margin: 4px 0 0;
    padding-left: 26px;
    font-size: 12.5px;
    color: var(--muted);
  }
</style>
