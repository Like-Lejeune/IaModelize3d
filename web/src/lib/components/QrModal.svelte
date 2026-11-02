<script lang="ts">
  import qrcode from 'qrcode-generator';
  import { onMount } from 'svelte';
  import Modal from './Modal.svelte';
  import { api } from '$lib/api';
  import { t } from '$lib/i18n.svelte';

  let { projectId, onClose }: { projectId: string; onClose: () => void } = $props();
  let url = $state('');
  let svg = $state('');
  // a link to this computer's localhost means nothing on the phone
  let local = $state(false);

  onMount(async () => {
    let link = `${location.origin}/c/${projectId}`;
    try {
      const r = await api.captureToken(projectId);
      link = r.url ? new URL(r.url, location.origin).href : `${link}?t=${encodeURIComponent(r.token)}`;
    } catch {
      /* token endpoint optional: same-browser fallback */
    }
    url = link;
    local = /^((.+\.)?localhost|127\.\d+\.\d+\.\d+|\[::1\])$/i.test(new URL(link).hostname);
    const qr = qrcode(0, 'M');
    qr.addData(link);
    qr.make();
    svg = qr.createSvgTag({ cellSize: 5, margin: 2, scalable: true });
  });
</script>

<Modal title={t('phone')} {onClose}>
  <div class="qr">
    <p class="muted">{t('phone_hint')}</p>
    <div class="code" aria-label="QR code">{@html svg}</div>
    <a class="small mono link" href={url} target="_blank" rel="noopener">{url}</a>
    {#if local}<p class="warn small" role="note">{t('qr_localhost')}</p>{/if}
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
    font-size: 12px;
  }
  .warn {
    margin: 0;
    color: var(--warn-text);
    overflow-wrap: anywhere;
  }
</style>
