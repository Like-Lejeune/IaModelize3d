<script lang="ts" module>
  // Tabler Icons webfont glyphs by the names the app uses; `npm run icons` subsets the font to what is referenced here.
  export const ICONS: Record<string, string> = {
    camera: 'ti-camera',
    image: 'ti-photo',
    video: 'ti-video',
    mic: 'ti-microphone',
    ruler: 'ti-ruler-2',
    caliper: 'ti-ruler-measure',
    pencil: 'ti-pencil',
    search: 'ti-search',
    book: 'ti-book',
    brain: 'ti-brain',
    sliders: 'ti-adjustments-horizontal',
    cube: 'ti-cube',
    eye: 'ti-eye',
    scan: 'ti-scan',
    target: 'ti-target',
    flask: 'ti-flask',
    sparkles: 'ti-sparkles',
    mountain: 'ti-mountain',
    package: 'ti-package',
    check: 'ti-check',
    'check-circle': 'ti-circle-check',
    message: 'ti-message',
    help: 'ti-help-circle',
    alert: 'ti-alert-triangle',
    x: 'ti-x',
    plus: 'ti-plus',
    download: 'ti-download',
    printer: 'ti-printer',
    share: 'ti-share',
    send: 'ti-send',
    'arrow-up': 'ti-arrow-up',
    stop: 'ti-player-stop-filled',
    chevron: 'ti-chevron-right',
    'chevron-down': 'ti-chevron-down',
    info: 'ti-info-circle',
    sun: 'ti-sun',
    moon: 'ti-moon',
    layers: 'ti-stack-2',
    flame: 'ti-flame',
    maximize: 'ti-maximize',
    phone: 'ti-device-mobile',
    history: 'ti-history',
    gitfork: 'ti-git-fork',
    play: 'ti-player-play',
    refresh: 'ti-refresh',
    globe: 'ti-world',
    lock: 'ti-lock',
    wand: 'ti-wand',
    copy: 'ti-copy',
    hammer: 'ti-hammer',
    adapter: 'ti-plug',
    // printed circuit boards (the PCB tab, the PCB example); Tabler has no board glyph, its chip reads as one
    cpu: 'ti-cpu',
    'circuit-board': 'ti-cpu',
    vase: 'ti-bottle',
    landmark: 'ti-building-monument',
    gear: 'ti-settings',
    figure: 'ti-man',
    home: 'ti-home',
    palette: 'ti-palette',
    dna: 'ti-dna-2',
    'photo-edit': 'ti-photo-edit',
    external: 'ti-external-link',
    'arrow-right': 'ti-arrow-right',
    language: 'ti-language',
    grid: 'ti-layout-grid',
    'arrow-left': 'ti-arrow-left',
    minus: 'ti-minus',
    brush: 'ti-brush',
    'hand-grab': 'ti-hand-grab',
    balloon: 'ti-balloon',
    wave: 'ti-wave-sine',
    'arrows-minimize': 'ti-arrows-minimize',
    scribble: 'ti-scribble',
    'eye-off': 'ti-eye-off',
    trash: 'ti-trash',
    undo: 'ti-arrow-back-up',
    sphere: 'ti-sphere',
    move: 'ti-arrows-move',
    resize: 'ti-arrows-maximize',
    rotate: 'ti-rotate',
    texture: 'ti-texture',
    'grid-dots': 'ti-grid-dots',
    flip: 'ti-flip-vertical',
    user: 'ti-user',
  };
</script>

<script lang="ts">
  let { name, size = 18, label }: { name: string; size?: number; label?: string } = $props();
</script>

<i
  class="ti {ICONS[name] ?? ICONS.info} icon"
  style:font-size="{size}px"
  role={label ? 'img' : undefined}
  aria-label={label}
  aria-hidden={label ? undefined : 'true'}
></i>

<style>
  .icon {
    flex: none;
    display: inline-block;
    line-height: 1;
  }
</style>
