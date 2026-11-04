<script lang="ts">
  import { t, unitLabel } from '$lib/i18n.svelte';
  let { compact = false }: { compact?: boolean } = $props();
</script>

<div class="tips" class:compact>
  <svg viewBox="0 0 160 110" class="art" aria-hidden="true">
    <!-- table, sheet in perspective, part, camera from above -->
    <rect x="0" y="0" width="160" height="110" rx="10" fill="var(--surface-high)" />
    <path d="M30 88 L58 40 L132 40 L144 88 Z" fill="var(--surface-container)" stroke="var(--outline)" stroke-width="1.2" />
    <path d="M70 66 L104 66 L104 74 L82 74 L82 82 L70 82 Z" fill="var(--primary)" />
    <circle cx="76" cy="77" r="2" fill="var(--surface-container)" />
    <circle cx="98" cy="70" r="2" fill="var(--surface-container)" />
    <g transform="translate(70 4)">
      <rect x="0" y="6" width="26" height="16" rx="3" fill="var(--on-surface-var)" />
      <rect x="8" y="2" width="10" height="6" rx="2" fill="var(--on-surface-var)" />
      <circle cx="13" cy="14" r="5" fill="var(--surface-container)" />
    </g>
    <path d="M83 26 L83 36" stroke="var(--outline)" stroke-dasharray="2 2" />
    <text x="38" y="102" font-size="9" fill="var(--outline)" font-family="var(--font-sans)">A4 · 210 × 297 {unitLabel('mm')}</text>
  </svg>
  <ul>
    <li>{t('tip_1')}</li>
    <li>{t('tip_2')}</li>
    {#if !compact}<li>{t('tip_3')}</li>{/if}
    <li>{t('tip_4')}</li>
  </ul>
</div>

<style>
  .tips {
    display: grid;
    grid-template-columns: 120px minmax(0, 1fr);
    gap: 12px;
    align-items: center;
  }
  .tips.compact {
    grid-template-columns: 96px minmax(0, 1fr);
  }
  .art {
    width: 100%;
    height: auto;
  }
  ul {
    margin: 0;
    padding-left: 16px;
    font-size: var(--text-md);
    color: var(--on-surface-var);
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  @media (max-width: 420px) {
    .tips {
      grid-template-columns: 1fr;
    }
    .art {
      max-width: 160px;
    }
  }
</style>
