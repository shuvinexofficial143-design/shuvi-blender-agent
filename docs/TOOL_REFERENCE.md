# Tool reference (protocol 1)

The factory registers 203 typed tools. Main Shuvi sends a `Request` through `BlenderController`;
it never needs bpy names, operators or Python expressions. All inputs are JSON objects,
unknown fields fail, and each result carries the exact request and command IDs.

## Shared contracts

`Request`: `protocol_version=1`, nonempty `request_id` and `command_id` (128 characters
maximum each), `operation` (80 maximum), `payload`, and `timeout_ms` (1..120000).
Messages have a 1 MiB byte ceiling, 32 nesting levels, 65536 JSON nodes (including keys),
finite numbers and integers with at most 64 bits. Unicode must be valid; NUL is rejected.

`Transform`: `location`, `rotation_euler`, `scale`, each exactly three finite components.
Absolute component limits are 1000000 Blender units, 1000 radians and 10000 respectively.
Euler rotation is local XYZ; this does not assert evaluated world pose.

`ObjectTarget`: `object_id`, `expected_name`, `expected_revision` from a recent snapshot.
IDs are opaque and session-scoped. Revisions are 64-character SHA-256 fingerprints.
Names used to create data are nonempty and at most 63 UTF-8 bytes. Existing names fail;
automatic Blender suffix renaming is not accepted as success.

`PageQuery`: optional `offset` (0..10000), `limit` (1..100, default 25), `name_prefix`
(0..256 characters), `object_type` (optional, 32 characters), `expected_revision`
(optional, 64 characters). A nonzero offset requires `expected_revision`. Collection
queries reject the object_type filter. Changing filters starts a new pagination query;
clients should retain the filter, session ID and revision while continuing a page.

## Operations

| Tool | Payload fields | Safety | Readback / result |
| --- | --- | --- | --- |
| system.ping | none | read_only | `ready=true` after a roundtrip |
| system.capabilities | none | read_only | protocol/session/Blender version and operation catalog |
| scene.inspect | none | read_only | scene/file/render/frames, context, cursor, units, pivot, type counts, world presence, revision |
| rig.armature_inspect | object_id | read_only | bounded armature/bone hierarchy, pose transforms, pose-constraint metadata, mismatch diagnostics and deterministic rig_revision |
| rig.armature_create | name, transform, expected_scene_revision | mutation | create one empty local armature object/datablock with verified object/rig readback and cleanup on mismatch |
| rig.bone_create | target, expected_rig_revision, name, head, tail, use_deform (optional) | mutation | create one standalone root edit bone through a bounded edit-mode transition with exact readback and verified removal recovery |
| rig.bone_hierarchy_edit | target, expected_rig_revision, bone_name, new_name, parent_name, use_connect | mutation | fresh-revision-gated parent/connect/rename edit with cycle preflight, exact readback and full state recovery |
| rig.bone_symmetry_edit | target, expected_rig_revision, left_name, right_name, left_head, left_tail | mutation | explicit matching .L/.R pair coordinate edit mirrored across local X with exact dual-bone readback and recovery |
| rig.pose_bone_transform | target, expected_rig_revision, bone_name, location, rotation_mode, rotation, scale | mutation | set one explicit pose bone's bounded raw transform channels with quaternion normalization, exact readback and full pose-state recovery |
| rig.pose_bone_reset | target, expected_rig_revision, bone_name | mutation | reset one explicit pose bone to identity quaternion/location/scale with exact readback and recovery |
| rig.pose_constraint_create | target, expected_rig_revision, bone_name, constraint_name, constraint_type, influence, mute, plus type-specific bounded fields | mutation | create one unique LIMIT_ROTATION or same-armature IK pose constraint with exact state/count readback and verified removal recovery |
| rig.pose_constraint_remove | target, expected_rig_revision, bone_name, constraint_name, expected_constraint_type | mutation | remove only an explicit bounded final managed constraint with exact absence/count readback and append-safe recreation recovery |
| rig.mesh_armature_bind | mesh_target, armature_target, expected_rig_revision, modifier_name | mutation | bind one bounded unparented zero-group mesh to one explicit armature through a single managed ARMATURE modifier with exact target/settings readback and removal recovery |
| rig.mesh_armature_unbind | mesh_target, armature_target, expected_rig_revision, modifier_name | mutation | remove the exact sole managed ARMATURE modifier from a bounded zero-group mesh with exact absence readback and modifier recreation recovery |
| rig.mesh_weights_inspect | mesh_object_id, armature_object_id | read_only | inspect one managed M6-bound mesh/armature pair with exact group order, sparse weights, mismatch diagnostics and deterministic weight_revision |
| rig.vertex_group_weights_set | mesh_target, armature_target, expected_rig_revision, expected_weight_revision, bone_name, weights | mutation | fully replace one deform-bone-matched vertex group's bounded sparse weights with exact readback and recovery |
| rig.vertex_group_remove | mesh_target, armature_target, expected_rig_revision, expected_weight_revision, bone_name | mutation | remove only the final deform-bone-matched vertex group with exact absence/count readback and append-safe recreation recovery |
| rig.ik_fk_preview | object_id, upper_bone, middle_bone, end_bone, target_bone, constraint_name | read_only | validate one explicit upper→middle→end deform chain plus non-deforming control target and report managed IK/FK helper state/mode |
| rig.ik_fk_setup | target, expected_rig_revision, upper_bone, middle_bone, end_bone, target_bone, constraint_name, initial_mode | mutation | create one managed same-armature IK constraint with chain_count=3 and deterministic initial IK/FK mute state with rollback |
| rig.ik_fk_switch | target, expected_rig_revision, upper_bone, middle_bone, end_bone, target_bone, constraint_name, mode | mutation | switch only the managed IK helper mute state between IK and FK with exact readback/recovery |
| rig.recipe_catalog | none | read_only | deterministic versioned catalog of the fixed managed Level 6 recipes, exact schemas and catalog revision |
| rig.recipe_preview | recipe_id, target, expected_rig_revision, parameters | read_only | fresh-state preview of one fixed recipe using existing bounded constraint or IK/FK validation without mutation |
| rig.recipe_apply | recipe_id, target, expected_rig_revision, parameters | mutation | apply one fixed recipe through existing verified constraint/IK-FK mutation, exact readback and recovery paths |
| objects.list | PageQuery | read_only | sorted object snapshots, total, offset, next_offset, session_id, revision |
| collections.list | PageQuery without object_type | read_only | sorted names and object/child counts, total, offset, next_offset, session_id, revision |
| object.inspect | object_id | read_only | current-scene object snapshot and revision |
| mode.set | target, mode, expected_scene_revision | mutation | verified compatible Object/Edit/Sculpt/Pose/Paint context transition |
| shape.inspect | object_id | read_only | bounded CURVE/FONT data summary and shape readback |
| curve.create | name, points, cyclic, bevel_depth, transform, expected_scene_revision | mutation | one bounded 3D POLY spline, transform/membership and point readback |
| text.create | name, body, align_x, size, extrude, transform, expected_scene_revision | mutation | FONT body/alignment/size/extrusion and transform/membership readback |
| object.create | name, kind, transform, expected_scene_revision | mutation | bounded primitive; actual geometry counts/fingerprint, name/type/transform/membership |
| object.set_transform | target, transform | mutation | actual local transform and unchanged object identity/name |
| object.duplicate | target, name, transform | mutation | distinct identity/mesh, copied geometry/material slots, transform/membership |
| object.duplicate_linked | target, name, transform | mutation | distinct object identity with verified shared bounded mesh data |
| object.delete | target, expected_scene_revision | destructive | verifies target object absent from scene/data after guarded deletion |
| material.create_assign | target, name, base_color, metallic, roughness | mutation | actual Principled shader inputs, material slot and properties |
| material.slots_inspect | object_id | read_only | bounded slot order, face-user counts, face material indices and material_revision |
| material.slot_link | target, expected_material_revision, material_name | mutation | append existing material as a new verified slot |
| material.slot_reassign | target, expected_material_revision, slot_index, material_name | mutation | replace one existing slot reference with verified rollback |
| material.slot_duplicate | target, expected_material_revision, source_slot_index, new_material_name | mutation | duplicate material datablock from one slot and append verified independent slot |
| material.slot_remove | target, expected_material_revision, slot_index | mutation | conservatively remove only unused final slot |
| material.face_assign | target, expected_material_revision, slot_index, face_indices | mutation | assign explicit bounded faces to one existing slot with rollback |
| material.shader_inspect | material_name | read_only | bounded Principled values, managed node/link topology, PBR bindings and shader_revision |
| material.principled_set | material_name, expected_shader_revision, settings | mutation | typed Principled/Normal Map/Bump settings with unmanaged-link protection and verified managed-graph recovery |
| material.pbr_texture_assign | material_name, expected_shader_revision, channel, image_name | mutation | bind existing local image to allowlisted PBR channel with enforced color-space semantics and bounded wiring |
| material.pbr_texture_clear | material_name, expected_shader_revision, channel | mutation | remove only one Shuvi-managed PBR texture node/link set with verified recovery |
| texture.image_inspect | image_name | read_only | bounded existing local image metadata, tiled/packed summary and image_revision without exposing filepath |
| texture.udim_plan | object_id, uv_layer_name | read_only | source-only per-face UDIM tile planning with split/out-of-range diagnostics |
| texture.channel_qa | material_name | read_only | managed PBR image/colorspace/link and normal-chain QA with PASS/REVIEW/BLOCKED |
| texture.bake_prep | object_id, material_name, uv_layer_name, channels, texture_size | read_only | source-only UV/material/channel/UDIM bake readiness; never executes bake |
| texture.consistency_qa | material_name | read_only | managed image size/reuse/channel consistency diagnostics |
| texture.recovery_snapshot | material_name | read_only | bounded Shuvi-managed Principled/auxiliary/PBR state plus recovery revision |
| texture.recovery_restore | material_name, expected_shader_revision, recovery_revision, state | mutation | rebuild verified managed Level 4 material state with rollback to immediate pre-call state |
| texture.asset_qa | object_id, material_name, uv_layer_name | read_only | aggregate Level 4 UV/material/texture structural QA |
| texture.workflow_preview | object_id, material_name, uv_layer_name | read_only | fixed ten-stage non-mutating Level 4 workflow composition |
| texture.level4_acceptance | object_id, material_name, uv_layer_name | read_only | eight-check source/fake-adapter Level 4 acceptance with runtime-required boundary |
| geometry_nodes.tree_inspect | group_name | read_only | bounded GeometryNodeTree interface/node/socket/link/nested-group snapshot plus group_revision |
| geometry_nodes.group_create | group_name | mutation | create one empty local GeometryNodeTree and verify bounded readback |
| geometry_nodes.node_add | group_name, expected_group_revision, node_type, node_name, location (optional) | mutation | add one allowlisted Geometry node with deterministic/requested bounded placement and rollback |
| geometry_nodes.node_remove | group_name, expected_group_revision, node_name | mutation | remove one allowlisted Geometry node; capture incident links and verify full node/link recovery on rollback |
| geometry_nodes.node_set_input | group_name, expected_group_revision, node_name, socket_name, value | mutation | edit one allowlisted unlinked typed socket default with exact readback and rollback |
| geometry_nodes.link_add | group_name, expected_group_revision, from_node_name, from_socket_identifier, to_node_name, to_socket_identifier | mutation | add one exact typed acyclic link between allowlisted nodes with socket/type/input-limit validation and rollback |
| geometry_nodes.link_remove | group_name, expected_group_revision, from_node_name, from_socket_identifier, to_node_name, to_socket_identifier | mutation | remove one exact typed link by node/socket identifiers with verified restoration rollback |
| geometry_nodes.modifier_inspect | object_id | read_only | inspect bounded NODES modifiers, bound local GeometryNodeTree metadata and group revisions plus binding_revision |
| geometry_nodes.modifier_bind | target, group_name, expected_group_revision, modifier_name | mutation | create one bounded NODES modifier and bind it to one fresh local GeometryNodeTree with exact object/group readback and rollback |
| geometry_nodes.modifier_remove | target, group_name, expected_group_revision, modifier_name | mutation | remove one exact NODES modifier/group binding with stack-position/flag restoration on rollback |
| geometry_nodes.primitive_preview | recipe, prefix, parameters | read_only | deterministic source-only CUBE / ICO_SPHERE / TWIN_CUBE graph plan with output/interface intent and primitive_revision |
| geometry_nodes.primitive_apply | group_name, expected_group_revision, recipe, prefix, parameters | mutation | apply one exact bounded primitive recipe to an empty local GeometryNodeTree with internal Group Output/interface and verified rollback |
| geometry_nodes.primitive_clear | group_name, expected_group_revision, recipe, prefix, parameters | mutation | clear only a graph that exactly matches the requested primitive recipe and rebuild it on known verification failure |
| geometry_nodes.field_preview | workflow, prefix, parameters | read_only | deterministic source-only INDEX/POSITION/NORMAL → named-attribute workflow plan with attribute metadata and field_workflow_revision |
| geometry_nodes.field_apply | group_name, expected_group_revision, workflow, prefix, parameters | mutation | build one exact bounded field-to-Store-Named-Attribute graph in an empty local GeometryNodeTree with verified rollback |
| geometry_nodes.field_clear | group_name, expected_group_revision, workflow, prefix, parameters | mutation | clear only an exact managed field workflow graph and rebuild it on known verification failure |
| geometry_nodes.scatter_preview | recipe, prefix, parameters | read_only | deterministic source-only CUBE_SCATTER / ICO_SPHERE_SCATTER plan with bounded point resolution, estimated instance count and scatter_revision |
| geometry_nodes.scatter_apply | group_name, expected_group_revision, recipe, prefix, parameters | mutation | build one exact bounded Instance on Points graph in an empty local GeometryNodeTree with verified rollback |
| geometry_nodes.scatter_clear | group_name, expected_group_revision, recipe, prefix, parameters | mutation | clear only an exact managed scatter graph and rebuild it on known verification failure |
| geometry_nodes.architecture_preview | recipe, prefix, parameters | read_only | deterministic source-only MODULAR_WALL / BLOCK_GRID plan with bounded module count and architecture_revision |
| geometry_nodes.architecture_apply | group_name, expected_group_revision, recipe, prefix, parameters | mutation | build one exact bounded Cube→Transform→Join→Output architecture graph in an empty local GeometryNodeTree with verified rollback |
| geometry_nodes.architecture_clear | group_name, expected_group_revision, recipe, prefix, parameters | mutation | clear only an exact managed architecture graph and rebuild it on known verification failure |
| geometry_nodes.recipe_catalog | none | read_only | deterministic versioned catalog of 10 managed Geometry Nodes recipe IDs, parameter schemas, compatibility markers and catalog_revision |
| geometry_nodes.recipe_preview | recipe_id, prefix, parameters | read_only | validate one managed recipe ID against its bounded family schema and route preview through the existing verified family implementation |
| geometry_nodes.recipe_apply | recipe_id, group_name, expected_group_revision, prefix, parameters | mutation | route one managed recipe mutation through its existing bounded family apply path while preserving fresh-state/readback/rollback evidence |
| geometry_nodes.recipe_clear | recipe_id, group_name, expected_group_revision, prefix, parameters | mutation | clear one exact managed recipe through its existing family clear path while preserving verified recovery evidence |
| geometry_nodes.workflow_preview | recipe_id, prefix, parameters | read_only | fixed nine-stage non-mutating Level 5 QA/recovery/acceptance composition with direct-family preview equivalence and explicit runtime boundary |
| geometry_nodes.level5_acceptance | recipe_id, prefix, parameters | read_only | seven-check source/fake-bpy Level 5 acceptance report; real Blender runtime remains unverified |
| device.create | name, kind, transform, expected_scene_revision, settings | mutation | actual camera/light properties, transform/membership and active-camera state |
| device.update | target, settings | mutation | bounded camera/light setting patch and active-camera readback |
| modifier.add | target, name, kind, settings | mutation | actual newly added modifier settings |
| collection.create | name, expected_scene_revision, target (or null) | mutation | new collection's root link and optional object link |
| asset.mark | target, description | mutation | new asset mark and actual description |
| animation.set_range | start, end, expected_scene_revision | mutation | actual frame bounds |
| animation.set_frame | frame, expected_scene_revision | mutation | actual current frame |
| animation.insert_keyframe | target, frame, transform, interpolation | mutation | actual nine keyed transform values, frame and interpolation |
| render.configure | width, height, samples, expected_scene_revision | mutation | actual CPU Cycles/PNG/RGBA/8-bit/single-thread settings |
| render.execute | name (.png), expected_scene_revision | render | output size/hash, bounded PNG structure, dimensions and pixels decoded for structural validation |
| file.checkpoint | name (.blend), expected_scene_revision | file_write | output size/hash/uncompressed header and unchanged active source path |
| file.open_checkpoint | name (.blend), expected_scene_revision | destructive | opens only verified workspace checkpoint, rotates session/object identities, verifies loaded filepath |
| mesh.inspect | object_id | read_only | indexed vertices/faces and separate geometry_revision |
| mesh.topology_inspect | object_id | read_only | bounded derived edges, boundary/non-manifold edges and face adjacency |
| mesh.create | name, geometry, transform, expected_scene_revision | mutation | actual indexed geometry and object transform/membership |
| mesh.translate_vertices | target, expected_geometry_revision, indices, delta | mutation | actual complete bounded geometry; untouched indices/faces compared too |
| mesh.extrude_face | target, expected_geometry_revision, face_index, offset | mutation | exact rebuilt vertices/faces for one bounded single-face extrusion |
| mesh.transform_elements | target, expected_geometry_revision, domain, indices, translation, rotation_euler, scale, pivot | mutation | exact full-geometry readback plus affected vertex set |
| mesh.merge_vertices | target, expected_geometry_revision, indices, mode | mutation | compacted vertices/faces plus deterministic merged vertex index |
| mesh.dissolve_edge | target, expected_geometry_revision, edge_index | mutation | two-face edge dissolve into one verified simple polygon |
| mesh.extrude_region | target, expected_geometry_revision, face_indices, offset | mutation | connected-region cap/side-wall rebuild with full geometry readback |
| mesh.inset_face | target, expected_geometry_revision, face_index, factor | mutation | one inner cap plus verified quad ring |
| mesh.bevel_boundary_edge | target, expected_geometry_revision, edge_index, factor | mutation | conservative boundary-edge chamfer strip and rebuilt source polygon |
| mesh.subdivide_edge | target, expected_geometry_revision, edge_index, factor | mutation | one interpolated edge vertex inserted into all bounded edge-user polygon cycles |
| mesh.loop_cut_quad_strip | target, expected_geometry_revision, edge_index, factor | mutation | bounded all-quad strip discovery, one split vertex per ring edge and verified quad split |
| mesh.bridge_boundary_loops | target, expected_geometry_revision, loop_a, loop_b | mutation | equal explicit boundary loops connected by one verified quad per segment |
| mesh.fill_boundary_loop | target, expected_geometry_revision, vertex_indices | mutation | one verified polygon face across an explicit existing boundary loop |
| mesh.shading_inspect | object_id | read_only | bounded source face normals/areas, smoothing state and topology/shading diagnostics |
| mesh.set_face_smoothing | target, expected_geometry_revision, expected_shading_revision, face_indices, smooth | mutation | exact per-face smooth flags with unchanged bounded geometry |
| mesh.orient_faces_consistently | target, expected_geometry_revision, expected_shading_revision | mutation | manifold-connected winding consistency with preserved smooth flags |
| mesh.repair_inspect | object_id, distance, area_epsilon | read_only | bounded near-duplicate/duplicate/degenerate/loose/component repair diagnostics |
| mesh.merge_by_distance | target, expected_geometry_revision, distance | mutation | deterministic proximity merge, index compaction and collapsed/duplicate face cleanup |
| mesh.cleanup_faces | target, expected_geometry_revision, area_epsilon, remove_duplicate_faces | mutation | bounded degenerate/duplicate face removal with smooth-state preservation |
| mesh.remove_loose_vertices | target, expected_geometry_revision | mutation | compact unreferenced vertices while preserving polygon order and smoothing |
| mesh.retopology_inspect | object_id | read_only | bounded valence, pole, boundary, tri/quad/ngon and quad-ratio diagnostics |
| mesh.retopology_projection_inspect | source_id, target_id, vertex_indices, max_distance | read_only | bounded nearest target triangle points/normals/distances for explicit source vertices |
| mesh.retopology_project | source, target, expected_source_geometry_revision, expected_target_geometry_revision, vertex_indices, max_distance, offset | mutation | verified nearest-surface base-mesh projection with normal offset and coordinate rollback |
| mesh.retopology_relax | target, expected_geometry_revision, vertex_indices, factor, iterations, preserve_boundary | mutation | bounded synchronous one-ring relax with optional boundary preservation |
| modifier.shrinkwrap_add | source, target, expected_stack_revision, name, wrap_method, wrap_mode, offset | mutation | verified typed non-destructive Shrinkwrap modifier with explicit target identity |
| modifier.stack_diagnose | object_id | read_only | bounded stack type/order/reference/visibility diagnostics plus diagnostic revision |
| modifier.stack_compose | target, expected_stack_revision, entries | mutation | atomic append of 1..8 typed BEVEL/SUBSURF/SOLIDIFY entries with full-stack verification |
| modifier.recipe_preview | recipe, prefix, parameters | read_only | deterministic allowlisted modifier recipe expansion and recipe revision |
| modifier.recipe_apply | target, expected_stack_revision, recipe, prefix, parameters | mutation | transactional allowlisted preset composition with collision/capacity checks and rollback |
| modeling.qa_inspect | object_id, distance, area_epsilon | read_only | aggregate structural modeling QA across repair/shading/retopology/modifier state plus qa_revision |
| modeling.workflow_preview | object_id, workflow, distance, area_epsilon | read_only | no-mutation preview of allowlisted repair workflow triggers and workflow revision |
| modeling.workflow_apply | target, expected_geometry_revision, expected_qa_revision, workflow, distance, area_epsilon | mutation | transactional verified repair composition with full initial-geometry/smoothing recovery evidence |
| sculpt.inspect | object_id | read_only | bounded base-mesh sculpt readiness, valence, boundary, degenerate-face and vertex-normal diagnostics |
| sculpt.brush_displace | target, expected_geometry_revision, center, radius, strength, falloff | mutation | radial area-weighted-normal displacement with ≤512 affected vertices and coordinate rollback |
| sculpt.brush_smooth | target, expected_geometry_revision, center, radius, strength, falloff, iterations, preserve_boundary | mutation | bounded synchronous radial one-ring smoothing with optional boundary preservation and rollback |
| sculpt.brush_inflate | target, expected_geometry_revision, center, radius, strength, falloff | mutation | radius-relative normal inflation/deflation with normalized signed strength and rollback |
| sculpt.brush_flatten | target, expected_geometry_revision, center, radius, strength, falloff | mutation | weighted local tangent-plane flattening with complete geometry verification |
| sculpt.brush_pinch | target, expected_geometry_revision, center, radius, strength, falloff | mutation | signed tangent-plane pinch/expand around brush center |
| sculpt.brush_grab | target, expected_geometry_revision, center, radius, delta, falloff | mutation | explicit local-space weighted grab translation without normal dependency |
| sculpt.brush_crease | target, expected_geometry_revision, center, radius, pinch, depth, falloff | mutation | combined tangent pinch plus normal indentation crease foundation |
| sculpt.region_preview | object_id, center, radius, falloff, axis, side, symmetry, plane_epsilon, require_symmetry_pairs, mask | read_only | bounded side-aware radial region preview with sparse mask weights and symmetry partner evidence |
| sculpt.brush_displace_controlled | target, expected_geometry_revision, center, radius, falloff, axis, side, symmetry, plane_epsilon, require_symmetry_pairs, mask, strength | mutation | masked/side-filtered normal displacement with optional mirrored local-axis deformation |
| sculpt.brush_grab_controlled | target, expected_geometry_revision, center, radius, falloff, axis, side, symmetry, plane_epsilon, require_symmetry_pairs, mask, delta | mutation | masked/side-filtered explicit grab with optional mirrored local-axis delta |
| sculpt.detail_plan | object_id, viewport_level, render_level | read_only | bounded SUBSURF detail-cost estimate plus explicit real-Multires runtime boundary |
| sculpt.subdivision_setup | target, expected_stack_revision, name, viewport_level, render_level | mutation | verified empty-stack SUBSURF sculpt-detail preview setup |
| sculpt.subdivision_set_levels | target, expected_stack_revision, name, viewport_level, render_level | mutation | verified typed SUBSURF detail-level update |
| sculpt.voxel_plan | object_id, voxel_size | read_only | bounded local-space voxel grid/cell estimate; planning only |
| sculpt.voxel_target_density | object_id, longest_axis_voxels | read_only | derive bounded recommended voxel size from requested longest-axis density |
| sculpt.surface_snapshot | object_id | read_only | deterministic local bounds/centroid/area/edge-length preservation baseline |
| sculpt.surface_anchor_plan | object_id, max_anchors | read_only | deterministic extrema/centroid-near surface anchor evidence for later remesh comparison |
| uv.inspect | object_id | read_only | bounded UV-layer/missing-UV, overlap/stretch/island and seam diagnostics with dedicated uv_revision |
| uv.seam_set | target, expected_geometry_revision, expected_uv_revision, edge_indices, seam | mutation | explicit 1..512 edge seam flags with full bounded seam readback and verified rollback |
| uv.unwrap_plan | object_id, projection | read_only | bounded XY/XZ/YZ deterministic planar UV projection preview; no Blender unwrap claim |
| uv.unwrap_apply | target, expected_geometry_revision, expected_uv_revision, layer_name, projection | mutation | create/replace one named planar UV layer with complete layer-state verification and recovery |
| uv.island_transform | target, expected_geometry_revision, expected_uv_revision, layer_name, face_indices, translation, scale | mutation | exact detected UV-island scale/translate with intended-coordinate readback and rollback |
| uv.pack_plan | object_id, layer_name, margin | read_only | deterministic bounded grid-pack preview for current UV islands; source-only |
| uv.pack_apply | target, expected_geometry_revision, expected_uv_revision, layer_name, margin | mutation | deterministic grid pack with exact target-layer revision verification and full UV rollback |
| uv.texel_density_inspect | object_id, layer_name, texture_size | read_only | bounded per-face/min/median/max source texel-density estimates |
| uv.texel_density_plan | object_id, layer_name, texture_size, target_density | read_only | uniform UV scale planning toward a target median density; no mutation claim |
| character.proportion_guide | preset, height, origin | read_only | deterministic local-space ADULT_NEUTRAL/HEROIC/STYLIZED modeling proportion reference |
| character.blockout_plan | preset, height, origin | read_only | planning-only symmetric primitive layout for head/torso/pelvis/arms/legs |
| character.landmark_fit | object_id, preset | read_only | fit proportion guide targets to deterministic nearest base-mesh vertex candidates |
| character.face_guide | object_id, front_direction | read_only | normalized 14-point facial reference from bounded local head bounds |
| character.face_landmark_fit | object_id, front_direction, max_normalized_distance | read_only | nearest-vertex facial candidate mapping with explicit review threshold |
| character.face_region_plan | object_id, front_direction | read_only | six deterministic head/face sculpt-region centers and radii |
| character.face_symmetry_audit | object_id, front_direction, tolerance | read_only | local-X candidate landmark symmetry and centerline drift audit |
| character.body_region_plan | object_id, preset | read_only | fit preset to mesh bounds and emit 17 torso/limb/hand/foot sculpt planning regions |
| character.limb_guide | preset, height, origin, side, limb_kind | read_only | side-aware ARM/LEG landmark reference with shoulder/elbow/wrist/hand or hip/knee/ankle/foot |
| character.extremity_guide | kind, side, anchor, length | read_only | explicit HAND or FOOT landmark reference including digit/toe tips |
| character.body_symmetry_audit | object_id, tolerance | read_only | bounded local-X base-mesh symmetry partner audit with unmatched/collision evidence |
| character.sculpt_qa | object_id, symmetry_tolerance | read_only | aggregate structural sculpt-readiness + body symmetry QA with deterministic qa revision |
| character.sculpt_recipe_preview | recipe, intensity | read_only | allowlisted BODY/FACE/HAND_FOOT sculpt workflow preview using existing typed tools |
| character.sculpt_recovery_snapshot | object_id, vertex_indices | read_only | bounded 1..512 vertex coordinate-patch snapshot plus topology revision |
| character.sculpt_recovery_restore | target, expected_geometry_revision, expected_topology_revision, entries | mutation | verified 1..512 coordinate-patch restore with topology-drift denial and rollback |
| character.workflow_preview | object_id, preset, front_direction, symmetry_tolerance, face_fit_threshold, recipe, intensity | read_only | 12-stage end-to-end Level 3 composition preview; never auto-executes mutation |
| character.level3_acceptance | object_id, preset, front_direction, symmetry_tolerance, face_fit_threshold, recipe, intensity | read_only | aggregate eight-check Level 3 source acceptance with explicit runtime/production boundary |
| mesh.apply_object_transform | target, expected_geometry_revision | mutation | complete local scale/XYZ rotation/location baked into mesh; object channels reset |
| origin.to_centroid | target, expected_geometry_revision | mutation | arithmetic local vertex centroid becomes origin with verified geometry/object offset |

## Operation limits and policy

- Read-only operations are enabled by default. Mutation requires `allow_mutations`.
  Destructive operations require both `allow_mutations` and `allow_destructive`.
  Checkpoints require `allow_file_writes` and an output workspace. Rendering requires
  mutations, file writes, rendering permission, an output workspace and prior CPU settings.
  `file.open_checkpoint` additionally requires a configured OutputWorkspace and accepts only
  a verified regular `.blend` inside that confined root. The host checks its own safety
  allowlist and rejects catalog classifications that disagree with it.
- Scene work: at most 10000 objects, 10000 collections, 10000 allocated session identities,
  and 100000 nested inspection work units per scene request. Revisions scan current bounded
  scene metadata and collection relationships; snapshots stream rather than accumulate.
  Object pages have a 512 KiB content budget; reduce limit when denied. No persistent cache.
- Object snapshots expose at most 64 modifiers, material slots and collection memberships;
  animation exposes at most 64 channels, 256 points per channel and 1024 total points.
  Truncation is explicit and truncated snapshots cannot authorize mutation. Names are
  bounded to 256 characters; metadata strings to 1000; file/render paths to 4096.
  Revisions cover inspected metadata, not every Blender property or all mesh geometry.
- Mesh operations and duplicate input: 4096 vertices, 4096 faces, 32768 total face indices.
  Created faces have 3..32 distinct valid vertex indices. Translation selects 1..256 unique
  indices and delta components in -1000..1000; every result coordinate stays within
  -1000000..1000000. Translation requires unshared editable mesh without shapes/modifiers.
  Complete transform baking and origin-to-centroid require a fresh geometry revision,
  unparented local unshared mesh data, XYZ Euler rotation mode, no shape keys/modifiers,
  and the normal Object-mode/no-animation/no-constraint guard. Duplicates reject shape keys
  and modifiers and require an unparented mesh or empty.
- Modifiers require no existing modifier stack and the bounded mesh above. BEVEL has width
  0..100 and segments 1..8; SUBSURF has levels/render_levels 0..2; SOLIDIFY thickness -100..100.
  These source bounds do not establish a hard Blender CPU/memory ceiling.
- Material color is RGBA in 0..1; metallic/roughness are 0..1. Material assignment requires
  local unshared mesh data and fewer than 64 slots. Camera settings are lens 1..500,
  clip_start 0.0001..1000, clip_end 0.001..1000000 greater than start, boolean make_active.
  Light kinds POINT/SUN/SPOT/AREA accept energy 0..1000000 and RGB in 0..1. device.update
  accepts only the fields appropriate to the target kind and verifies the resulting state.
- Curves create exactly one 3D POLY spline with 2..256 points, coordinates within
  -1000000..1000000, boolean cyclic state and bevel depth 0..100. Text body is 1..1000
  characters; align_x is LEFT/CENTER/RIGHT/JUSTIFY/FLUSH, size .0001..1000 and extrude
  0..100. Curve/Text creation uses direct data APIs, not editor operators.
- Collections have at most 64 root children; adding an object membership requires fewer
  than 64 existing memberships. Asset descriptions are 0..1000 characters; replacement
  metadata is denied. Objects must be editable/local, in object mode, and unconstrained;
  generic object tools reject animation. Keyframes permit only session-owned unshared
  actions, at most 64 unique frames, no frame overwrite, and LINEAR/BEZIER/CONSTANT.
- Timeline frames are 1..100000; configured range span at most 10000. Frame selection must
  fall inside that range. Rendering is single-frame CPU only, 16..512 pixels each dimension,
  1..16 samples, one thread. A deadline cannot interrupt a running bpy call.
- Outputs use plain filenames at most 128 characters, exact .png/.blend suffixes, exclusive
  reservation and no overwrite. Traversal, absolute/UNC paths, alternate streams, reserved
  Windows device names, reparse points and hard links are denied. Roots are pinned to
  filesystem identity. PNG files are at most 4 MiB; BLEND files 128 MiB with streamed hashing.
  Header validation does not prove that a .blend file can be reopened or recovered.

## Results and catalog

Read-only success is `succeeded`; mutations are `verified` only with nonempty expected
state matching actual readback. Numeric comparisons use absolute tolerance 1e-5 and
relative tolerance 1e-6; copied geometry fingerprints require identical stored coordinates.
Adapter mutation results include before/after where available and verification evidence.
Creation mismatches remove newly allocated data; generic edits are not transactions.
Errors/exceptions can leave partial state. Failed verification never authorizes retry.

`Result` includes `protocol_version`, `request_id`, `command_id`, `status`, `data`, `error`,
`verification`. An error has `code`, sanitized public `message`, and boolean `retryable`.
Codes: invalid_request, unsupported_operation, protocol_mismatch, not_found,
ambiguous_target, stale_state, safety_denied, timeout, transport_error, execution_error,
verification_failed, blender_not_found. No traceback or arbitrary exception text is sent.
Error messages are nonempty, valid Unicode and at most 512 characters. Mutation exceptions
after dispatch report outcome=unknown and require inspection before retry.

Catalog entries expose name, classification, enabled, payload_fields (null for custom
parsers), verification_required, runtime_required, file_write_permission_required and
render_permission_required. Enabled reports session policy, not scene compatibility or
runtime verification. All factory tools except the generic ping adapter require Blender
state at execution. Normal host imports have no bpy dependency.

See [client contract](CLIENT.md), [source audit](SOURCE_AUDIT.md) and
[future runtime acceptance](RUNTIME_ACCEPTANCE.md). Runtime verification remains **0%**;
production ready: **no**.

Level 1 primitive expansion: `object.create.kind` also accepts `UV_SPHERE`,
`ICOSPHERE`, `CYLINDER`, `CONE`, `CIRCLE` (filled), `GRID`, `TORUS`.
See [Level 1 control](LEVEL_1_CONTROL.md) for fixed geometry bounds.

Level 1 additions (mutations require normal policy and fresh state):
- `scene.rename`: name, expected_scene_revision.
- `scene.set_units`: bounded system/scale_length/length_unit patch plus scene revision.
- `cursor.inspect` / `cursor.set`: read or verify the 3D cursor location.
- `mode.inspect`: bounded current mode + active-object summary.
- `pivot.inspect` / `pivot.set`: transform pivot with an allowlisted Blender enum.
- `object.rename`: target, name.
- `object.set_properties`: allowlisted display/color/pass-index/transform-lock/empty-display
  group only; no arbitrary property setter.
- `object.patch_transform`: nonempty partial location/scale/XYZ Euler or unit WXYZ
  quaternion; omitted channels are preserved.
- `object.set_visibility`: hide_viewport, hide_render and view-layer hidden state.
- `selection.inspect` / `selection.set`: bounded selected IDs and active object.
- `hierarchy.inspect` / `hierarchy.set_parent`: parent/children readback, cycle rejection,
  unparent via null parent, and optional keep-world.
- `origin.inspect`: local and world object-origin locations.
- `collection.inspect`, `collection.rename`, `collection.link_object`,
  `collection.unlink_object`, `collection.move_object`, `collection.create_child`:
  bounded collection management with stale-state guards and orphan prevention.
- `object.duplicate_linked`: independent object sharing the source mesh datablock, with
  geometry/material/readback checks and conservative mesh limits.
- `shape.inspect`, `curve.create`, `text.create`: bounded direct-data Curve/Text
  inspection and creation; no arbitrary bpy/operator execution.
- `device.update`: bounded camera lens/clip/active-state or light energy/color updates.
- `mesh.apply_object_transform`: bake the complete supported local object transform into
  bounded mesh vertices, then verify reset object transform plus resulting geometry.
- `origin.to_centroid`: move the origin to the arithmetic mesh-vertex centroid while
  preserving supported world geometry through a verified vertex/object offset.


## Level 1 completion additions

- `mode.set` supports the current Level 1 allowlist: OBJECT for supported targets; EDIT for
  mesh/curve/font/surface/meta/lattice/armature; SCULPT/VERTEX_PAINT/WEIGHT_PAINT/
  TEXTURE_PAINT for mesh; POSE for armature. The target must already be selected and active.
  Non-Object entry is only from Object mode. Actual Blender context semantics remain subject
  to runtime acceptance.
- `object.delete` is destructive and source-verified by absence readback. It refuses linked,
  overridden/read-only objects and refuses deleting a parent while scene children still
  reference it. It does not automatically remove orphan data blocks.
- `file.open_checkpoint` is a confined destructive project replacement. Before opening, the
  file is structurally verified as a bounded regular BLEND output in the configured workspace.
  A successful open invalidates all prior session object IDs by rotating the inspector session.
- With these additions the current Level 1 **source roadmap is 100% implemented**. Real Blender
  runtime verification remains a separate acceptance phase and is not implied by source CI.


## Level 2 modeling additions

Current Level 2 source progress: **100%**.

- `mesh.topology_inspect` derives a deterministic canonical edge set from bounded polygon
  loops, reports boundary edges, non-manifold edges and two-face adjacency. Derived topology
  is capped at 8192 unique edges in addition to the existing 4096-vertex/4096-face/32768-loop
  geometry bounds.
- `mesh.extrude_face` performs one explicitly indexed face extrusion using a bounded local
  offset. It requires Object mode, fresh object + geometry revisions, editable local unshared
  mesh data, no shape keys and no modifier stack. The resulting vertex/face/loop counts are
  preflighted before mutation. The tool rebuilds the bounded mesh through direct data APIs,
  reads the entire geometry back, verifies the new cap and side quads, and restores captured
  geometry if verification fails.
- This is the first professional-modeling milestone, not Blender's complete extrusion family.
  Multi-face region extrusion, inset, bevel, loop cut, bridge, merge/dissolve, normals and
  topology-repair workflows remain later Level 2 milestones.

See [Level 2 modeling](LEVEL_2_MODELING.md) for the ten-milestone roadmap.


### Level 2 milestone 2 limits

- `mesh.transform_elements` accepts domain VERTEX/EDGE/FACE and 1..256 unique element
  indices. EDGE indices refer to the canonical sorted edge list from
  `mesh.topology_inspect`; FACE and VERTEX indices refer to current bounded geometry.
  Translation/rotation/scale are applied around the supplied local-space pivot. Result
  coordinates must remain within the normal ±1000000 mesh coordinate bound.
- `mesh.merge_vertices` accepts 2..64 unique vertex indices and placement CENTER/FIRST/LAST.
  Rebuild is denied when material slots, vertex groups, UV layers or color attributes are
  present because those layers are not preserved by this foundation.
- `mesh.dissolve_edge` accepts one canonical edge index and only edges with exactly two face
  users. The merged face must be simple and contain at most 32 unique vertices.
- All milestone 2 mutations require editable local unshared mesh data, fresh geometry state,
  no shape keys/modifiers, Object mode and normal object mutation safety guards. Verification
  compares complete bounded geometry; failed verification triggers bounded rollback.


### Level 2 milestone 3 limits

- `mesh.extrude_region` accepts 1..64 unique face indices, requires a single edge-connected
  selected region, rejects selected non-manifold edges and rejects a closed region without a
  boundary. Unique selected vertices are duplicated once; side quads are created only for
  region boundary edges.
- `mesh.inset_face` accepts one face and factor 0.001..0.95. It is a center-interpolation
  inset foundation with one new inner vertex per source face vertex and one surrounding quad
  per source edge.
- `mesh.bevel_boundary_edge` accepts one canonical edge index and factor 0.001..0.49.
  The edge must have exactly one polygon user. This milestone intentionally does not bevel
  shared/manifold edges.
- Milestone 3 topology rebuilds keep the Milestone 2 metadata guard: material slots, vertex
  groups, UV layers and color attributes cause a safety denial until data-layer preservation
  is implemented intentionally.


### Level 2 milestone 4 limits

- `mesh.subdivide_edge` accepts one canonical edge index and factor 0.001..0.999. The edge
  must have one or two polygon users. One interpolated vertex is inserted into every polygon
  cycle using that edge; any resulting polygon above 32 vertices is denied.
- `mesh.loop_cut_quad_strip` accepts one seed edge and factor 0.001..0.999. Discovery walks
  only through quads by opposite edges, rejects non-manifold crossings, and caps the discovered
  ring at 256 edges. Every affected quad is replaced by two verified quads.
- `mesh.bridge_boundary_loops` accepts two disjoint equal-size loops of 3..64 vertices.
  Consecutive loop vertices must already form boundary edges with exactly one polygon user.
  Corresponding segments create one quad each; automatic twist/alignment solving is not part
  of this foundation.
- `mesh.fill_boundary_loop` accepts 3..32 unique vertices following an existing boundary
  cycle and adds exactly one polygon. It rejects a polygon with the same vertex set when one
  already exists.
- All Milestone 4 topology rebuilds retain the no-material/UV/color/vertex-group metadata
  guard until those data layers can be intentionally preserved.


### Level 2 milestone 5 limits

- `mesh.shading_inspect` computes source face normals from triangle-fan area vectors and
  reports triangle-fan area, degenerate/ambiguous-normal faces, isolated vertices, boundary/
  non-manifold edges, winding conflicts and per-face `use_smooth` state. These are base-mesh
  diagnostics and do not claim evaluated custom/split normals.
- `mesh.set_face_smoothing` accepts 1..256 unique face indices and a boolean smooth state.
  Both geometry and shading revisions must be fresh. The complete smooth/flat face partition
  is read back; geometry revision must stay unchanged.
- `mesh.orient_faces_consistently` solves pairwise orientation constraints across edges with
  exactly two face users. More-than-two-user edges and contradictory constraints are denied.
  Components are made internally consistent but are not automatically oriented "outside".
  Smooth flags are preserved across the bounded topology rebuild.
- The orientation rebuild keeps the existing no-material/UV/color/vertex-group metadata guard.
  No custom normal layer editing, sharp-edge system, modifier-evaluated normal control or
  arbitrary normal operator is exposed in this milestone.


### Level 2 milestone 6 limits

- `modifier.stack_inspect` caps stack inspection at 16 entries and returns an ordered
  `stack_revision`. Supported typed readback covers BEVEL, SUBSURF, SOLIDIFY and BOOLEAN;
  arbitrary settings on unknown modifier types are not surfaced.
- `modifier.stack_add` appends BEVEL/SUBSURF/SOLIDIFY to an existing bounded stack using
  the allowlisted settings for that kind. Duplicate names and full stacks are denied.
- `modifier.boolean_add` requires distinct fresh mesh target/cutter objects, accepts
  DIFFERENCE/UNION/INTERSECT and EXACT/FAST, and verifies cutter identity/name plus ordered
  modifier state. It does not apply the Boolean result to permanent mesh topology.
- `modifier.update` accepts only allowlisted fields for the declared current modifier type,
  plus viewport/render visibility. Verification failure restores the captured patched values.
- `modifier.move` reorders one named stack entry to an existing index and verifies the
  complete ordered stack; verification failure restores the prior order.
- Hard-surface source CI verifies contracts/state transitions only. Actual Blender modifier
  evaluation and Boolean solver geometry remain runtime-unverified.


### Level 2 milestone 7 limits

- `mesh.repair_inspect` accepts distance 1e-9..100 and area epsilon 0..1000000. Spatial
  near-duplicate work is capped at 1,000,000 pair checks and 512 reported diagnostic groups.
  Duplicate polygons are matched independent of cycle rotation/reversal.
- `mesh.merge_by_distance` uses deterministic proximity clusters, compacts surviving
  vertices, removes faces collapsed below three unique vertices, and deduplicates polygons
  created by the merge. Surviving source face smoothing flags are preserved.
- `mesh.cleanup_faces` removes triangle-fan-area-degenerate faces and, when explicitly
  requested, later duplicate faces. It refuses to remove every polygon and rejects a no-op.
- `mesh.remove_loose_vertices` removes only vertices unused by every polygon, remaps all
  polygon indices, preserves per-face smooth state and rejects a no-op.
- All Milestone 7 mutations retain the no-material/UV/color/vertex-group metadata guard and
  deny shape keys/modifiers; failed verification restores captured geometry and smoothing.


### Level 2 milestone 8 limits

- `mesh.retopology_inspect` reports vertex valence, boundary vertices, isolated vertices,
  interior non-4-valence poles, tri/quad/ngon face partitions and quad ratio.
- Projection preview/mutation accepts 1..128 unique source vertices and caps
  source-vertex × target-triangle checks at 1,000,000. Projection targets currently require
  base triangle/quad faces and no shape keys/modifiers.
- Direct projection supports unparented XYZ source/target transforms with nonzero scale,
  computes nearest world-space triangle points, and converts them back to source local space.
  If any requested vertex exceeds max_distance, the mutation is denied before changing source
  coordinates.
- `mesh.retopology_relax` accepts factor 0.001..1 and 1..8 iterations. It performs synchronous
  one-ring averaging on the explicit selection and can hold boundary vertices fixed.
- `modifier.shrinkwrap_add` supports NEAREST_SURFACEPOINT/NEAREST_VERTEX and
  ON_SURFACE/ABOVE_SURFACE with offset -100..100. Existing `modifier.update` can patch typed
  Shrinkwrap method/mode/offset/visibility but cannot arbitrarily retarget the modifier.
- Real Blender evaluated Shrinkwrap/depsgraph behavior remains runtime-unverified.


### Level 2 milestone 9 limits

- `modifier.stack_diagnose` reports unsupported entries, disabled viewport/render states,
  missing BOOLEAN/SHRINKWRAP references, SUBSURF-before-BEVEL advisory pairs, type counts and
  a bounded complexity score. Diagnostics do not automatically mutate/reorder the stack.
- `modifier.stack_compose` accepts 1..8 unique named BEVEL/SUBSURF/SOLIDIFY specs using the
  existing typed settings for each kind. External-reference modifiers are excluded from this
  generic composition path and remain available through their dedicated tools.
- `modifier.recipe_preview` and `modifier.recipe_apply` currently support PANEL_SHELL,
  SUBDIV_BEVEL and HARD_SURFACE_TRIPLE. Each recipe has an exact parameter schema and
  deterministic generated modifier names based on a bounded prefix.
- Recipe/composition mutations require a fresh stack revision, preflight name collisions and
  the 16-entry total stack cap. Verification compares the complete ordered stack; failure
  removes all entries created by that transaction.
- These workflows compose modifier state only. They do not evaluate/apply modifier geometry,
  so real Blender solver/depsgraph behavior remains runtime-unverified.


### Level 2 milestone 10 limits

- `modeling.qa_inspect` combines bounded base-mesh repair/shading/retopology diagnostics with
  modifier-stack diagnostics. `qa_status` is a structural source classification only; it is
  not an artistic score or production-readiness certification.
- `modeling.workflow_preview` supports `CLEAN_BASE_MESH` and
  `CLEAN_ORIENT_BASE_MESH`. The preview lists triggers from current QA but later steps are
  intentionally re-evaluated after each verified mutation.
- `modeling.workflow_apply` requires a fresh ObjectTarget, geometry revision and QA revision.
  It conditionally composes merge-by-distance, face cleanup, loose-vertex removal and,
  for the orienting workflow, consistent face winding. No-op workflows are rejected.
- Before the first child mutation, the complete indexed mesh plus per-face smoothing is
  captured. Each child operation must independently verify readback. A later failure causes
  restoration of the original geometry/smoothing; a known failed result is returned only when
  that recovery is itself read back and verified.
- The final workflow readback requires zero near-duplicate groups, duplicate/degenerate faces,
  loose vertices and zero-length edges; the orienting workflow also requires zero winding
  conflicts.
- Existing rebuild guards remain in force, so shape keys/modifiers/material/UV/color/
  vertex-group data are never silently discarded by the workflow.
- The current Level 2 source roadmap is 100% complete. Real Blender runtime verification
  remains 0% until the separately authorized acceptance suite is actually executed.


## Level 3 sculpting foundation

Current Level 3 source progress: **100%**.

### Level 3 milestone 1 limits

- `sculpt.inspect` derives base-mesh sculpt-readiness signals from bounded indexed geometry:
  boundary vertices, non-manifold edges, degenerate faces, unresolved accumulated vertex
  normals and min/max/average vertex valence. The readiness flag is structural only and does
  not claim Blender Sculpt Mode/PBVH readiness.
- `sculpt.brush_displace` uses a local-space radial center, radius, signed strength and
  LINEAR/SMOOTH falloff. At most 512 selected vertices may be affected. Each valid selected
  vertex moves along its deterministic area-weighted base-mesh normal by
  `strength × falloff_weight`.
- `sculpt.brush_smooth` accepts strength 0.001..1.0 and 1..8 iterations. It performs
  synchronous one-ring averaging on the radial selection and can preserve boundary vertices.
- Sculpt foundation mutations require a fresh ObjectTarget and geometry revision, Object
  mode, editable local unshared base mesh, and no shape keys/modifier stack. They preserve
  topology and verify the complete bounded geometry after mutation.
- Verification failure restores all changed vertex coordinates and reads the mesh again through
  the ordinary bounded snapshot path.
- These are source-side deterministic sculpt-like base-mesh deformation tools. They do not
  invoke Blender's interactive Sculpt Mode brush engine, PBVH, Dyntopo, Multires, masks or
  face sets. Real Blender Level 3 runtime verification remains 0%.


### Level 3 milestone 2 limits

- `sculpt.brush_inflate` accepts normalized signed strength -1..1 and converts it to a
  radius-relative local displacement scale of `radius × 0.25 × strength` before falloff.
- `sculpt.brush_flatten` resolves a weighted regional brush normal and weighted selected
  centroid, then moves vertices toward that local tangent plane with strength 0.001..1.0.
- `sculpt.brush_pinch` accepts signed strength -1..1 and moves vertices along their tangent-
  plane radial component toward/away from the brush center.
- `sculpt.brush_grab` applies an explicit nonzero local delta (components ±1000) scaled by
  radial falloff and does not require a valid surface normal.
- `sculpt.brush_crease` combines tangent pinch 0..1 and indentation depth 0..100; at least
  one component must be nonzero.
- Normal-dependent brushes reject selections whose falloff-weighted accumulated base-mesh
  normal cannot be normalized safely.
- All expanded brushes inherit the 512-positive-weight selection cap, fresh object/geometry
  state, local unshared base-mesh guard, full indexed-geometry readback and coordinate rollback.
- These algorithms are deterministic base-mesh foundations only; they do not claim Blender
  interactive Sculpt Mode brush equivalence or runtime verification.


### Level 3 milestone 3 limits

- `sculpt.region_preview` accepts NONE/X/Y/Z axis controls, BOTH/POSITIVE/NEGATIVE side
  filtering, a bounded symmetry epsilon, strict optional pair requirement and up to 512 unique
  sparse mask entries. Mask value 0 means unmasked; 1 means fully protected.
- Symmetry requires X/Y/Z plus exactly one source side. Partner lookup mirrors source
  coordinates in object-local space, searches a bounded spatial grid and caps candidate checks
  at 1,000,000.
- If both sides of a symmetry pair have explicit mask values, the maximum mask value is used
  as the pair's effective protection so mirrored deformation cannot bypass the more-protected
  side.
- The complete changed set, including mirrored partners, is capped at 512 vertices.
- `sculpt.brush_displace_controlled` mirrors deformation deltas across the chosen local axis;
  self-paired symmetry-plane vertices are constrained back onto that plane.
- `sculpt.brush_grab_controlled` applies explicit local delta with the same mask/side layer;
  when mirrored, only the selected axis component changes sign.
- These are stateless request-side mask and symmetry controls. They do not create or read
  Blender Sculpt Mask/Face Set layers and do not claim Blender Sculpt Mode symmetry
  equivalence.


### Level 3 milestones 4–5 limits

- Sculpt detail levels are bounded to 0..3 and use a conservative source-side estimate of
  base faces × 4^level. Estimates above 250,000 faces are denied.
- `sculpt.subdivision_setup` requires an empty stack and creates only a typed SUBSURF preview;
  real Multires subdivision remains explicitly runtime-required.
- `sculpt.subdivision_set_levels` requires fresh stack state and an unchanged named SUBSURF
  entry; existing typed modifier rollback/readback behavior is reused.
- Voxel planning is local-space only, capped at 512 planned cells per axis and 16,777,216
  total estimated cells. It never executes Blender Voxel Remesh.
- `sculpt.surface_snapshot` records bounds, centroid, surface-area estimate, average unique
  edge length and topology counts as a preservation baseline.
- `sculpt.surface_anchor_plan` returns 4..32 deterministic extrema/centroid-near anchors with
  base positions/normals; future topology-changing runtime checks must use spatial proximity,
  not preserved vertex indices.
- Real Multires, Voxel Remesh, Dyntopo and evaluated subdivision behavior remain runtime
  unverified.


### Level 3 milestones 6–7 limits

- `character.proportion_guide` exposes ADULT_NEUTRAL, HEROIC and STYLIZED modeling-reference
  presets with explicit local X-left/right, Y-depth, Z-up convention. The preset values are
  artistic blockout references, not anatomical/medical truth.
- `character.blockout_plan` returns an 11-part planning-only primitive layout for head,
  torso, pelvis, bilateral upper/forearms and bilateral thigh/lower-leg masses. It creates
  no Blender objects.
- `character.landmark_fit` derives body-guide targets from current local mesh bounds and maps
  them to deterministic nearest base-mesh vertex candidates. The fit is read-only and capped
  by the existing 4096-vertex bounded geometry surface.
- `character.face_guide` requires nonzero X/Y/Z head bounds and explicit POSITIVE_Y or
  NEGATIVE_Y local front direction. It returns 14 facial reference points, centerline names
  and left/right pair definitions.
- `character.face_landmark_fit` reports per-landmark normalized candidate distance and an
  explicit rejection list against caller-supplied threshold 0.001..2.0; rejected candidates
  produce REVIEW rather than a false fit claim.
- `character.face_region_plan` returns planning-only eye/nose/mouth/chin-jaw/brow brush
  centers/radii derived from head width/height.
- `character.face_symmetry_audit` checks mirrored local-X pair error, Y/Z pair alignment and
  centerline X drift against tolerance 1e-6..1.0. It is candidate-vertex QA, not perceptual
  symmetry analysis.
- All milestone 6–7 tools are read-only and expose no arbitrary Python or unrestricted Blender
  operator execution. Real Blender sculpt/evaluated-geometry behavior remains runtime-unverified.


### Level 3 milestones 8–9 limits

- `character.body_region_plan` derives 17 planning-only body regions from current local mesh
  bounds plus ADULT_NEUTRAL/HEROIC/STYLIZED preset references. It does not mutate geometry.
- `character.limb_guide` emits four side-aware landmarks for ARM or LEG plus a reference
  thickness. `character.extremity_guide` emits seven HAND or five FOOT reference landmarks
  from explicit local anchor/length.
- `character.body_symmetry_audit` uses local X only, caller tolerance 1e-6..100 and the
  bounded spatial-grid partner matcher. It reports unmatched positive/negative vertices and
  duplicate partner collisions; it is coordinate QA, not perceptual/anatomical symmetry.
- `character.sculpt_qa` combines bounded sculpt structural diagnostics and local-X symmetry.
  PASS/REVIEW/BLOCKED is a source-side structural classification only.
- `character.sculpt_recipe_preview` supports BODY_PRIMARY_FORMS, FACE_PRIMARY_FORMS and
  HAND_FOOT_REFINEMENT at intensity 0.05..1.0. It previews ordered existing typed tools and
  never auto-executes mutations.
- `character.sculpt_recovery_snapshot` accepts 1..512 unique vertex indices and returns their
  current coordinates plus a topology revision derived from current vertex count/faces.
- `character.sculpt_recovery_restore` requires fresh object/geometry state, exact matching
  topology revision, editable local unshared base mesh and no shape keys/modifier stack.
  It restores at most 512 explicit coordinates, verifies full indexed geometry and uses the
  ordinary sculpt coordinate rollback path if verification fails.
- These helpers do not expose arbitrary Python or unrestricted Blender operators. Real Blender
  Sculpt Mode/PBVH/Multires/Dyntopo behavior remains runtime-unverified.


### Level 3 milestone 10 limits

- `character.workflow_preview` composes a fixed 12-stage character workflow around existing
  Level 3 tools. It aggregates current body/face/QA/recipe/surface evidence and reports
  READY/REVIEW/BLOCKED, but performs no automatic mutations.
- Recommended mutation groups require a recovery snapshot first and fresh target/geometry state
  for every mutation. Recovery restore is explicit and never triggered automatically.
- `character.level3_acceptance` evaluates eight source-side checks: body landmarks, body
  regions, face fit, face regions, face symmetry, structural sculpt QA, recipe preview and
  surface baseline.
- Acceptance output is explicitly scoped to source/fake-adapter evidence, always reports
  `runtime_acceptance_required=true`, `real_runtime_verified=false` and
  `production_ready=false` in the current source-only environment.
- The separately opt-in runtime harness now supports `--allow-level3-character`, but only
  injected fake-session coverage has been executed. No real Blender runtime acceptance has
  occurred.
- Level 3 source roadmap is complete at 100%; this does not alter the 0% real-runtime status.


### Level 4 milestones 1–2 limits

- `uv.inspect` is read-only and capped at 256 faces, 8,192 loops, 8 UV layers and 8,192
  mesh edges. It reports a dedicated `uv_revision` derived from geometry, per-layer coordinate
  revisions and the complete bounded seam-flag vector.
- Missing UVs, degenerate UV faces, positive-area overlap pairs, UV-island count and relative
  UV-to-surface-area stretch outliers are source-side diagnostics. They do not claim Blender
  UV Editor or unwrap quality equivalence.
- Overlap checks triangulate bounded UV polygons and retain at most 256 positive-area overlap
  pairs. Edge/point-only contact is not treated as overlap.
- `uv.inspect` also acts as the seam preview surface by returning seam flags, seam edge
  indices and seam vertex pairs without mutation.
- `uv.seam_set` requires fresh ObjectTarget, geometry revision and UV revision plus 1..512
  unique explicit edge indices. The target must be editable local unshared mesh data.
- Seam mutation preserves geometry and UV-layer coordinate revisions, reads back the complete
  bounded seam state and restores the prior complete seam-flag vector if verification fails.
- No arbitrary Python or unrestricted Blender operator surface is exposed. Real Blender
  unwrap/pack/material runtime behavior remains unverified.


### Level 4 milestones 3–4 limits

- `uv.unwrap_plan` and `uv.unwrap_apply` support only explicit XY, XZ or YZ object-local
  planar projection. A zero projected axis extent is denied. This is deterministic source
  projection, not Blender Angle Based/Conformal/Smart UV Project behavior.
- `uv.unwrap_apply` requires fresh object, geometry and UV revisions and editable local
  unshared mesh data. It creates a named UV layer only below the eight-layer cap or replaces
  that exact named layer.
- Successful unwrap verification requires unchanged geometry/seams, exact UV layer count/order,
  intended active layer, unchanged non-target layer revisions and the intended target
  coordinate revision. Failure removes a newly-created layer or restores every prior loop UV.
- `uv.inspect` now returns explicit UV-island face-index groups as well as island count.
- `uv.island_transform` accepts only a face set that exactly equals one current detected
  island. It scales around that island's UV bounding-box center and applies bounded translation.
- Island transform accepts scale 0.01..100 and translation/result coordinates within ±16.
  Geometry, seams, active layer, layer order and all non-target UV revisions must remain
  unchanged; verification failure restores all prior target-layer loop coordinates.
- The typed factory currently contains 131 tools. The centralized registry/catalog capacity is
  explicitly bounded at 160 and tested at both registry and host-catalog boundaries.
- No arbitrary Python or unrestricted Blender operator execution was introduced. Real Blender
  UV Editor/unwrap runtime behavior remains unverified.


### Level 4 milestones 5–6 limits

- `uv.pack_plan` / `uv.pack_apply` use deterministic row-major near-square cell packing in
  0..1 UV space with margin 0..0.1. Islands preserve shape/aspect ratio through uniform scale;
  degenerate island bounds and unusable margins fail closed.
- Pack apply requires fresh object, geometry and UV revisions. Geometry, seams, active UV
  layer, layer order and every non-target layer revision must remain unchanged. Verification
  mismatch restores the complete prior target-layer loop coordinates.
- `uv.texel_density_inspect` accepts texture size 16..32768 and reports per-face plus
  min/median/max pixels-per-unit estimates based on UV-area/surface-area ratio.
- `uv.texel_density_plan` is read-only and returns a bounded uniform scale toward a target
  median density. It does not mutate UVs or claim Blender texel-density equivalence.
- Material slot management is capped at 64 slots and 256 faces and requires editable local
  unshared mesh data for mutations.
- `material.slots_inspect` exposes ordered slot names, per-slot face-user counts, every
  bounded face material index and a dedicated material_revision.
- Slot link/reassign/duplicate/remove and face assignment require fresh ObjectTarget plus fresh
  material_revision. Removal is intentionally limited to the final unused slot to avoid silent
  material-index shifting.
- `material.slot_duplicate` duplicates the material datablock rather than merely reusing the
  same reference. New names must be unused.
- `material.face_assign` accepts 1..256 unique explicit faces and restores prior per-face
  material indices if verification fails.
- The factory currently exposes 141 typed tools under the existing centralized 160-tool cap.
- No arbitrary Python, unrestricted Blender UV/material operator surface or shader-node editor
  surface is exposed. Real Blender UV/material runtime behavior remains unverified.


### Level 4 milestones 7–8 limits

- Shader inspection/mutation requires one existing local node-enabled material, exactly one
  Principled BSDF, at most 32 nodes and at most 64 links.
- `material.shader_inspect` reports supported Principled values, managed Normal Map/Bump
  settings, bounded node/link topology, all managed PBR channel bindings and a dedicated
  shader_revision.
- `material.principled_set` accepts only Base Color, Metallic, Roughness, Transmission,
  Emission Color/Strength, Alpha, Normal strength and Height/Bump strength/distance. It may
  create only Shuvi-managed Normal Map/Bump helpers and refuses to replace unmanaged incoming
  shader links.
- Managed normal wiring is bounded to Normal Map → Bump → Principled Normal, with either helper
  omitted when unnecessary. Recovery restores supported Principled values plus the complete
  prior Shuvi-managed node/link state and verifies the initial shader revision.
- PBR assignment supports BASE_COLOR, ROUGHNESS, METALLIC, NORMAL, HEIGHT, AO and ALPHA only.
  It binds only an already-existing local image datablock; no filesystem image-loading surface
  is exposed in Milestone 8.
- Color-space validation is fail-closed: Base Color requires sRGB; Roughness, Metallic, Normal,
  Height, AO and Alpha require Non-Color. The operation does not silently mutate a shared image
  datablock's global colorspace.
- Base Color/Roughness/Metallic/Alpha link directly to matching Principled sockets; Normal and
  Height use Shuvi-managed Normal Map/Bump helpers. Principled has no AO socket, so AO remains
  an explicit managed auxiliary texture and is not falsely reported as directly wired.
- `material.pbr_texture_clear` deletes only the requested Shuvi-managed texture node and its
  links; it never deletes the image datablock or unmanaged nodes.
- The factory currently exposes 145 typed tools under the existing centralized 160-tool cap.
- No arbitrary Python, unrestricted shader-node creation, filesystem image loading or generic
  Blender material operator surface is exposed. Real Blender shader/PBR runtime behavior
  remains unverified.


### Level 4 milestones 9–10 limits

- `texture.image_inspect` reads one existing local image datablock and returns only bounded
  metadata: dimensions, colorspace, source/tiled state, up to 256 tile numbers, packed state,
  filepath-presence boolean and an image revision. It does not expose or load a filesystem path.
- `texture.udim_plan` is source-only. It maps bounded face UV extents onto standard 10-column
  UDIM numbering from 1001, keeps exact tile-boundary faces deterministic, and reports faces
  that span tiles or leave the supported range. It never claims real Blender UDIM behavior.
- `texture.channel_qa` validates the seven Shuvi-managed PBR channels for image existence,
  expected colorspace, direct/helper link integrity and the managed Normal Map/Bump chain.
  Missing optional channels are ABSENT; structurally broken managed channels are BLOCKED.
- `texture.consistency_qa` reports invalid image sizes as blockers and mixed resolutions or
  cross-channel image reuse as review advisories.
- `texture.bake_prep` validates material assignment, UV degeneracy/overlap, supported UDIM
  placement and managed channel health for 1..7 requested channels at texture size 16..32768.
  It is explicitly source-only and never invokes a Blender bake operator.
- `texture.recovery_snapshot` captures only supported Principled values, managed Normal/Bump
  values and seven managed texture image names. It does not serialize arbitrary nodes.
- `texture.recovery_restore` requires fresh shader state and a recovery revision matching the
  validated bounded state. It rebuilds only Shuvi-managed graph content, validates referenced
  local images/colorspaces, reads back the recovery revision and verifies rollback on failure.
- `texture.asset_qa`, `texture.workflow_preview` and `texture.level4_acceptance` combine
  bounded UV/material/texture evidence. Workflow preview never auto-mutates. Final source
  acceptance is explicitly fake/source scoped, requires later runtime acceptance, and cannot
  mark production readiness.
- The acceptance harness exposes Level 4 cases only behind both `--authorize-runtime` and the
  separate `--allow-level4-textures` opt-in. Injected fake-session CI is not real runtime.
- The factory now exposes **155 typed tools** under the centralized **160-tool** hard cap.
- No arbitrary Python, generic node editor, unrestricted bpy/material operator, external image
  loader, real bake execution or hidden production/runtime claim is introduced.


### Level 5 milestones 1–2 limits

- `geometry_nodes.tree_inspect` accepts only an existing local `GeometryNodeTree` by name.
  It caps inspection at 64 nodes, 128 links, 64 interface sockets, 32 inputs and 32 outputs
  per node, and 32 nested groups. It returns a fresh `group_revision` over the bounded
  interface, nodes/sockets, links and nested-group references.
- Foreign nodes may be inspected but are never implicitly made mutable.
- `geometry_nodes.group_create` creates only an empty local `GeometryNodeTree`; it does not
  attach the group to an object or create a modifier/interface automatically.
- `geometry_nodes.node_add` accepts only ten explicit node aliases mapped internally to
  Blender idnames: MESH_CUBE, MESH_ICO_SPHERE, JOIN_GEOMETRY, TRANSFORM_GEOMETRY,
  SET_POSITION, INPUT_POSITION, INPUT_NORMAL, INPUT_INDEX, REALIZE_INSTANCES and
  INSTANCE_ON_POINTS. Caller-supplied Blender idnames are never executed.
- Node placement is bounded to ±10000 editor units and is deterministic when omitted.
- `geometry_nodes.node_remove` refuses linked nodes until Milestone 3 provides typed link
  capture/recovery. Unlinked removal captures restorable node state and verifies rollback.
- `geometry_nodes.node_set_input` only edits specifically allowlisted typed defaults for the
  allowlisted node kind. Linked inputs are never disconnected to make a default edit succeed.
- Every node mutation requires a fresh group revision and actual bounded readback.
- Milestones 1-2 ended at **160 typed tools**. Milestone 3 deliberately raises the centralized
  registry/client hard cap from **160 to 168** and adds only two typed link mutations, taking
  the factory to **162 tools**. The bounded cap remains enforced and no generic executor is used.
- No arbitrary Python, unrestricted node creation, generic node property setter, typed link
  mutation, Geometry Nodes modifier binding, real Geometry Nodes evaluation or runtime claim
  is exposed by Milestones 1–2.


### Level 5 milestone 3 limits

- Link mutation identifies sockets by their inspected stable socket identifiers, not only by
  display names. Node names plus source/output and target/input socket identifiers define the
  exact link identity.
- Both endpoint nodes must be Shuvi-allowlisted Geometry Nodes. Foreign nodes remain inspectable
  but cannot participate in external typed link mutation.
- `geometry_nodes.link_add` requires a fresh group revision, an existing output socket and
  input socket, exact non-UNKNOWN socket-type equality and remaining link budget.
- Exact duplicate links are rejected. Single-input sockets reject a second incoming link;
  multi-input sockets may accept multiple distinct compatible incoming links.
- A bounded graph walk rejects a new directed link when it would introduce a dependency cycle.
- Successful link creation verifies exact link presence and an exact +1 link count. A known
  readback mismatch removes the new link and verifies the original group revision.
- `geometry_nodes.link_remove` requires the exact existing link and fresh group revision.
  Removal verifies exact absence and an exact -1 link count; verification failure recreates
  the original link and verifies the original group revision.
- Geometry-node removal now captures all bounded incident link identities before deleting an
  allowlisted node. Verification accounts for the exact incident-link count; rollback rebuilds
  the node and restores every captured link before claiming recovery.
- The factory exposes **162 typed tools** under the deliberately bounded **168-tool** hard cap.
- No unrestricted graph rewrite, arbitrary Blender node idname, implicit type conversion,
  self-link, cyclic graph construction, generic Python or real Geometry Nodes evaluation is
  exposed.


### Level 5 milestone 4 limits

- `geometry_nodes.modifier_inspect` resolves one current-session mesh object and inspects at
  most the existing 16-modifier stack bound. Only NODES modifiers are returned as bindings.
- Binding inspection reports modifier name/type/visibility, bound group name, whether the group
  is local, its tree type, and a fresh group revision when the bound local group is a bounded
  GeometryNodeTree. Broken/unbound NODES modifiers are reported without inventing a group.
- Object snapshots now include `node_group_name` for NODES modifiers, so object revisions
  change when a Geometry Nodes binding changes.
- `geometry_nodes.modifier_bind` requires a fresh ObjectTarget plus fresh group revision,
  OBJECT mode, editable local mesh object, local mesh data without shape keys, bounded mesh
  size, available modifier capacity, unique modifier name and bounded local GeometryNodeTree.
- Binding creates exactly one NODES modifier and assigns exactly the requested node group. It
  preserves all pre-existing modifiers and verifies modifier count, NODES type, bound group
  name, object snapshot and unchanged group revision.
- Known bind verification failure removes the created modifier and verifies restoration of the
  original object revision and group revision.
- `geometry_nodes.modifier_remove` requires the exact NODES modifier already bound to the
  requested fresh group. It verifies exact modifier absence and count decrement while keeping
  the node group itself unchanged.
- Known removal verification failure recreates the modifier, restores its original stack index,
  viewport/render flags and group binding, then verifies the original object/group revisions.
- The factory exposes **165 typed tools** under the existing bounded **168-tool** hard cap.
- No modifier evaluation claim, generic modifier setter, arbitrary node-group assignment,
  modifier apply operation, external linked group mutation, shape-key workflow or real Blender
  Geometry Nodes runtime claim is exposed.


### Level 5 milestone 5 limits

- `geometry_nodes.primitive_preview` supports only three source-defined recipes:
  `CUBE`, `ICO_SPHERE` and `TWIN_CUBE`. It returns a deterministic graph plan,
  interface/output intent and `primitive_revision` without touching Blender data.
- Recipe parameters are strongly bounded: positive size/radius, cube vertex counts 2..64,
  Icosphere subdivisions 1..5 and twin-cube offsets within ±1000.
- `geometry_nodes.primitive_apply` requires a fresh group revision and an entirely empty
  bounded local GeometryNodeTree. It refuses groups with more than one user to avoid mutating a
  shared procedural asset.
- Apply creates one output Geometry interface socket plus an internal `NodeGroupOutput`.
  Callers cannot request that internal node through the generic typed node-add surface.
- Recipe graph nodes are only existing allowlisted Geometry Nodes. `CUBE` uses Mesh Cube,
  `ICO_SPHERE` uses Mesh Ico Sphere, and `TWIN_CUBE` uses two Mesh Cubes plus one Transform
  Geometry and one Join Geometry.
- Every recipe uses deterministic names, node locations, typed default values and exact
  source-side links into the Group Output Geometry socket.
- Apply verification compares the exact interface, node types/names/locations/defaults and
  link topology. Known mismatch removes the recipe graph/interface and verifies restoration of
  the original empty group revision.
- `geometry_nodes.primitive_clear` first requires the current group to exactly match the
  requested recipe/prefix/parameters. Modified or foreign graphs fail closed instead of being
  partially deleted.
- Clear verifies the group becomes exactly empty. Known readback mismatch rebuilds the exact
  recipe and verifies restoration of the original group revision.
- These source-side checks do not evaluate modifier output, generated mesh topology,
  dependency-graph behavior or render output in real Blender.
- The factory now exposes **168 typed tools**, exactly matching the current **168-tool** hard
  registry/client cap. Milestone 6 must deliberately raise the bounded cap before adding any
  new typed operations; no generic executor may be used to bypass the limit.


### Level 5 milestone 6 limits

- `geometry_nodes.field_preview` supports exactly three typed workflows:
  `INDEX_ATTRIBUTE`, `POSITION_ATTRIBUTE`, and `NORMAL_ATTRIBUTE`.
- Each workflow starts with one bounded Mesh Cube source and routes exactly one built-in field
  into one internal Store Named Attribute node before Group Output.
- Attribute names are collision-conservative: they must begin with `shuvi_`, include a
  non-empty suffix, contain only ASCII letters/digits/underscore, and fit within 48 UTF-8 bytes.
- `INDEX_ATTRIBUTE` stores the Index field as `INT` on the `POINT` domain.
  `POSITION_ATTRIBUTE` and `NORMAL_ATTRIBUTE` store vector fields as `FLOAT_VECTOR` on
  the `POINT` domain.
- The Store Named Attribute node is internal to the managed workflow; generic node creation
  still does not expose arbitrary Store Named Attribute property mutation.
- Geometry-node inspection now reports bounded `field_settings` for Store Named Attribute
  nodes: exact `data_type` and `domain`. Those settings participate in the group revision.
- Apply requires a fresh group revision, a completely empty local GeometryNodeTree and at most
  one group user. Shared procedural assets fail closed.
- Apply verification compares exact output interface, node names/types/locations, selected
  default values, Store Named Attribute settings and link topology.
- Clear first requires the current graph to exactly match the requested workflow, prefix and
  parameters. Any changed domain, data type, attribute name, default, link or foreign node
  causes refusal instead of partial deletion.
- Known apply failures restore the original empty group revision. Known clear failures rebuild
  the exact workflow and verify restoration of the original group revision.
- The registry/client cap is deliberately raised from **168 to 176** for this milestone.
  The factory now exposes **171 typed tools**, remaining below the bounded hard cap.
- These checks are source/fake-bpy evidence only; they do not prove real Blender attribute
  storage, field evaluation, generated mesh data layers, dependency-graph behavior or render
  output.


### Level 5 milestone 7 limits

- `geometry_nodes.scatter_preview` supports exactly `CUBE_SCATTER` and
  `ICO_SPHERE_SCATTER`.
- Both recipes use one bounded Mesh Cube as the point source. Per-axis point resolution is
  limited to 2..20 and a deterministic cube-surface point estimate is computed before any
  mutation. Requests above **2048 estimated instances** are rejected.
- Scatter source extent is bounded to 0.001..1000 on each axis. Rotation is bounded to
  ±2π and instance scale to 0.001..100 on each axis.
- CUBE_SCATTER uses a bounded Mesh Cube instance template with 2..8 vertices per axis.
  ICO_SPHERE_SCATTER uses a bounded Ico Sphere template with subdivisions 1..3.
- The graph is fixed: point mesh → Instance on Points Points; template mesh → Instance;
  Instance on Points Instances → Group Output Geometry.
- Selection is fixed true, Pick Instance false and Instance Index zero. No random selection,
  unbounded density field, external object, collection, asset-library or material reference is
  accepted.
- Instances remain unrealized. Preview reports `estimated_instance_count`,
  `maximum_instance_count=2048`, `instances_realized=false`,
  `external_asset_references=false` and `collection_references=false`.
- Apply requires a fresh group revision, an entirely empty local GeometryNodeTree and at most
  one current group user. Existing or shared graphs fail closed.
- Apply verification compares exact interface, node names/types/locations, bounded defaults and
  exact link topology. Known mismatch removes the complete scatter graph/interface and verifies
  restoration of the original empty group revision.
- Clear requires the current graph to exactly match the requested scatter recipe/prefix/
  parameters. Any changed transform, resolution, template default, link, interface or foreign
  node causes refusal rather than partial deletion.
- Known clear verification failure rebuilds the exact scatter graph and verifies restoration of
  the original group revision.
- The factory now exposes **174 typed tools** under the existing bounded **176-tool** cap.
- Fake-bpy/CI prove source graph intent only; they do not prove real Blender instance count,
  instance placement, geometry evaluation, viewport behavior, memory/GPU cost or render output.


### Level 5 milestone 8 limits

- `geometry_nodes.architecture_preview` supports exactly `MODULAR_WALL` and
  `BLOCK_GRID`.
- MODULAR_WALL repeats bounded Cube modules along X. Count is limited to 1..16, with module
  size 0.001..1000, non-negative gap up to 1000 and base offset within ±1000 per axis.
- BLOCK_GRID repeats bounded Cube blocks on an XY grid. Each axis count is limited to 1..6 and
  the product is hard-limited to **24 modules**. Block size is 0.001..1000, per-axis gaps are
  0..1000 and base offset is within ±1000.
- Every module uses exactly one Mesh Cube plus one Transform Geometry node. All transformed
  outputs feed one Join Geometry multi-input socket, then one internal Group Output.
- Worst-case BLOCK_GRID uses 24 modules and therefore **50 nodes**, remaining below the
  existing 64-node Geometry Nodes inspection/work limit.
- All primitive cube vertex counts are fixed at 2 per axis; Transform rotation is fixed zero
  and scale fixed one. Callers control only bounded module/block size, repetition counts,
  spacing and base offset.
- No external object, collection, asset-library, material or unrestricted node reference is
  accepted.
- Apply requires a fresh group revision, a completely empty local GeometryNodeTree and at most
  one current group user. Existing or shared graphs fail closed.
- Apply verification compares exact output interface, every generated node name/type/location,
  selected typed defaults and complete link topology. Known mismatch removes the complete
  architecture graph/interface and verifies restoration of the original empty group revision.
- Clear requires the current graph to exactly match the requested architecture recipe/prefix/
  parameters. Any changed translation, size, link, interface or foreign node causes refusal.
- Known clear verification failure rebuilds the exact architecture graph and verifies the
  original group revision.
- The registry/client cap is deliberately raised from **176 to 184**. The factory now exposes
  **177 typed tools**.
- Fake-bpy/CI prove deterministic source graph intent only; they do not prove real Blender
  architecture dimensions, overlap, manifoldness, Boolean construction, viewport output,
  dependency-graph behavior, memory/GPU cost or render results.


### Level 5 milestone 9 limits

- `geometry_nodes.recipe_catalog` exposes a static bounded library of exactly **10 recipe IDs**:
  three primitive recipes, three field/attribute workflows, two scatter recipes and two
  architecture/environment recipes.
- Every catalog entry reports a fixed `recipe_id`, family, underlying family recipe/workflow,
  `recipe_version=1`, `library_version=1`, minimum Blender version `4.2`, explicit
  parameter schema, supported operations, `source_only=true` and
  `real_runtime_verified=false`.
- Compatibility is explicitly marked `SOURCE_VALIDATED_RUNTIME_UNVERIFIED`; the catalog does
  not claim real Blender Geometry Nodes execution.
- Catalog entries are sorted deterministically and the complete catalog has a deterministic
  `catalog_revision`.
- `geometry_nodes.recipe_preview`, `recipe_apply` and `recipe_clear` accept only the
  allowlisted recipe IDs. Unknown IDs fail before routing.
- The library does not implement duplicate graph builders. It validates through and delegates to
  the already-bounded primitive, field, scatter or architecture parser/operation for that ID.
- Underlying family parameter limits remain authoritative: attribute-name rules, scatter
  instance limits, architecture module limits and all numeric bounds are preserved unchanged.
- Mutation routing preserves the underlying fresh group revision requirement, empty/shared-group
  guards, exact source readback, structured verification and rollback/rebuild behavior.
- Library results include recipe metadata plus the unchanged underlying `family_result`; verified
  family mutations remain verified only when the underlying readback matched.
- Source tests compare library previews with the direct family preview output and execute verified
  apply→clear round trips for all **10 recipe IDs**.
- The recipe-library host parsers use distinct aliases from the pre-existing modeling recipe
  parser names, preventing host-contract shadowing.
- No arbitrary recipe registration, dynamic Python import, arbitrary node ID, generic graph
  payload, file-backed recipe loading or remote recipe source is exposed.
- Milestone 9 adds four typed operations, taking the factory from 177 to **181 typed tools**
  under the existing bounded **184-tool** cap.


### Level 5 milestone 10 limits

- `geometry_nodes.workflow_preview` composes a fixed nine-stage Level 5 workflow over the
  existing recipe catalog, direct managed-family preview, recipe-library preview, fresh-group
  mutation gates, exact tree readback, negative-state gates, managed clear/recovery and final
  acceptance reporting. It performs no automatic mutation.
- `geometry_nodes.level5_acceptance` evaluates seven source-side checks: fixed ten-recipe
  catalog, versioned compatibility metadata, static four-family routing, selected recipe
  membership, direct-family preview equivalence, bounded node/link plan and explicit
  source/runtime separation.
- All 10 managed recipe IDs are exercised through the acceptance surface. Representative
  primitive, field, scatter and architecture recipes also verify stale-revision refusal and
  recipe-wrapper rollback/recovery behavior.
- Cross-family parameter payloads fail during typed parsing rather than being reinterpreted by
  another family.
- Milestone 10 adds two read-only tools, taking the factory from 181 to **183 typed tools**
  under the existing bounded **184-tool** registry/client cap.
- Source/fake-bpy/CI acceptance does not prove real Blender Geometry Nodes evaluation,
  dependency-graph behavior, viewport output, memory/GPU behavior or rendering.
- Level 5 source roadmap is complete at 100%. Real Blender runtime verification remains 0%.


### Level 6 milestone 1 limits

- `rig.armature_inspect` is read-only and requires one current-session ARMATURE object.
- Armature data and pose data are each capped at **256 bones**.
- Per-pose-bone constraints are capped at **64**, with **512 total pose constraints**.
- Bone hierarchy readback includes parent, local head/tail, optional 4x4 local matrix,
  connect/deform flags and inherit-scale mode.
- Pose readback includes location, Euler/quaternion rotation, scale and bounded
  name/type/mute/influence constraint metadata.
- The result reports root bones, hierarchy-cycle diagnostics, pose/data name mismatches,
  exact linked-data flags, `source_only=true`, `real_runtime_verified=false` and a
  deterministic `rig_revision`.
- Non-armatures, over-bound rigs and non-finite coordinate/matrix/influence values fail closed.
- Milestone 1 adds one read-only tool, taking the factory from 183 to **184 typed tools**.
  The centralized registry/client hard maximum is raised from **184 to 192** for bounded
  future Level 6 milestones.
- Real Blender edit-bone lifetimes, pose evaluation, constraints, IK, skinning, deformation,
  vertex-weight behavior and dependency-graph results remain runtime-unverified.


### Level 6 milestone 2 limits

- `rig.armature_create` requires a fresh scene revision, Object mode, an unused object name
  and an unused derived armature-data name. It creates one empty local armature datablock and
  one scene-linked ARMATURE object, applies the requested bounded transform and verifies both
  object and rig readback. Verification mismatch removes both created resources.
- `rig.bone_create` requires a fresh ObjectTarget, a fresh `expected_rig_revision`, an
  editable local armature, Object mode, and the target selected and active.
- Bone names are unique and bounded by the existing 63-byte object-name contract.
- Bone head/tail coordinates are bounded to ±100000 Blender units and must differ.
- Milestone 2 creates only standalone root bones: parent is fixed null and
  `use_connect=false`. Parenting/connect/rename are intentionally deferred to Milestone 3.
- Bone creation enters only the internal allowlisted ARMATURE Edit mode, creates one edit bone,
  returns to Object mode, then verifies count/name/head/tail/deform state and object identity.
- Verification mismatch removes only the just-created bone, returns to Object mode and checks
  recovery against the original `rig_revision`.
- Milestone 2 adds two mutation tools, taking the factory from 184 to **186 typed tools**
  under the existing bounded **192-tool** registry/client cap.
- Real Blender edit-bone lifetime behavior, mode/context quirks, pose-channel regeneration,
  dependency-graph updates and deformation remain runtime-unverified.


### Level 6 milestone 3 limits

- `rig.bone_hierarchy_edit` requires a fresh ObjectTarget, fresh `rig_revision`, an editable
  local armature, Object mode, and the target selected and active.
- The requested final bone name must be unique. Parent assignment is explicit; null unparents.
  `use_connect=true` requires a parent.
- Hierarchy edits preflight the complete bounded parent map and reject cycles before mutation.
- Connected children are explicitly snapped to the requested parent's tail before connect is
  enabled; successful readback verifies the final hierarchy and coordinate side effect.
- Verification mismatch restores original name, parent, head, tail and connect state and checks
  recovery against the original `rig_revision`.
- `rig.bone_symmetry_edit` only accepts an explicit matching `.L` / `.R` pair and reflects
  left head/tail coordinates across local X. It does not perform fuzzy counterpart discovery.
- Symmetry coordinate editing requires both bones to be disconnected and preserves their parent
  and deform state. Both bones are restored on verification failure.
- Milestone 3 adds two mutation tools, taking the factory from 186 to **188 typed tools** under
  the existing bounded **192-tool** registry/client cap.
- Real Blender edit-bone rename propagation, connect snapping, pose-channel regeneration,
  dependency-graph updates and viewport behavior remain runtime-unverified.


### Level 6 milestone 4 limits

- Both pose mutations require a fresh ObjectTarget, fresh `rig_revision`, an editable local
  armature, Object mode, and the target selected and active.
- `rig.pose_bone_transform` targets exactly one named existing pose bone. Location is bounded to
  ±100000 Blender units. XYZ Euler rotation is bounded to ±1000 radians.
- Quaternion rotation uses exactly four finite components in [-1, 1], rejects the zero
  quaternion and normalizes deterministically before mutation and verification.
- Pose scale uses exactly three finite positive components in [0.001, 1000].
- Mutation changes only raw pose channels: rotation mode, location, the selected rotation
  representation and scale. Pre-existing constraint metadata is left untouched.
- `rig.pose_bone_reset` restores one explicit pose bone to quaternion identity, zero location/
  Euler channels and unit scale.
- Known verification mismatch restores rotation mode, location, Euler rotation, quaternion
  rotation and scale and checks recovery against the original `rig_revision`.
- Milestone 4 adds two mutation tools, taking the factory from 188 to **190 typed tools** under
  the existing bounded **192-tool** registry/client cap.
- Real Blender pose evaluation, dependency-graph behavior, constraint interaction, animation/
  keyframe interaction and viewport behavior remain runtime-unverified.


### Level 6 milestone 5 limits

- Both constraint mutations require a fresh ObjectTarget, fresh `rig_revision`, an editable
  local armature, Object mode, and the target selected and active.
- Creation accepts only `LIMIT_ROTATION` and `IK`; names are explicit and unique per pose bone.
- Influence is finite in [0, 1], mute is explicit, and the existing inspection bounds remain
  64 constraints per pose bone and 512 total pose constraints.
- `LIMIT_ROTATION` requires all X/Y/Z enable/min/max fields. Limits are bounded to ±1000
  radians and each minimum must not exceed its maximum.
- `IK` targets only one explicit different pose bone in the same armature, requires the target
  in both armature and pose data, and bounds chain count to 1..64.
- No arbitrary target object, pole target, solver option, driver, generic constraint type or
  unrestricted constraint settings surface is exposed.
- Creation mismatch removes the exact just-created constraint object and verifies recovery to
  the original `rig_revision`.
- Removal requires the expected constraint type and bounded managed state. Only the final
  constraint on a pose bone can be removed so append-based rollback preserves ordering.
- Removal mismatch recreates the bounded constraint snapshot and verifies recovery to the
  original `rig_revision`.
- Milestone 5 adds two mutation tools, taking the factory from 190 to **192 typed tools**, exactly
  at the current bounded **192-tool** registry/client cap.
- Real Blender constraint evaluation, IK solver behavior, dependency-graph cycles and viewport
  deformation remain runtime-unverified.


### Level 6 milestone 6 limits

- Both binding mutations require fresh mesh and armature ObjectTargets plus a fresh
  `rig_revision`. Objects/data must be local and editable in Object mode.
- Mesh work is bounded to 4096 vertices, 4096 polygons and 32768 polygon indices.
- Milestone 6 requires an unparented mesh with no shape keys and no pre-existing vertex groups.
- Bind additionally requires an empty modifier stack and one explicit unique modifier name.
- The only created modifier type is `ARMATURE`, targeted to the explicit armature object.
  `use_vertex_groups=true`, `use_bone_envelopes=false`, and viewport/render visibility are
  fixed managed settings.
- No automatic parenting, automatic weights, bone-envelope binding, generic modifier settings,
  arbitrary target discovery or weight mutation is exposed.
- Successful bind readback verifies the exact armature object ID behind the modifier target,
  exact managed modifier settings/count, unchanged parent state and unchanged `rig_revision`.
- Bind verification mismatch removes the exact created modifier and checks recovery of both the
  mesh object revision and armature `rig_revision`.
- Unbind requires exactly one modifier and only accepts the exact M6-managed ARMATURE state.
  The zero-vertex-group restriction remains intentional until Milestone 7.
- Unbind verification mismatch recreates the managed Armature modifier and checks recovery of
  both original revisions.
- Milestone 6 raises the bounded registry/client cap from 192 to **200** and adds two mutation
  tools, taking the execution factory from 192 to **194 typed tools**.
- Real Blender deformation, modifier evaluation, dependency-graph interaction and later weight
  behavior remain runtime-unverified.


### Level 6 milestone 7 limits

- Weight inspection/mutation operates only on a mesh + armature pair already connected by the
  exact managed Milestone 6 ARMATURE modifier state.
- Inspection is bounded to 4096 mesh vertices, 4096 polygons, 32768 polygon indices, **64 vertex
  groups**, **64 group memberships per vertex**, and **16,384 total sparse assignments**.
- Group indices must be unique and contiguous from 0; memberships must reference a known group;
  weights must be finite inside [0, 1].
- `weight_revision` fingerprints the exact vertex count, group order/names/indices and all sparse
  assignments. Mutations require this revision in addition to fresh mesh/armature ObjectTargets
  and fresh `rig_revision`.
- Weight mutation only accepts an existing **deform-enabled armature bone** as the group name.
  Existing groups must all match deform-enabled bones before mutation proceeds.
- `rig.vertex_group_weights_set` accepts 1..4096 unique explicit vertex indices, each inside
  actual mesh bounds, with weights in 0.000001..1.0. It replaces the complete sparse map for that
  one group rather than applying a hidden partial patch.
- No arbitrary group names, zero-weight placeholder memberships, automatic weights, envelope
  weighting, generic Weight Paint operations, weight normalization/transfer or fuzzy bone lookup
  is exposed.
- Set verification mismatch removes a newly created group or restores the previous exact weights,
  then checks recovery against the original `weight_revision`.
- Group removal is restricted to the final group in Blender group-index order so append-based
  recovery preserves exact ordering. Mismatch recreates the exact sparse group state.
- Milestone 7 adds three tools, taking the execution factory from 194 to **197 typed tools** under
  the bounded **200-tool** registry/client cap.
- Real Blender skin deformation, dependency-graph evaluation, weight-paint behavior and modifier
  evaluation remain runtime-unverified.


### Level 6 milestone 8 limits

- Preview/setup/switch require four explicit distinct bone names: upper, middle, end and target.
- The armature hierarchy must be exactly upper → middle → end. All three chain bones must be
  deform-enabled and the target/control bone must be non-deforming.
- Setup requires fresh ObjectTarget + fresh `rig_revision`, Object mode, selected/active local
  editable armature state and the existing pose-constraint count bounds.
- The only helper constraint created is same-armature `IK` on the end bone with influence 1.0,
  target = the explicit control bone and fixed chain count **3**.
- Initial `IK` mode leaves the managed IK constraint unmuted; initial `FK` mode mutes it.
- Switch accepts only a fully recognized M8-managed helper and changes only its `mute` field.
- Setup mismatch removes the exact created constraint; switch mismatch restores the previous mute
  state. Both verify recovery to the original `rig_revision`.
- No pole target, driver, custom property, generic constraint type, automatic control-bone
  generation, arbitrary solver option or automatic IK/FK matching is exposed.
- Existing `rig.pose_constraint_remove` remains the bounded cleanup path.
- Milestone 8 adds three tools, taking the factory from 197 to **200 typed tools**, exactly at the
  current **200-tool** registry/client cap.
- Real Blender IK solve behavior, evaluated transforms, dependency-graph behavior and animation
  interpolation remain runtime-unverified.


### Level 6 milestone 9 limits

- The recipe library is fixed and versioned: library version **1**, current recipe version **1**,
  minimum declared Blender version **4.2**, compatibility
  `SOURCE_VALIDATED_RUNTIME_UNVERIFIED`.
- Exactly three recipe IDs are exposed: `constraint.limit_rotation`,
  `constraint.same_armature_ik` and `control.three_bone_ik_fk`.
- `parameters` must match the selected recipe's exact schema; unknown, missing, untyped or
  out-of-bound fields fail closed before execution.
- Catalog and preview are read-only. Preview requires fresh target/revision state and returns a
  deterministic plan/blocker report instead of mutating the rig.
- Apply delegates only to the already bounded Milestone 5 pose-constraint creation or Milestone 8
  IK/FK setup implementation. It inherits their exact readback, stale-state rejection and
  rollback/recovery behavior.
- No user-defined executable recipe, arbitrary Python, unrestricted bpy operator/property path,
  automatic control-rig generation, pole target, driver, custom property or solver payload is
  exposed.
- Milestone 9 adds three tools, taking the factory from 200 to **203 typed tools** and deliberately
  raises the bounded registry/client cap to **203**.
- Real Blender constraint solving, evaluated transforms, dependency-graph behavior and runtime
  compatibility remain unverified.


### Level 6 milestone 10 limits

- Milestone 10 adds an internal source/fake-bpy acceptance harness, not a new public protocol tool.
- The public factory/catalog remains exactly **203 typed tools** under the **203-tool** cap.
- Acceptance requires bounded armature structure, the exact managed mesh/armature binding,
  non-empty deform-bone-matched skin weights, the fixed versioned recipe catalog and a fresh
  managed three-bone IK/FK recipe preview in the same inspector/session.
- Stale state must fail closed. Forced IK/FK verification failure must roll back to the original
  rig state with verified recovery before the recovered state can pass acceptance.
- The acceptance result remains explicitly source-only: real Blender runtime verification is
  **0%** and production readiness is **No**.
