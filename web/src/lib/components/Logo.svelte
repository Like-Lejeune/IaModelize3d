<script lang="ts">
  // The mark: an F drawn as a copper trace with its pads, the one shape a board and a printed part share.
  let { size = 24 }: { size?: number } = $props();
</script>

<svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
  <path d="M6 21V4h13M6 12h9" stroke="var(--primary)" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" />
  <circle cx="19" cy="4" r="2.6" fill="var(--primary)" />
  <circle cx="15" cy="12" r="2.6" fill="var(--primary)" />
  <circle cx="6" cy="21" r="2.6" fill="var(--primary)" />
  <circle cx="19" cy="4" r="0.9" fill="var(--surface)" />
  <circle cx="15" cy="12" r="0.9" fill="var(--surface)" />
  <circle cx="6" cy="21" r="0.9" fill="var(--surface)" />
</svg>
