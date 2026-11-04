<script lang="ts">
  // The finished devices as line drawings in a muted grey, behind the page's first screen: scattered anew on each visit, they
  // fade out towards its bottom and scroll away with it. The parent is positioned and needs a stacking context of its own
  // (isolation: isolate), or the body's background covers the layer.
  import { onMount } from 'svelte';
  import { patternTile, TILE, type Glyph } from './tile';

  let url = $state<string | null>(null);

  onMount(() => {
    let gone = false;
    let made: string | null = null;
    // the drawings load apart from the page and the layer fades in; nothing depends on them, so a failure stays silent
    import('./deviceGlyphs.json')
      .then((m) => {
        if (gone) return;
        made = URL.createObjectURL(new Blob([patternTile(m.default as Glyph[])], { type: 'image/svg+xml' }));
        url = made;
      })
      .catch(() => {});
    return () => {
      gone = true;
      if (made) URL.revokeObjectURL(made);
    };
  });
</script>

<div class="pattern" class:on={!!url} style:background-image={url ? `url(${url})` : undefined} style:background-size="{TILE}px" aria-hidden="true"></div>

<style>
  .pattern {
    position: absolute;
    inset: 0 0 auto;
    height: 100dvh;
    z-index: -1;
    pointer-events: none;
    background-repeat: repeat;
    background-position: center top;
    mask-image: linear-gradient(to bottom, #000 60%, transparent);
    opacity: 0;
    transition: opacity var(--dur-slow) var(--ease-standard);
  }
  .pattern.on {
    opacity: 0.17;
  }
</style>
