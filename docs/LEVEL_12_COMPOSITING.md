# Level 12 — Advanced Compositing

**Source milestones: 10% (M1/10); Blender runtime/visual verification 0%; production readiness: No.**

## M1 — Native Bright/Contrast image grading
The typed `compositor.grade_preview/apply/release` tools connect one existing native image-output node to an *initially unconnected* existing Composite or Viewer output through a new Blender `CompositorNodeBrightContrast`. Bounded Bright (-100..100) and Contrast (-100..100) socket values and use_premultiply are written via real bpy RNA and verified with exact link readback. A stale graph revision blocks apply; release needs an unchanged scene, source, output, graded settings and links, then removes only the owned grade node and two links. Partial creation/link failures roll back the new node without rewriting foreign compositor links. This is source-level functionality: it does not load footage, process image pixels, execute compositing, or render a frame. Tool registry count 314. Next M2 will add a separate native lens-distortion / chromatic aberration pass.
