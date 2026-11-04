<script lang="ts">
  import qrcode from 'qrcode-generator';
  import { onMount } from 'svelte';
  import Modal from './Modal.svelte';
  import { api, errorText } from '$lib/api';
  import { t } from '$lib/i18n.svelte';

  let { projectId, onClose }: { projectId: string; onClose: () => void } = $props();
  let url = $state('');
  let svg = $state('');
  // a link to this computer's localhost means nothing on the phone
  let local = $state(false);
  let error = $state<string | null>(null);

  // without its token the link is refused on the phone: no code then, only the error and another try
  async function make() {
    error = null;
    let link = `${location.origin}/c/${projectId}`;
    try {
      const r = await api.captureToken(projectId);
      link = r.url ? new URL(r.url, location.origin).href : `${link}?t=${encodeURIComponent(r.token)}`;
    } catch (e) {
      error = errorText(e);
      return;
    }
    url = link;
    local = /^((.+\.)?localhost|127\.\d+\.\d+\.\d+|\[::1\])$/i.test(new URL(link).hostname);
    const qr = qrcode(0, 'M');
    qr.addData(link);
    qr.make();
    svg = qr.createSvgTag({ cellSize: 5, margin: 2, scalable: true });
  }

  onMount(make);
</script>

<Modal title={t('phone')} {onClose}>
  <div class="qr">
    <p class="muted">{t('phone_hint')}</p>
    {#if error}
      <p class="err small" role="alert">{error}</p>
      <button class="btn small" onclick={make}>{t('retry')}</button>
    {:else}
      <div class="code" aria-label="QR code">{@html svg}</div>
      <a class="small mono link" href={url} target="_blank" rel="noopener">{url}</a>
      {#if local}<p class="warn small" role="note">{t('qr_localhost')}</p>{/if}
    {/if}
  </div>
</Modal>

<style>
  .qr {
    display: flex;
    flex-direction: column;
    gap: 10px;
    align-items: center;
    text-align: center;
  }
  .code {
    width: 240px;
    max-width: 100%;
    background: #fff;
    padding: 8px;
    border-radius: var(--radius-btn);
  }
  .code :global(svg) {
    width: 100%;
    height: auto;
    display: block;
  }
  .link {
    overflow-wrap: anywhere;
    font-size: var(--text-sm);
  }
  .err {
    margin: 0;
    color: var(--error);
    overflow-wrap: anywhere;
  }
  .warn {
    margin: 0;
    color: var(--warn-text);
    overflow-wrap: anywhere;
  }
</style>
