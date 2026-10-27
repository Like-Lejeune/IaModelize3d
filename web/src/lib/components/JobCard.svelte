<script lang="ts">
  import Icon from './Icon.svelte';
  import StepRow from './StepRow.svelte';
  import ResultCard from './ResultCard.svelte';
  import { markdown } from '$lib/md';
  import { t, plural, fmtDuration, fmtMinutes } from '$lib/i18n.svelte';
  import { STAGES, statusLine } from '$lib/steps';
  import type { JobInfo, ProjectStore, TimelineItem } from '$lib/project.svelte';

  let {
    store,
    job,
    items,
    onZoom,
    onAction,
    onUseConcept,
  }: {
    store: ProjectStore;
    job: JobInfo;
    items: TimelineItem[];
    onZoom: (url: string) => void;
    onAction: (a: string) => void;
    onUseConcept?: (url: string) => void;
  } = $props();

  const JOB_ICON: Record<string, string> = { design: 'cube', slice: 'printer', probe: 'flask', concepts: 'sparkles', breed: 'gitfork', visual_edit: 'pencil' };

  let free = $state<Record<string, string>>({});
  let showSteps = $state<boolean | null>(null);
  let now = $state(Date.now() / 1000);

  $effect(() => {
    if (job.status !== 'running' && job.status !== 'waiting') return;
    const id = setInterval(() => (now = Date.now() / 1000), 1000);
    return () => clearInterval(id);
  });

  const active = $derived(job.status === 'running' || job.status === 'waiting');
  const stoppedEarly = $derived(job.status === 'failed' || job.status === 'budget' || job.status === 'cancelled');
  const thinking = $derived(items.filter((i) => i.kind === 'thinking') as Extract<TimelineItem, { kind: 'thinking' }>[]);
  const finalMsg = $derived([...items].reverse().find((i) => i.kind === 'agent') as Extract<TimelineItem, { kind: 'agent' }> | undefined);
  const asks = $derived(items.filter((i) => i.kind === 'ask') as Extract<TimelineItem, { kind: 'ask' }>[]);
  const work = $derived(items.filter((i) => !['thinking', 'agent', 'ask'].includes(i.kind)));
  const stepCount = $derived(work.filter((i) => i.kind === 'tool').length);
  const expanded = $derived(showSteps ?? active);
  const latestStatusItem = $derived([...items].reverse().find((i) => i.kind === 'status') as Extract<TimelineItem, { kind: 'status' }> | undefined);
  const latestStatus = $derived(latestStatusItem?.text);
  const elapsed = $derived((job.finished ?? now) - job.started);
  const stageIdx = $derived(STAGES.indexOf((job.stage ?? 'understand') as any));

  // design jobs without a server result card get one from the latest local build
  const result = $derived.by(() => {
    if (job.result) return job.result;
    if (job.kind !== 'design' || job.status !== 'done' || !store.build) return null;
    const lastVersion = [...items].reverse().find((i) => i.kind === 'program') as any;
    if (!lastVersion) return null;
    const c = store.checks;
    return {
      version: lastVersion.version,
      title: store.detail?.title,
      size_mm: c?.stats?.size,
      est_grams: c?.stats?.estGrams,
      est_minutes: c?.stats?.estMinutes,
      checks: { ok: c?.ok, errors: c?.issues.filter((i) => i.severity === 'error').length ?? 0 },
      render: lastVersion.render,
      params_with_sources: Object.entries(store.build.paramSpecs ?? {}).map(([name, s]) => ({ name, label: s.label, value: store.values[name], unit: s.unit, source: s.source })),
    };
  });

  function statusText(): string {
    if (job.status === 'waiting') return t('answer');
    if (active) return latestStatus ? statusLine(latestStatus) : t('agent_working');
    return t(job.status);
  }
</script>

<section class="job" class:active aria-label={t(`job_${job.kind}`)}>
  <header>
    <span class="kind"><Icon name={JOB_ICON[job.kind] ?? 'cube'} size={15} /></span>
    <strong>{t(`job_${job.kind}`)}</strong>
    <span class="spacer"></span>
    {#if active}<span class="spin" aria-hidden="true"></span>{/if}
    <span class="state" class:ok={job.status === 'done'} class:bad={stoppedEarly}>{active ? fmtDuration(elapsed) : t(job.status)}</span>
  </header>

  {#if job.kind === 'design'}
    <ol class="stepper" aria-label="progress">
      {#each STAGES as s, i (s)}
        {@const reached = job.reached.includes(s) || i < stageIdx || job.status === 'done'}
        {@const current = active && i === stageIdx}
        <li class:reached class:current title={t(`stage.${s}`)}>
          <span class="dot"></span><span class="lab">{t(`stage.${s}`)}</span>
        </li>
      {/each}
    </ol>
  {/if}

  {#if active}<div class="live" aria-live="polite">{statusText()}</div>{/if}

  {#if thinking.length}
    <details class="think">
      <summary><Icon name="brain" size={14} /> {t('thinking')} · {plural(thinking.length, ['note', 'notes'], ['заметка', 'заметки', 'заметок'])}</summary>
      {#each thinking as th (th.key)}<div class="md note">{@html markdown(th.text)}</div>{/each}
    </details>
  {/if}

  {#if work.length}
    {#if !active && stepCount}
      <button class="toggle" onclick={() => (showSteps = !expanded)} aria-expanded={expanded}>
        <Icon name={expanded ? 'chevron-down' : 'chevron'} size={14} />
        {plural(stepCount, ['step', 'steps'], ['шаг', 'шага', 'шагов'])}
      </button>
    {/if}
    {#if expanded}
      <div class="steps">
        {#each work as it (it.key)}
          {#if it.kind === 'tool'}
            <StepRow item={it} {onZoom} />
          {:else if it.kind === 'status'}
            {#if !(active && it === latestStatusItem)}<p class="note-line">{statusLine(it.text)}</p>{/if}
          {:else if it.kind === 'program'}
            <div class="ver">
              <span class="chip mono">v{it.version}</span>
              <span class="small">{it.summary ?? ''}</span>
            </div>
          {:else if it.kind === 'facts'}
            <div class="facts">
              <div class="section-title">{t('facts')}</div>
              {#each it.items as f, i (i)}
                <div class="fact">
                  <span class="subj">{f.subject} · {f.attribute}</span>
                  <strong class="mono">{typeof f.value === 'number' ? f.value : String(f.value).replace(/^"|"$/g, '')} {f.unit ?? ''}</strong>
                  {#if f.source_url}<a href={f.source_url} target="_blank" rel="noopener noreferrer" class="xs">{new URL(f.source_url).hostname.replace(/^www\./, '')} ↗</a>{/if}
                </div>
              {/each}
            </div>
          {:else if it.kind === 'memory'}
            <p class="note-line"><Icon name="brain" size={13} /> {it.items.map((m) => m.name).join(', ')}</p>
          {:else if it.kind === 'critic'}
            <div class="critic" class:pass={it.verdict === 'pass'}>
              <div class="row">
                <Icon name="eye" size={15} />
                <strong class="small">{t('critic')}</strong>
                <span class="chip" class:ok={it.verdict === 'pass'} class:warn={it.verdict !== 'pass'}>{t(it.verdict)}</span>
                {#if it.score != null}<span class="mono xs muted">{t('score_of', { s: it.score })}</span>{/if}
              </div>
              {#if it.issues.length}
                <ul>{#each it.issues as is, i (i)}<li class:major={is.severity === 'major'}>{is.text}</li>{/each}</ul>
              {/if}
            </div>
          {:else if it.kind === 'concepts'}
            <div class="grid">
              {#each it.images as im (im.url)}
                <figure>
                  <button class="tile" onclick={() => onZoom(im.url)}><img src={im.url} alt={im.prompt ?? ''} loading="lazy" /></button>
                  {#if onUseConcept}<button class="btn small" onclick={() => onUseConcept?.(im.url)}>{t('use_this')}</button>{/if}
                </figure>
              {/each}
            </div>
          {:else if it.kind === 'variants'}
            <div class="grid">
              {#each it.items as v (v.version)}
                <figure>
                  {#if v.render}<button class="tile" onclick={() => onZoom(v.render!)}><img src={v.render} alt="v{v.version}" loading="lazy" /></button>{/if}
                  <figcaption class="xs muted">v{v.version} · {v.summary ?? ''}</figcaption>
                </figure>
              {/each}
            </div>
          {:else if it.kind === 'slice'}
            <div class="sliced">
              <Icon name="printer" size={15} />
              <span>{fmtMinutes(it.data?.stats?.minutes)} · {Math.round(it.data?.stats?.grams ?? 0)} {t('grams')}</span>
              <button class="btn small ghost" onclick={() => onAction('slice')}>{t('print')} →</button>
            </div>
          {:else if it.kind === 'probe'}
            <div class="sliced">
              <Icon name="flask" size={15} />
              <span>{it.data?.dimension ?? ''}: {(it.data?.variants ?? []).map((v: any) => v.label).join(' / ')}</span>
              <button class="btn small ghost" onclick={() => onAction('probe')}>{t('print')} →</button>
            </div>
          {:else if it.kind === 'error'}
            <p class="err small"><Icon name="alert" size={14} /> {it.text}</p>
          {/if}
        {/each}
      </div>
    {/if}
  {/if}

  {#each asks as q (q.key)}
    <div class="ask" class:open={!q.answered}>
      <div class="md q">{@html markdown(q.question)}</div>
      {#if q.answered}
        <div class="chip ok">{t('answered')}: {q.answered}</div>
      {:else}
        <div class="opts">
          {#each q.options as opt (opt)}<button class="btn" disabled={store.replaying} onclick={() => store.answer(q, opt)}>{opt}</button>{/each}
        </div>
        {#if q.allow_text && !store.replaying}
          <form
            class="row"
            onsubmit={(e) => {
              e.preventDefault();
              const v = (free[q.key] ?? '').trim();
              if (v) store.answer(q, v);
            }}
          >
            <input type="text" placeholder={t('your_answer')} bind:value={free[q.key]} aria-label={t('your_answer')} style="flex:1" />
            <button class="btn primary small" type="submit">{t('answer')}</button>
          </form>
        {/if}
      {/if}
    </div>
  {/each}

  {#if finalMsg}<div class="final md">{@html markdown(finalMsg.text)}</div>{/if}

  {#if result && job.status === 'done'}
    <ResultCard {result} {onAction} {onZoom} />
  {/if}

  {#if stoppedEarly}
    <div class="stopped">
      <p class="small">{job.status === 'budget' ? t('budget_hint') : t('retry_hint')}</p>
      <button class="btn primary small" onclick={() => store.continueJob()} disabled={store.running || store.replaying}><Icon name="play" size={13} /> {t('continue')}</button>
    </div>
  {/if}

  {#if !active && (job.cost?.usd != null || job.finished)}
    <footer class="xs muted">
      {fmtDuration(elapsed)}{#if job.cost?.usd != null} · {t('cost', { c: `$${Number(job.cost.usd).toFixed(3)}` })}{/if}
    </footer>
  {/if}
</section>

<style>
  .job {
    border: 1px solid var(--line);
    background: var(--panel);
    border-radius: var(--radius);
    padding: 10px 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .job.active {
    border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 10%, transparent);
  }
  header {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: var(--fs-sm);
  }
  .kind {
    width: 24px;
    height: 24px;
    border-radius: 7px;
    display: grid;
    place-items: center;
    background: var(--accent-soft);
    color: var(--accent);
  }
  .state {
    font-size: var(--fs-xs);
    color: var(--muted);
    font-variant-numeric: tabular-nums;
  }
  .state.ok {
    color: var(--ok);
  }
  .state.bad {
    color: var(--err);
  }
  .stepper {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 3px;
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .stepper li {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }
  .stepper .dot {
    height: 4px;
    border-radius: 2px;
    background: var(--panel-3);
  }
  .stepper li.reached .dot {
    background: color-mix(in srgb, var(--accent) 55%, var(--panel-3));
  }
  .stepper li.current .dot {
    background: var(--accent);
    animation: fw-pulse 1.2s ease-in-out infinite alternate;
  }
  @keyframes fw-pulse {
    to {
      opacity: 0.45;
    }
  }
  .stepper .lab {
    font-size: 10.5px;
    color: var(--muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .stepper li.current .lab {
    color: var(--text);
    font-weight: 600;
  }
  .live {
    font-size: var(--fs-sm);
    color: var(--text-2);
  }
  .think summary,
  .toggle {
    font-size: var(--fs-xs);
    color: var(--muted);
    cursor: pointer;
    display: inline-flex;
    gap: 6px;
    align-items: center;
    background: none;
    border: none;
    padding: 0;
    width: fit-content;
    list-style: none;
  }
  .note {
    font-size: var(--fs-sm);
    color: var(--text-2);
    border-left: 2px solid var(--line);
    padding-left: 8px;
    margin: 6px 0;
  }
  .steps {
    display: flex;
    flex-direction: column;
    border-left: 1px dashed var(--line);
    margin-left: 10px;
    padding-left: 10px;
  }
  .note-line {
    margin: 2px 0;
    font-size: var(--fs-xs);
    color: var(--muted);
    font-style: italic;
  }
  .ver {
    display: flex;
    gap: 8px;
    align-items: center;
    padding: 2px 0;
  }
  .facts {
    padding: 4px 0;
  }
  .fact {
    display: flex;
    gap: 6px;
    align-items: baseline;
    flex-wrap: wrap;
    font-size: var(--fs-sm);
  }
  .subj {
    color: var(--text-2);
  }
  .critic {
    border-radius: 8px;
    background: var(--warn-soft);
    padding: 6px 8px;
    margin: 4px 0;
  }
  .critic.pass {
    background: var(--ok-soft);
  }
  .critic ul {
    margin: 4px 0 0;
    padding-left: 18px;
    font-size: var(--fs-sm);
  }
  .critic li.major {
    font-weight: 550;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
    gap: 6px;
    padding: 4px 0;
  }
  figure {
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .tile {
    padding: 0;
    border: 1px solid var(--line);
    border-radius: 8px;
    overflow: hidden;
    cursor: zoom-in;
    background: var(--panel-2);
  }
  .tile img {
    display: block;
    width: 100%;
    aspect-ratio: 1;
    object-fit: cover;
  }
  .sliced {
    display: flex;
    gap: 8px;
    align-items: center;
    font-size: var(--fs-sm);
    padding: 4px 0;
  }
  .ask {
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .ask.open {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .opts {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .opts .btn {
    justify-content: flex-start;
    white-space: normal;
    text-align: left;
    height: auto;
  }
  .final {
    font-size: var(--fs-md);
    line-height: 1.55;
  }
  .stopped {
    display: flex;
    gap: 10px;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    background: var(--warn-soft);
    border-radius: 8px;
    padding: 8px 10px;
  }
  .stopped p {
    margin: 0;
    flex: 1;
    min-width: 180px;
  }
  .err {
    color: var(--err);
    margin: 2px 0;
  }
  footer {
    text-align: right;
  }
</style>
