<script lang="ts">
  import { t } from '$lib/i18n.svelte';
  import type { ProjectStore } from '$lib/project.svelte';
  import { api, errorText } from '$lib/api';

  let { store }: { store: ProjectStore } = $props();
  let text = $state('');
  let hard = $state(false);
  let attach = $state<string[]>([]);
  let uploading = $state(false);

  async function send() {
    const v = text.trim();
    if (!v && !attach.length) return;
    text = '';
    const ids = attach;
    attach = [];
    await store.send(v || '(see attached)', ids, hard ? 'hard' : 'auto');
  }

  async function addFiles(list: FileList | null) {
    if (!list) return;
    uploading = true;
    try {
      for (const f of Array.from(list)) {
        const kind = f.type.startsWith('video/') ? 'video' : f.type.startsWith('audio/') ? 'audio' : 'photo';
        const a = await api.upload(store.id, f, kind);
        attach = [...attach, a.id];
      }
    } catch (e) {
      store.addError(errorText(e));
    } finally {
      uploading = false;
    }
  }
</script>

<form
  class="composer"
  onsubmit={(e) => {
    e.preventDefault();
    send();
  }}
>
  {#if store.running}
    <div class="row run">
      <span class="muted small">{store.status ?? t('agent_working')}</span>
      {#if store.cost}<span class="chip mono">${store.cost.usd.toFixed(3)}</span>{/if}
      <button type="button" class="btn small" onclick={() => store.cancel()}>{t('cancel')}</button>
    </div>
  {/if}
  <textarea
    bind:value={text}
    rows="2"
    placeholder={t('message_placeholder')}
    aria-label={t('message_placeholder')}
    onkeydown={(e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        send();
      }
    }}
  ></textarea>
  <div class="row">
    <label class="btn small ghost" title={t('upload')}>
      📎{#if attach.length}<span class="chip">{attach.length}</span>{/if}{#if uploading}…{/if}
      <input class="sr-only" type="file" multiple accept="image/*,video/*,audio/*" onchange={(e) => addFiles((e.currentTarget as HTMLInputElement).files)} />
    </label>
    <label class="hard small"><input type="checkbox" bind:checked={hard} /> {t('hard_mode')}</label>
    <span style="flex:1"></span>
    <button class="btn primary small" type="submit" disabled={!text.trim() && !attach.length}>{t('send')}</button>
  </div>
</form>

<style>
  .composer {
    border-top: 1px solid var(--line);
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    background: var(--panel);
  }
  textarea {
    width: 100%;
    min-height: 44px;
  }
  .hard {
    display: flex;
    gap: 4px;
    align-items: center;
    color: var(--muted);
  }
  .small {
    font-size: 13px;
  }
  .run {
    justify-content: space-between;
  }
</style>
