<script lang="ts">
  import { page } from '$app/state';
  import { t, toggleLang } from '$lib/i18n.svelte';

  // Minimal phone capture screen opened from the studio's QR code.
  const id = $derived(page.params.id!);
  const token = $derived(page.url.searchParams.get('t'));
  let done = $state<{ kind: string; ok: boolean; msg?: string }[]>([]);
  let busy = $state(0);

  async function send(kind: string, files: FileList | null) {
    if (!files) return;
    for (const f of Array.from(files)) {
      busy++;
      try {
        const fd = new FormData();
        fd.append('kind', kind);
        fd.append('file', f, f.name);
        const q = token ? `?capture=${encodeURIComponent(token)}` : '';
        const res = await fetch(`/api/projects/${id}/assets${q}`, {
          method: 'POST',
          body: fd,
          credentials: 'same-origin',
          headers: token ? { 'X-FW-Capture': token } : {},
        });
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
        done = [...done, { kind, ok: true }];
      } catch (e: any) {
        done = [...done, { kind, ok: false, msg: e?.message ?? String(e) }];
      } finally {
        busy--;
      }
    }
  }
</script>

<svelte:head><title>{t('capture_title')} · Formwright</title></svelte:head>

<main class="cap">
  <div class="top">
    <strong>Formwright</strong>
    <button class="btn ghost small" onclick={toggleLang}>{t('lang')}</button>
  </div>
  <h1>{t('capture_title')}</h1>
  <label class="big btn primary">
    📷 {t('take_photo')}
    <input class="sr-only" type="file" accept="image/*" capture="environment" onchange={(e) => send('photo', (e.currentTarget as HTMLInputElement).files)} />
  </label>
  <label class="big btn">
    📏 {t('caliper')}
    <input class="sr-only" type="file" accept="image/*" capture="environment" onchange={(e) => send('caliper', (e.currentTarget as HTMLInputElement).files)} />
  </label>
  <label class="big btn">
    🎬 {t('take_video')}
    <input class="sr-only" type="file" accept="video/*" capture="environment" onchange={(e) => send('video', (e.currentTarget as HTMLInputElement).files)} />
  </label>
  {#if busy}<p class="muted">{t('upload')}… ({busy})</p>{/if}
  {#each done as d, i (i)}
    <p class={d.ok ? 'ok' : 'err'}>{d.ok ? `✓ ${d.kind} ${t('uploaded')}` : `✕ ${d.msg}`}</p>
  {/each}
  {#if done.some((d) => d.ok)}<p class="muted">{t('capture_done')}</p>{/if}
</main>

<style>
  .cap {
    max-width: 480px;
    margin: 0 auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .top {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  h1 {
    font-size: 24px;
  }
  .big {
    min-height: 64px;
    font-size: 17px;
  }
  .ok {
    color: var(--ok);
    margin: 0;
  }
  .err {
    color: var(--err);
    margin: 0;
  }
</style>
