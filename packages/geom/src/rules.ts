// Printability rulebook: what each check means and how to fix it. The agent only
// sees hints for checks that actually fired, so this can grow without bloating prompts.
export interface Rule {
  title: string;
  hints: string[];
  // No check emits this code yet; the entry waits for one. Never list it as something the analyzer finds.
  notImplemented?: true;
}

export const RULES: Record<string, Rule> = {
  invalid_mesh: { title: 'Geometry is not a closed solid', hints: ['Build from closed primitives and booleans; avoid hand-made meshes with gaps.', 'If a surface mesh is required, close it with caps.'] },
  empty: { title: 'Model is empty', hints: ['Check boolean order (subtract removed everything?) and units (mm).'] },
  multiple_bodies: { title: 'Several separate bodies', hints: ['Intended for multi-part prints? Otherwise connect them.', 'Every body must rest on the bed or be supported.'] },
  exceeds_bed: { title: 'Does not fit the print bed', hints: ['Rotate to use the diagonal or another axis.', 'Split with std.splitWithPegs() and glue.'] },
  small_contact: { title: 'Small first-layer contact area', hints: ['Flip to put the largest flat face down.', 'Add a brim or mouse ears (thin 0.4 mm discs at corners).', 'Widen the base.'] },
  tip_over: { title: 'Tall and narrow: may wobble or tip', hints: ['Print lying down if strength allows.', 'Widen the base or add a sacrificial brim.', 'Lower outer wall acceleration in the print profile.'] },
  elephant_foot: { title: 'Mating face touches the bed', hints: ['Add a 0.4-0.6 mm 45° chamfer on bottom edges of fitting faces.'], notImplemented: true },
  overhang: { title: 'Overhang steeper than the printer can do without support', hints: ['Fine on supports (the print profile turns them on) when changing the shape would hurt its look or function.', 'Support-free when it costs nothing: a 45° chamfer or arch from below, or rotate the part.'] },
  floating_island: { title: 'Region starts in mid-air (prints on supports)', hints: ['Fine on supports (the print profile turns them on): arms, chins, brims of hats, overhanging details.', 'Support-free when it costs nothing: a cone or 45° rib under it, or rotate so it starts on the bed.', 'A separate piece floating by mistake: connect it to the body.'] },
  long_bridge: { title: 'Bridge longer than the printer bridges cleanly', hints: ['Shorten the span or add a pillar/rib in the middle.', 'Use an arch or a 45° roof instead of a flat ceiling.'] },
  horizontal_hole: { title: 'Round horizontal hole', hints: ['Use std.holeH() which makes a teardrop pointing up.'], notImplemented: true },
  too_thin: { title: 'Feature thinner than one extrusion line (slicer will drop it)', hints: ['Thicken to at least 2 line widths (~0.9 mm on a 0.4 nozzle).', 'Remove the feature if it is decorative.'] },
  fine_detail: { title: 'Edge detail below one line width (will be rounded, e.g. thread crests)', hints: ['Usually fine. Thicken only if the sharp edge matters.'] },
  thin_wall: { title: 'Wall thinner than two lines', hints: ['Use multiples of the line width: 0.84, 1.26, 1.68 mm on a 0.4 nozzle.'] },
  small_text: { title: 'Text or relief too fine', hints: ['Stroke at least 0.5 mm and depth at least two layers.', 'Put text on a top face instead of a wall.'], notImplemented: true },
  short_layer_time: { title: 'Very short layer time near the top', hints: ['Print several copies at once.', 'Profile: raise minimal layer time / slow down small layers.'] },
  vase_incompatible: { title: 'Not printable in spiral vase mode', hints: ['Vase mode needs one closed outline per layer, no holes, no top.', 'Merge inner features into the single wall or print normally.'] },
  fit_clearance: { title: 'Clearance between mating parts too small', hints: ['Use std.fit("slide") or std.fit("print_in_place") gaps (>= 0.3-0.4 mm).'], notImplemented: true },
  load_across_layers: { title: 'Load pulls layers apart', hints: ['Rotate the part so layers run along the load path.', 'Add fillets in inner corners and ribs along the load.'], notImplemented: true },
};

export function hintsFor(code: string): string[] {
  return RULES[code]?.hints ?? [];
}
