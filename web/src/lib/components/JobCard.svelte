<script lang="ts">
  // One agent run as plain chat: what the agent says reads as text, its work folds into step groups.
  import Icon from './Icon.svelte';
  import ModelStrip from './ModelStrip.svelte';
  import ResultCard from './ResultCard.svelte';
  import DeviceResult from '$lib/device/DeviceResult.svelte';
  import { dt } from '$lib/device/i18n';
  import StepRow from './StepRow.svelte';
  import { markdown } from '$lib/md';
  import { t, fmtDuration, fmtMinutes } from '$lib/i18n.svelte';
  import { callTitle, groupSummary, isSystemStatus } from '$lib/steps';
  import type { JobInfo, ProjectStore, TimelineItem } from '$lib/project.svelte';

  let {
    store,
    job,
    items,
    last,
    onZoom,
    onAction,
    onUseConcept,
    bare = false,
  }: {
    store: ProjectStore;
    job: JobInfo;
    items: TimelineItem[];
    last: boolean;
    onZoom: (url: string) => void;
    onAction: (a: string) => void;
    onUseConcept?: (url: string) => void;
    /** The run alone: no "models in this run" strip and no follow-up suggestions after it (the device workspace). */
    bare?: boolean;
  } = $props();

  type Block = { type: 'text'; key: string; text: string } | { type: 'group'; key: string; items: TimelineItem[] } | { type: 'item'; key: string; item: TimelineItem };

  const WORK = ['tool', 'status', 'critic', 'facts', 'memory'];

  let free = $state<Record<string, string>>({});
  let opened = $state<Record<string, boolean>>({});
  let copied = $state<string | null>(null);
  let reasoning = $state(false);

  const active = $derived(job.status === 'running' || job.status === 'waiting');
  const stoppedEarly = $derived(job.status === 'failed' || job.status === 'budget' || job.status === 'cancelled');
  const stopping = $derived(store.stopping && store.jobId === job.id);
  // the model's reasoning summaries, folded into one group per run
  const thoughts = $derived(items.filter((i): i is Extract<TimelineItem, { kind: 'thinking' }> => i.kind === 'thinking' && !!i.text.trim()));
  // one plain line of the latest summary for the live line
  const thought = $derived(job.thought ? job.thought.replace(/[*_`#>]+/g, '').replace(/\s+/g, ' ').trim() : '');

  const blocks = $derived.by(() => {
    const out: Block[] = [];
    // the closing message often repeats the last thing the model said (older runs cut it at 400 chars)
    const said = items.filter((i) => i.kind === 'agent').map((i) => (i as { text: string }).text.trim());
    for (const it of items) {
      const speech = it.kind === 'agent' || (it.kind === 'status' && (it.say ?? !isSystemStatus(it.text)));
      if (speech) {
        const text = (it as { text: string }).text.trim();
        if (!text || (it.kind === 'status' && said.some((s) => s.startsWith(text.replace(/…$/, '').slice(0, 200))))) continue;
        out.push({ type: 'text', key: it.key, text });
      } else if (WORK.includes(it.kind)) {
        const prev = out[out.length - 1];
        if (prev?.type === 'group') prev.items.push(it);
        else out.push({ type: 'group', key: it.key, items: [it] });
      } else if (it.kind !== 'program' && it.kind !== 'thinking') out.push({ type: 'item', key: it.key, item: it });
    }
    return out;
  });

  const lastText = $derived([...blocks].reverse().find((b) => b.type === 'text')?.key);
  // a finished run: its last words up front, the way there in one folded line (a question or a picture stays in the open)
  const lastAt = $derived(blocks.findLastIndex((b) => b.type === 'text'));
  const folded = $derived(!active && lastAt > 0 ? blocks.slice(0, lastAt).filter((b) => b.type !== 'item') : []);
  const shown = $derived(!active && lastAt > 0 ? blocks.filter((b, i) => i >= lastAt || b.type === 'item') : blocks);
  let logOpen = $state(false);
  const spent = $derived(job.finished ? fmtDuration(job.finished - job.started) : '');
  const tail = $derived(blocks[blocks.length - 1]);
  const busyStep = $derived(tail?.type === 'group' && tail.items.some((i) => i.kind === 'tool' && !i.result));
  const showLive = $derived(active && job.status !== 'waiting' && !busyStep);
  const hasModel = $derived(!!store.source);
  // a crash ends the run without a closing message: the server's calm line with the error id is all there is.
  // Older servers stored the raw exception there, so only that line (and the deadline stop) is shown.
  const stopNote = $derived.by(() => {
    const s = job.status === 'failed' ? (job.summary ?? '').trim() : '';
    if (s === 'took too long; the latest version is kept') return t('job_too_long');
    return /(Error id|Код ошибки): e_\w+/.test(s) ? s : null;
  });
  // a device asks about the device, not about the plastic of its case
  const isDevice = $derived(store.detail?.pack === 'device');
  const suggestions = $derived(
    isDevice
      ? (hasModel ? ['sg_light', 'sg_battery', 'sg_smaller', 'sg_explain'] : ['sg_measures', 'sg_power', 'sg_where']).map((k) => ({
          label: dt(k), text: dt(`${k}_t`), send: hasModel,
        }))
      : hasModel
      ? [t('suggest_stronger'), t('suggest_lighter'), t('suggest_round'), t('suggest_explain')].map((s) => ({ label: s, text: s, send: true }))
      : [
          { label: t('suggest_size'), text: t('suggest_size_t'), send: false },
          { label: t('suggest_mount'), text: t('suggest_mount_t'), send: false },
          { label: t('suggest_load'), text: t('suggest_load_t'), send: false },
        ],
  );

  // folded until asked: a running group already names its current step in the header
  const isOpen = (b: Block) => opened[b.key] ?? false;

  // a running step names itself; a finished group says what it did
  function groupLabel(g: TimelineItem[]): { text: string; live: boolean } {
    const busy = g.find((i) => i.kind === 'tool' && !i.result) as Extract<TimelineItem, { kind: 'tool' }> | undefined;
    if (busy) return { text: callTitle(busy.name, busy.args, busy.title), live: true };
    return { text: groupSummary(g as { kind: string; tkind?: string; name?: string }[]), live: false };
  }

  async function copy(key: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      copied = key;
      setTimeout(() => copied === key && (copied = null), 1500);
    } catch {
      /* clipboard blocked */
    }
  }

  function suggest(s: { text: string; send: boolean }) {
    if (s.send) store.send(s.text);
    else store.draft = s.text;
  }
</script>

{#snippet reasoningGroup()}
    <div class="group">
      <button class="ghead" onclick={() => (reasoning = !reasoning)} aria-expanded={reasoning}>
        <Icon name="brain" size={13} />
        <span class="glabel">{t('reasoning_summary')} · {thoughts.length}</span>
        <span class="chev" class:open={reasoning}><Icon name="chevron" size={12} /></span>
      </button>
      {#if reasoning}
        <div class="gbox thoughts">
          {#each thoughts as th (th.key)}<div class="md">{@html markdown(th.text)}</div>{/each}
        </div>
      {/if}
    </div>
{/snippet}

{#snippet block(b: Block)}
    {#if b.type === 'text'}
      <div class="say md">{@html markdown(b.text)}</div>
      {#if b.key === lastText && !active}
        <div class="actions" class:hover={!last}>
          <button class="act" onclick={() => copy(b.key, b.text)} title={t('copy')} aria-label={t('copy')}>
            <Icon name={copied === b.key ? 'check' : 'copy'} size={14} />
          </button>
          <button class="act" onclick={() => onAction('share')} title={t('share')} aria-label={t('share')}><Icon name="share" size={14} /></button>
        </div>
      {/if}
    {:else if b.type === 'group'}
      {@const open = isOpen(b)}
      {@const label = groupLabel(b.items)}
      <div class="group">
        <button class="ghead" onclick={() => (opened[b.key] = !open)} aria-expanded={open}>
          <span class="glabel" class:shimmer={label.live}>{label.text}</span>
          <span class="chev" class:open><Icon name="chevron" size={12} /></span>
        </button>
        {#if open}
          <div class="gbox">
            {#each b.items as it (it.key)}<StepRow item={it} {onZoom} />{/each}
          </div>
        {/if}
      </div>
    {:else}
      {@const it = b.item}
      {#if it.kind === 'ask'}
        <div class="ask" class:open={!it.answered}>
          <div class="md">{@html markdown(it.question)}</div>
          {#if it.answered}
            <div class="xs muted">{t('answered')}: {it.answered}</div>
          {:else}
            <div class="opts">
              {#each it.options as opt (opt)}<button class="btn" disabled={store.replaying} onclick={() => store.answer(it, opt)}>{opt}</button>{/each}
            </div>
            {#if it.allow_text && !store.replaying}
              <form
                class="row"
                onsubmit={(e) => {
                  e.preventDefault();
                  const v = (free[it.key] ?? '').trim();
                  if (v) store.answer(it, v);
                }}
              >
                <input type="text" placeholder={t('your_answer')} bind:value={free[it.key]} aria-label={t('your_answer')} />
                <button class="btn primary small" type="submit">{t('answer')}</button>
              </form>
            {/if}
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
        <div class="inline">
          <Icon name="printer" size={15} />
          <span>{fmtMinutes(it.data?.stats?.minutes)} · {Math.round(it.data?.stats?.grams ?? 0)} {t('grams')}</span>
          <button class="btn small ghost" onclick={() => onAction('slice')}>{t('print')} →</button>
        </div>
      {:else if it.kind === 'probe'}
        <div class="inline">
          <Icon name="flask" size={15} />
          <span>{it.data?.dimension ?? ''}: {(it.data?.variants ?? []).map((v: any) => v.label).join(' / ')}</span>
          <button class="btn small ghost" onclick={() => onAction('probe')}>{t('print')} →</button>
        </div>
      {:else if it.kind === 'error'}
        <p class="err small">
          <Icon name="alert" size={14} />
          <span>{it.text}{#if it.code === 'job_running' && it.projectId && it.projectId !== store.id}&nbsp;<a href="/p/{it.projectId}">{t('open_blocking')}</a>{/if}</span>
        </p>
      {/if}
    {/if}
{/snippet}

<section class="turn" aria-label={t(`job_${job.kind}`)}>
  {#if !active && (folded.length || thoughts.length)}
    <div class="group">
      <button class="ghead" onclick={() => (logOpen = !logOpen)} aria-expanded={logOpen}>
        <span class="glabel">{t('work_log')}{spent ? ` · ${spent}` : ''}</span>
        <span class="chev" class:open={logOpen}><Icon name="chevron" size={12} /></span>
      </button>
      {#if logOpen}
        <div class="log">
          {#if thoughts.length}{@render reasoningGroup()}{/if}
          {#each folded as b (b.key)}{@render block(b)}{/each}
        </div>
      {/if}
    </div>
  {:else if thoughts.length}
    {@render reasoningGroup()}
  {/if}

  {#each shown as b (b.key)}{@render block(b)}  {/each}

  {#if showLive}
    <div class="live" aria-live="polite">
      {#if stopping}
        <span class="shimmer">{t('stopping')}</span>
      {:else if store.connection === 'retry'}
        <!-- what the job is doing is not known while the stream is down: no thinking and no counter -->
        <span class="shimmer">{t('reconnecting')}</span>
      {:else if job.wait?.outage}
        <span class="shimmer">{t('model_outage')}</span>
      {:else if thought}
        <span class="shimmer lbl">{t('reasoning_summary')}</span>
        <span class="thought" title={thought}>{thought}</span>
      {:else}
        <span class="shimmer">{t('agent_thinking')}</span>
      {/if}
      {#if job.wait?.seconds && !stopping && store.connection !== 'retry'}<span class="secs">{fmtDuration(job.wait.seconds)}</span>{/if}
    </div>
  {/if}

  {#if job.result && !active}
    {#if isDevice}<DeviceResult {store} result={job.result} {onAction} />{:else}<ResultCard result={job.result} {onAction} {onZoom} readonly={store.readonly} />{/if}
  {/if}

  <!-- a visitor's studio (someone else's run) offers no next turn: Remix is theirs to take -->
  <!-- only a design run has a request to take up again: a slice or a set of sketches starts afresh from its own panel -->
  {#if stoppedEarly && last && !store.running && !store.readonly && job.kind === 'design'}
    <div class="stopped small">
      <!-- with no model yet there is no version to keep -->
      <span>{stopNote ?? (job.status === 'budget' ? t('budget_hint') : hasModel ? t('retry_hint') : t('retry_hint_new'))}</span>
      <button class="btn small" onclick={() => store.continueJob()} disabled={store.running || store.replaying}><Icon name="play" size={12} /> {t('continue')}</button>
    </div>
  {:else if stoppedEarly}
    <div class="stopped xs">{stopNote ?? t('job_stopped_old')}</div>
  {/if}

  {#if !active && job.cost && !bare}<ModelStrip cost={job.cost} />{/if}

  {#if last && !bare && !active && !store.running && !store.replaying && !store.readonly}
    <div class="chips" role="group">
      {#each suggestions as s (s.label)}<button class="chip sbtn" onclick={() => suggest(s)}>{s.label}</button>{/each}
    </div>
  {/if}
</section>

<style>
  .turn {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .say {
    font-size: var(--text-base);
    line-height: 1.55;
    overflow-wrap: anywhere;
  }
  .actions {
    display: flex;
    gap: 2px;
    margin: -6px 0 0 -6px;
  }
  .actions.hover {
    opacity: 0;
    transition: opacity 0.12s;
  }
  .turn:hover .actions.hover,
  .actions.hover:focus-within {
    opacity: 1;
  }
  .act {
    width: 28px;
    height: 28px;
    border-radius: var(--radius-btn);
    border: none;
    background: none;
    display: grid;
    place-items: center;
    padding: 0;
    color: var(--outline);
    cursor: pointer;
  }
  .act:hover {
    background: var(--surface-high);
    color: var(--on-surface);
  }
  .group {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .ghead {
    display: flex;
    align-items: center;
    gap: 4px;
    width: 100%;
    min-height: 26px;
    padding: 2px 0;
    border: none;
    background: none;
    text-align: left;
    font-size: var(--text-md);
    color: var(--outline);
    cursor: pointer;
  }
  .ghead:hover {
    color: var(--on-surface);
  }
  .glabel {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .chev {
    flex: none;
    display: grid;
    transition: transform 0.12s;
  }
  .chev.open {
    transform: rotate(90deg);
  }
  .log {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding-left: 10px;
    border-left: var(--border-width) solid var(--divider);
  }
  .gbox {
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-field);
    background: var(--surface);
    overflow: hidden;
  }
  .live {
    display: flex;
    align-items: baseline;
    gap: 6px;
    min-width: 0;
    font-size: var(--text-md);
  }
  .live .lbl,
  .secs {
    flex: none;
  }
  .thought {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--on-surface-var);
  }
  .secs {
    color: var(--outline);
    font-variant-numeric: tabular-nums;
  }
  .thoughts {
    padding: 8px 12px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    max-height: 360px;
    overflow-y: auto;
    font-size: var(--text-md);
    line-height: 1.5;
    color: var(--on-surface-var);
    overflow-wrap: anywhere;
  }
  .ask {
    background: var(--surface);
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-card);
    padding: var(--space-4);
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .ask.open {
    border-color: var(--primary);
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
  .ask .row input {
    flex: 1;
    min-width: 0;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
    gap: 6px;
  }
  figure {
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .tile {
    padding: 0;
    border: var(--border-width) solid var(--outline-variant);
    border-radius: var(--radius-btn);
    overflow: hidden;
    cursor: zoom-in;
    background: var(--surface);
  }
  .tile img {
    display: block;
    width: 100%;
    aspect-ratio: 1;
    object-fit: cover;
  }
  .inline {
    display: flex;
    gap: 8px;
    align-items: center;
    font-size: var(--text-md);
  }
  .err {
    color: var(--error);
    margin: 0;
    display: flex;
    gap: 6px;
    align-items: flex-start;
  }
  .stopped {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
    color: var(--outline);
  }
  .err a {
    color: inherit;
    font-weight: var(--font-weight-semibold);
  }
  .chips {
    display: flex;
    gap: var(--space-2);
    flex-wrap: wrap;
  }
</style>
