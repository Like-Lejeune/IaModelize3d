<script lang="ts">
  import qrcode from 'qrcode-generator';
  import { onMount } from 'svelte';
  import Modal from './Modal.svelte';
  import { api } from '$lib/api';
  import { t } from '$lib/i18n.svelte';

  let { projectId, onClose }: { projectId: string; onClose: () => void } = $props();
  let url = $state('');
  let svg = $state('');

  onMount(async () => {
    let link = `${location.origin}/c/${projectId}`;
    try {
      const r = await api.captureToken(projectId);
      link = r.url ? new URL(r.url, location.origin).href : `${link}?t=${encodeURIComponent(r.token)}`;
    } catch {
      /* token endpoint optional: same-browser fallback */
    }
    url = link;
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
    border-radius: 10px;
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
</style>
