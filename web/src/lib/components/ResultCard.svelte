<script lang="ts">
  // The hand-over at the end of a design job: what was made, whether it prints, what the
  // independent reviewer thought and where every number came from.
  import { getContext } from 'svelte';
  import Icon from './Icon.svelte';
  import SourceBadge from './SourceBadge.svelte';
  import { i18n, t, fmtMinutes, unitLabel, fmtClearance, fmtValue, partName } from '$lib/i18n.svelte';
  import { paramLabel, paramOption } from '$lib/paramtext';
  import { fmtUsd, isOpenWeights, modelName } from '$lib/models';
  import type { EnclosureChecks, ResultCard } from '$lib/types';

  let {
    result,
    onAction,
    onZoom,
    readonly = false,
  }: { result: ResultCard; onAction: (a: string) => void; onZoom: (url: string) => void; readonly?: boolean } = $props();

  // the studio page shares its latest case check ('fw.enclosure'): a card without its own shows that one for its version
  const studio = getContext<{ readonly current: EnclosureChecks | null } | undefined>('fw.enclosure');

  let sources = $state(false);
  // the iso render may not exist on older runs; fall back to the views image
  let coverFailed = $state(false);

  const mm = (v: number) => String(+Number(v).toFixed(1));
  // next steps the UI names in its own language (n.label is the run's)
  const NEXT = new Set(['download', 'slice', 'probe', 'order', 'share']);
  // someone else's run (read-only): the files are theirs to take, the next steps are the owner's
  const next = $derived((result.next ?? []).filter((n) => !readonly || n.action === 'download'));
  const hero =$derived(result.compare ?? (coverFailed ? null : result.cover) ?? result.render ?? null);
  const second = $derived(result.compare ? ((coverFailed ? null : result.cover) ?? result.render ?? null) : null);
  const errors = $derived(result.checks?.errors ?? 0);
  const printable = $derived(result.checks?.ok !== false && errors === 0);
  const critic = $derived(result.critic ?? null);
  // the server stands in a pass when the reviewer could not answer: that is no review
  const reviewed = $derived(!!critic?.verdict && critic.note !== 'reviewer unavailable');
  const reviewedV = $derived(result.reviewed_version ?? critic?.version ?? null);
  // later versions than the reviewed one shipped without another look
  const stale = $derived(reviewed && reviewedV != null && result.version != null && reviewedV < result.version);
  const score = $derived(critic?.match_score);
  const usd = $derived(result.cost?.usd ?? result.cost_usd);
  const size = $derived(result.size_mm?.length ? `${result.size_mm.map(mm).join(' × ')} ${unitLabel('mm')}` : '');
  const enc = $derived.by(() => {
    if (result.enclosure?.summary) return result.enclosure;
    const c = studio?.current;
    return c && (result.version == null || c.version === result.version) ? c : null;
  });
  // "checked against the board: USB 0.27 mm · BOOTSEL 0.3 mm · snaps 1.7 %"
  const encLine = $derived.by(() => {
    const sm = enc?.summary;
    if (!sm) return '';
    const button = enc?.findings?.find((f) => f.code === 'button_reach')?.part;
    const out: string[] = [];
    if (sm.usb_clearance_mm != null) out.push(`USB ${fmtClearance(sm.usb_clearance_mm)}`);
    if (sm.button_gap_mm != null) out.push(`${button ? partName(button) : t('enc_button')} ${fmtValue(sm.button_gap_mm, 'mm')}`);
    if (sm.snap_strain_pct != null) out.push(`${t('enc_snaps_short')} ${fmtValue(sm.snap_strain_pct, '%')}`);
    return out.join(' · ');
  });
</script>

<article class="result" aria-label={t('result_title')}>
  {#if hero}
    <div class="shots" class:two={!!second}>
      <button class="shot" onclick={() => onZoom(hero)} aria-label={t('view')}>
        <img src={hero} alt={result.title ?? ''} loading="lazy" onerror={() => hero === result.cover && (coverFailed = true)} />
      </button>
      {#if second}
        <button class="shot" onclick={() => onZoom(second)} aria-label={t('view')}>
          <img src={second} alt="" loading="lazy" onerror={() => second === result.cover && (coverFailed = true)} />
        </button>
      {/if}
    </div>
  {/if}
  <div class="body">
    <div class="xs muted head">{printable ? t('result_title') : t('result_not_ok')}{result.version ? ` · v${result.version}` : ''}</div>
    {#if result.title}<h3>{result.title}</h3>{/if}
    <div class="facts small">
      <!-- a case's size is its print plate (base and lid side by side), as the viewer's chip says in that layout -->
      {#if size}<span class="mono">{enc ? `${t('size_plate')} ` : ''}{size}</span>{/if}
      {#if result.est_grams}<span>≈{mm(result.est_grams)} {t('grams')}</span>{/if}
      {#if result.est_minutes}<span>≈{fmtMinutes(result.est_minutes)}</span>{/if}
    </div>
    <div class="chips">
      <span class="chip" class:ok={printable} class:err={!printable}>
        <Icon name={printable ? 'check' : 'alert'} size={12} />
        {printable ? t('printable') : t('not_printable')}{result.checks?.score != null ? ` · ${result.checks.score}` : ''}
      </span>
      {#if reviewed}
        {@const forced = !!critic?.forced_by && score != null}
        <span class="chip" class:ok={critic?.verdict === 'pass' && !forced && !stale} class:warn={critic?.verdict !== 'pass' || forced || stale}>
          <Icon name="eye" size={12} />
          <span>
            {t('reviewer')}: {forced ? t('critic_forced', { score: score! }) : score != null ? t('score_of', { s: score }) : t(critic!.verdict!)}
            {#if critic?.model}<span class="sub">· {modelName(critic.model)}{isOpenWeights(critic.model) ? ` (${t('open_weights')})` : ''}</span>{/if}
            {#if reviewedV}<span class="sub">· {t('reviewed_v', { v: reviewedV })}</span>{/if}
          </span>
        </span>
      {:else}
        <span class="chip warn"><Icon name="eye" size={12} /> {t('reviewer')}: {t('not_reviewed')}</span>
      {/if}
      {#if encLine}
        <span class="chip" class:ok={enc?.ok !== false} class:err={enc?.ok === false}>
          <Icon name={enc?.ok === false ? 'alert' : 'adapter'} size={12} />
          <span>{t('enc_line')}: <span class="mono">{encLine}</span></span>
        </span>
      {/if}
    </div>

    {#if result.params_with_sources?.length}
      <button class="fold small" onclick={() => (sources = !sources)} aria-expanded={sources}>
        <span>{t('where_from')}</span>
        <span class="chev" class:open={sources}><Icon name="chevron" size={12} /></span>
      </button>
      {#if sources}
        <ul class="params">
          {#each result.params_with_sources as p (p.name)}
            {@const raw = p.label ?? p.name}
            {@const label = paramLabel(raw, i18n.lang)}
            <li>
              <span class="pl" title={label !== raw ? raw : undefined}>{label}</span>
              <span class="mono">{typeof p.value === 'number' ? mm(p.value) : paramOption(String(p.value), i18n.lang)}{p.unit ? ` ${unitLabel(p.unit)}` : ''}</span>
              <SourceBadge source={p.source} />
            </li>
          {/each}
        </ul>
      {/if}
    {/if}

    {#if usd}<div class="xs muted">{t('cost', { c: fmtUsd(usd) })}</div>{/if}

    {#if next.length}
      <div class="next">
        {#each next as n, i (n.action)}
          <button class="btn small" class:primary={i === 0} onclick={() => onAction(n.action)}>
            {#if n.action === 'download'}<Icon name="download" size={14} />{/if}
            {NEXT.has(n.action) ? t(`next.${n.action}`) : (n.label ?? n.action)}
          </button>
        {/each}
      </div>
    {/if}
  </div>
</article>

<style>
  .result {
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-card);
    background: var(--surface);
    overflow: hidden;
  }
  .shots {
    display: grid;
    gap: 1px;
    background: var(--outline-variant);
  }
  .shots.two {
    grid-template-columns: 2fr 1fr;
  }
  .shot {
    padding: 0;
    border: none;
    background: var(--surface-container);
    cursor: zoom-in;
    display: block;
    min-width: 0;
  }
  .shot img {
    display: block;
    width: 100%;
    height: 100%;
    max-height: 260px;
    object-fit: contain;
  }
  .body {
    padding: var(--space-3) var(--space-4) var(--space-4);
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .head {
    font-weight: var(--font-weight-semibold);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  h3 {
    margin: 0;
    font-size: var(--text-product-lead);
    font-weight: var(--font-weight-semibold);
    overflow-wrap: anywhere;
  }
  .facts {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 12px;
    color: var(--on-surface-var);
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .chips .chip {
    white-space: normal;
    padding-block: 3px;
  }
  .sub {
    font-weight: normal;
  }
  .fold {
    display: flex;
    align-items: center;
    gap: 4px;
    width: fit-content;
    padding: 2px 0;
    border: none;
    background: none;
    color: var(--outline);
    cursor: pointer;
  }
  .fold:hover {
    color: var(--on-surface);
  }
  .chev {
    display: grid;
    transition: transform 0.12s;
  }
  .chev.open {
    transform: rotate(90deg);
  }
  .params {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: var(--text-card-from);
  }
  .params li {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .pl {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--on-surface-var);
  }
  .next {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 2px;
  }
</style>
