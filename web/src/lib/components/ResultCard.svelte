<script lang="ts">
  import Icon from './Icon.svelte';
  import SourceBadge from './SourceBadge.svelte';
  import { t, fmtMinutes, unitLabel } from '$lib/i18n.svelte';
  import type { ResultCard } from '$lib/project.svelte';

  let {
    result,
    onAction,
    onZoom,
  }: { result: ResultCard; onAction: (action: string) => void; onZoom?: (url: string) => void } = $props();

  const ok = $derived(result.checks?.ok !== false && !(result.checks?.errors ?? 0));
  const size = $derived(result.size_mm?.length ? result.size_mm.map((v) => +Number(v).toFixed(1)).join(' × ') + ' ' + unitLabel('mm') : null);
  const params = $derived((result.params_with_sources ?? []).filter((p) => p.source && p.source !== 'design').slice(0, 6));
  const img = $derived(result.cover ?? result.render ?? null);
</script>

<article class="result card">
  {#if img}
    <button class="pic" onclick={() => onZoom?.(img)} aria-label={t('view')}><img src={img} alt={result.title ?? ''} /></button>
  {/if}
  <div class="info">
    <div class="head">
      <span class="light" class:ok aria-hidden="true"><Icon name={ok ? 'check' : 'alert'} size={14} stroke={2.4} /></span>
      <div>
        <h3>{ok ? t('result_title') : t('result_not_ok')}</h3>
        {#if result.title}<div class="muted small">{result.title}{result.version ? ` · v${result.version}` : ''}</div>{/if}
      </div>
    </div>
    <dl class="facts">
      {#if size}<div><dt>{t('size')}</dt><dd class="mono">{size}</dd></div>{/if}
      {#if result.est_grams}<div><dt>{t('weight')}</dt><dd class="mono">≈ {Math.round(result.est_grams)} {t('grams')}</dd></div>{/if}
      {#if result.est_minutes}<div><dt>{t('time')}</dt><dd class="mono">≈ {fmtMinutes(result.est_minutes)}</dd></div>{/if}
      {#if result.critic?.verdict}
        <div>
          <dt>{t('reviewer')}</dt>
          <dd>
            <span class="chip" class:ok={result.critic.verdict === 'pass'} class:warn={result.critic.verdict !== 'pass'}>{t(result.critic.verdict)}</span>
            {#if result.critic.match_score != null}<span class="mono small muted">{t('score_of', { s: result.critic.match_score })}</span>{/if}
          </dd>
        </div>
      {/if}
    </dl>
    {#if params.length}
      <div class="src">
        <div class="section-title">{t('where_from')}</div>
        <ul>
          {#each params as p (p.name)}
            <li>
              <span class="lbl">{p.label ?? p.name}</span>
              <span class="mono">{typeof p.value === 'number' ? +p.value.toFixed(2) : p.value}{p.unit ? ` ${unitLabel(p.unit)}` : ''}</span>
              <SourceBadge source={p.source} />
            </li>
          {/each}
        </ul>
      </div>
    {/if}
    <div class="actions">
      <button class="btn primary" onclick={() => onAction('slice')}><Icon name="printer" size={16} /> {t('prepare_print')}</button>
      <button class="btn" onclick={() => onAction('download')}><Icon name="download" size={16} /> {t('download_3mf')}</button>
      <button class="btn ghost" onclick={() => onAction('order')}>{t('order')}</button>
    </div>
  </div>
</article>

<style>
  .result {
    overflow: hidden;
    display: flex;
    flex-direction: column;
    border-color: color-mix(in srgb, var(--accent) 35%, var(--line));
  }
  .pic {
    padding: 0;
    border: none;
    background: var(--panel-2);
    cursor: zoom-in;
    display: block;
  }
  .pic img {
    display: block;
    width: 100%;
    max-height: 220px;
    object-fit: contain;
  }
  .info {
    padding: 12px 14px 14px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .head {
    display: flex;
    gap: 10px;
    align-items: flex-start;
  }
  h3 {
    font-size: var(--fs-md);
  }
  .light {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: var(--warn-soft);
    color: var(--warn);
    flex: none;
  }
  .light.ok {
    background: var(--ok-soft);
    color: var(--ok);
  }
  .facts {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
    gap: 8px;
    margin: 0;
  }
  .facts div {
    background: var(--panel-2);
    border-radius: 8px;
    padding: 6px 8px;
  }
  dt {
    font-size: var(--fs-xs);
    color: var(--muted);
  }
  dd {
    margin: 0;
    font-size: var(--fs-sm);
    display: flex;
    gap: 6px;
    align-items: center;
    flex-wrap: wrap;
  }
  .src ul {
    list-style: none;
    padding: 0;
    margin: 4px 0 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .src li {
    display: flex;
    gap: 8px;
    align-items: center;
    font-size: var(--fs-sm);
  }
  .lbl {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text-2);
  }
  .actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
</style>
