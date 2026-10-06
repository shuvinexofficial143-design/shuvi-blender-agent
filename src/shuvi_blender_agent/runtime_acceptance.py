"""Future opt-in Blender acceptance in a disposable factory-startup workspace."""

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from .client import BlenderController
from .contracts import Request, Status
from .discovery import BlenderVersion, DiscoveryConfig, discover, probe_version
from .errors import AgentError, ErrorCode
from .models import ObjectTarget
from .plans import Plan, PlanRunner, PlanStep
from .process import LaunchConfig, launch
from .safety import SafetyPolicy


def run_acceptance(
    executable: Path,
    *,
    runtime_authorized: bool = False,
    allow_render: bool = False,
    allow_destructive: bool = False,
    allow_level2_modeling: bool = False,
    launcher=launch,
    version_probe=probe_version,
) -> dict:
    if (
        runtime_authorized is not True
        or type(allow_render) is not bool
        or type(allow_destructive) is not bool
        or type(allow_level2_modeling) is not bool
    ):
        raise AgentError(ErrorCode.SAFETY_DENIED, "Explicit runtime authorization is required")
    started = time.monotonic()
    report = {
        "suite_completed": False,
        "real_runtime_verified": False,
        "cases": [],
        "render_requested": allow_render,
        "destructive_requested": allow_destructive,
        "level2_modeling_requested": allow_level2_modeling,
    }
    session = None
    workspace_path = None
    try:
        installations = discover(DiscoveryConfig(configured_paths=(Path(executable),)))
        executable = installations.select().executable
        version = version_probe(executable, 3000)
        if version < BlenderVersion(4, 2):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Acceptance requires Blender 4.2+")
        report["version"] = str(version)
        with TemporaryDirectory(prefix="shuvi-blender-acceptance-") as directory:
            workspace_path = Path(directory)
            config = LaunchConfig(
                executable,
                blend_file=None,
                output_directory=workspace_path,
                policy=SafetyPolicy(
                    allow_mutations=True,
                    allow_destructive=allow_destructive,
                    allow_file_writes=True,
                    allow_rendering=allow_render,
                ),
            )
            with launcher(config) as session:
                controller = BlenderController(session.client)
                controller.capabilities()

                def execute(operation, payload=None):
                    remaining = int(120_000 - (time.monotonic() - started) * 1000)
                    if remaining < 1:
                        raise AgentError(ErrorCode.TIMEOUT, "Acceptance suite deadline exceeded")
                    request = Request(operation, payload or {}, timeout_ms=min(10_000, remaining))
                    result = controller.execute(request)
                    report["cases"].append({"operation": operation, "result": result.to_dict()})
                    if result.status == Status.FAILED:
                        raise result.error
                    return result.data

                def scene_revision():
                    return execute("scene.inspect")["revision"]

                def target(object_id):
                    snapshot = execute("object.inspect", {"object_id": object_id})
                    return asdict(ObjectTarget.from_snapshot(snapshot))

                transform = {"location": [0, 0, 0], "rotation_euler": [0, 0, 0], "scale": [1, 1, 1]}
                execute("system.ping")
                capabilities = execute("system.capabilities")
                if tuple(capabilities["blender_version"]) < (4, 2, 0):
                    raise AgentError(ErrorCode.SAFETY_DENIED, "Running Blender is below 4.2")
                execute("objects.list", {"limit": 1})
                execute("collections.list", {"limit": 1})
                ids = {}
                for kind in ("CUBE", "PLANE", "EMPTY"):
                    data = execute(
                        "object.create",
                        {
                            "name": f"Acceptance{kind}",
                            "kind": kind,
                            "transform": transform,
                            "expected_scene_revision": scene_revision(),
                        },
                    )
                    ids[kind] = data["after"]["object_id"]
                copied = execute(
                    "object.duplicate",
                    {
                        "target": target(ids["CUBE"]),
                        "name": "AcceptanceCopy",
                        "transform": transform,
                    },
                )
                ids["COPY"] = copied["after"]["object_id"]
                execute(
                    "selection.set",
                    {
                        "target": target(ids["CUBE"]),
                        "selected": True,
                        "active": True,
                        "expected_scene_revision": scene_revision(),
                    },
                )
                execute(
                    "mode.set",
                    {
                        "target": target(ids["CUBE"]),
                        "mode": "EDIT",
                        "expected_scene_revision": scene_revision(),
                    },
                )
                execute(
                    "mode.set",
                    {
                        "target": target(ids["CUBE"]),
                        "mode": "OBJECT",
                        "expected_scene_revision": scene_revision(),
                    },
                )
                execute(
                    "curve.create",
                    {
                        "name": "AcceptanceCurve",
                        "points": [[0, 0, 0], [1, 0, 0], [1, 1, 0]],
                        "cyclic": False,
                        "bevel_depth": 0.02,
                        "transform": transform,
                        "expected_scene_revision": scene_revision(),
                    },
                )
                execute(
                    "text.create",
                    {
                        "name": "AcceptanceText",
                        "body": "Shuvi",
                        "align_x": "CENTER",
                        "size": 1,
                        "extrude": 0.05,
                        "transform": transform,
                        "expected_scene_revision": scene_revision(),
                    },
                )
                moved = transform | {"location": [1, 2, 3]}
                execute("object.set_transform", {"target": target(ids["CUBE"]), "transform": moved})
                execute(
                    "material.create_assign",
                    {
                        "target": target(ids["CUBE"]),
                        "name": "AcceptanceMaterial",
                        "base_color": [0.2, 0.4, 0.8, 1],
                        "metallic": 0,
                        "roughness": 0.5,
                    },
                )
                device_ids = {}
                for kind in ("CAMERA", "POINT", "SUN", "SPOT", "AREA"):
                    settings = (
                        {"lens": 35, "clip_start": 0.1, "clip_end": 100, "make_active": True}
                        if kind == "CAMERA"
                        else {"energy": 1, "color": [1, 1, 1]}
                    )
                    created = execute(
                        "device.create",
                        {
                            "name": f"Acceptance{kind}",
                            "kind": kind,
                            "settings": settings,
                            "transform": transform | {"location": [0, 0, 6]},
                            "expected_scene_revision": scene_revision(),
                        },
                    )
                    device_ids[kind] = created["after"]["object_id"]
                execute(
                    "device.update",
                    {
                        "target": target(device_ids["CAMERA"]),
                        "settings": {"lens": 50, "clip_end": 200},
                    },
                )
                execute(
                    "device.update",
                    {
                        "target": target(device_ids["POINT"]),
                        "settings": {"energy": 2, "color": [1, 0.5, 0.25]},
                    },
                )
                execute(
                    "modifier.add",
                    {
                        "target": target(ids["CUBE"]),
                        "name": "AcceptanceBevel",
                        "kind": "BEVEL",
                        "settings": {"width": 0.05, "segments": 1},
                    },
                )
                execute(
                    "collection.create",
                    {
                        "name": "AcceptanceCollection",
                        "target": target(ids["CUBE"]),
                        "expected_scene_revision": scene_revision(),
                    },
                )
                execute(
                    "asset.mark",
                    {"target": target(ids["EMPTY"]), "description": "Disposable acceptance object"},
                )
                execute(
                    "animation.set_range",
                    {"start": 1, "end": 2, "expected_scene_revision": scene_revision()},
                )
                execute(
                    "animation.set_frame", {"frame": 1, "expected_scene_revision": scene_revision()}
                )
                execute(
                    "animation.insert_keyframe",
                    {
                        "target": target(ids["CUBE"]),
                        "frame": 1,
                        "transform": moved,
                        "interpolation": "LINEAR",
                    },
                )
                geometry = {"vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]], "faces": [[0, 1, 2]]}
                mesh = execute(
                    "mesh.create",
                    {
                        "name": "AcceptanceTriangle",
                        "geometry": geometry,
                        "transform": transform | {"location": [2, 0, 0], "scale": [2, 1, 1]},
                        "expected_scene_revision": scene_revision(),
                    },
                )
                mesh_id = mesh["after"]["object"]["object_id"]
                mesh_state = execute("mesh.inspect", {"object_id": mesh_id})
                execute(
                    "mesh.translate_vertices",
                    {
                        "target": target(mesh_id),
                        "indices": [0],
                        "delta": [0, 0, 0.1],
                        "expected_geometry_revision": mesh_state["geometry_revision"],
                    },
                )
                mesh_state = execute("mesh.inspect", {"object_id": mesh_id})
                execute(
                    "origin.to_centroid",
                    {
                        "target": target(mesh_id),
                        "expected_geometry_revision": mesh_state["geometry_revision"],
                    },
                )
                mesh_state = execute("mesh.inspect", {"object_id": mesh_id})
                execute(
                    "mesh.apply_object_transform",
                    {
                        "target": target(mesh_id),
                        "expected_geometry_revision": mesh_state["geometry_revision"],
                    },
                )
                if allow_level2_modeling:
                    level2_geometry = {
                        "vertices": [
                            [0, 0, 0],
                            [1, 0, 0],
                            [1, 1, 0],
                            [0, 1, 0],
                            [0.0001, 0, 0],
                            [9, 9, 9],
                        ],
                        "faces": [[4, 1, 2, 3], [3, 2, 1, 4]],
                    }
                    level2_mesh = execute(
                        "mesh.create",
                        {
                            "name": "AcceptanceLevel2Repair",
                            "geometry": level2_geometry,
                            "transform": transform,
                            "expected_scene_revision": scene_revision(),
                        },
                    )
                    level2_id = level2_mesh["after"]["object"]["object_id"]
                    level2_state = execute("mesh.inspect", {"object_id": level2_id})
                    execute("mesh.topology_inspect", {"object_id": level2_id})
                    execute("mesh.shading_inspect", {"object_id": level2_id})
                    execute("mesh.retopology_inspect", {"object_id": level2_id})
                    qa = execute(
                        "modeling.qa_inspect",
                        {
                            "object_id": level2_id,
                            "distance": 0.001,
                            "area_epsilon": 0,
                        },
                    )
                    execute(
                        "modeling.workflow_preview",
                        {
                            "object_id": level2_id,
                            "workflow": "CLEAN_BASE_MESH",
                            "distance": 0.001,
                            "area_epsilon": 0,
                        },
                    )
                    execute(
                        "modeling.workflow_apply",
                        {
                            "target": target(level2_id),
                            "expected_geometry_revision": level2_state["geometry_revision"],
                            "expected_qa_revision": qa["qa_revision"],
                            "workflow": "CLEAN_BASE_MESH",
                            "distance": 0.001,
                            "area_epsilon": 0,
                        },
                    )
                    execute(
                        "modeling.qa_inspect",
                        {
                            "object_id": level2_id,
                            "distance": 0.001,
                            "area_epsilon": 0,
                        },
                    )
                    stack = execute("modifier.stack_inspect", {"object_id": level2_id})
                    execute(
                        "modifier.recipe_preview",
                        {
                            "recipe": "PANEL_SHELL",
                            "prefix": "AcceptanceL2",
                            "parameters": {
                                "thickness": 0.05,
                                "width": 0.02,
                                "segments": 2,
                            },
                        },
                    )
                    execute(
                        "modifier.recipe_apply",
                        {
                            "target": target(level2_id),
                            "expected_stack_revision": stack["stack_revision"],
                            "recipe": "PANEL_SHELL",
                            "prefix": "AcceptanceL2",
                            "parameters": {
                                "thickness": 0.05,
                                "width": 0.02,
                                "segments": 2,
                            },
                        },
                    )
                    execute("modifier.stack_diagnose", {"object_id": level2_id})
                execute(
                    "render.configure",
                    {
                        "width": 16,
                        "height": 16,
                        "samples": 1,
                        "expected_scene_revision": scene_revision(),
                    },
                )
                execute(
                    "file.checkpoint",
                    {"name": "acceptance.blend", "expected_scene_revision": scene_revision()},
                )
                if allow_destructive:
                    execute(
                        "object.delete",
                        {
                            "target": target(ids["COPY"]),
                            "expected_scene_revision": scene_revision(),
                        },
                    )
                    execute(
                        "file.open_checkpoint",
                        {
                            "name": "acceptance.blend",
                            "expected_scene_revision": scene_revision(),
                        },
                    )
                if allow_render:
                    execute(
                        "render.execute",
                        {"name": "acceptance.png", "expected_scene_revision": scene_revision()},
                    )
                plan = Plan(
                    (
                        PlanStep("ping", Request("system.ping")),
                        PlanStep("scene", Request("scene.inspect")),
                    ),
                    timeout_ms=10_000,
                )
                plan_report = PlanRunner(controller).run(plan)
                report["plan"] = plan_report.to_dict()
                if not plan_report.completed:
                    raise AgentError(ErrorCode.EXECUTION_ERROR, "Acceptance plan failed")
                report["suite_completed"] = True
    except AgentError as exc:
        report["error"] = exc.to_dict()
    except Exception:
        report["error"] = AgentError(
            ErrorCode.EXECUTION_ERROR, "Acceptance suite failed; inspect cleanup"
        ).to_dict()
    report["cleanup_confirmed"] = (
        session is not None and session.client.closed and session.process.poll() is not None
    )
    report["workspace_removed"] = workspace_path is not None and not workspace_path.exists()
    report["real_runtime_verified"] = (
        report["suite_completed"]
        and report["cleanup_confirmed"]
        and report["workspace_removed"]
        and launcher is launch
        and version_probe is probe_version
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorize-runtime", action="store_true")
    parser.add_argument("--allow-render", action="store_true")
    parser.add_argument("--allow-destructive", action="store_true")
    parser.add_argument("--allow-level2-modeling", action="store_true")
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.authorize_runtime:
        if args.executable is None:
            parser.error("--executable is required for an authorized runtime run")
        report = run_acceptance(
            args.executable,
            runtime_authorized=True,
            allow_render=args.allow_render,
            allow_destructive=args.allow_destructive,
            allow_level2_modeling=args.allow_level2_modeling,
        )
    else:
        report = {
            "status": "prepared",
            "real_runtime_verified": False,
            "message": "No Blender executed. Run only after explicit runtime authorization.",
        }
    raw = json.dumps(report, indent=2)
    if args.report:
        with args.report.open("x", encoding="utf-8") as stream:
            stream.write(raw + "\n")
    print(raw)
    return (
        0
        if report.get("status") == "prepared"
        or (
            report["suite_completed"]
            and report["cleanup_confirmed"]
            and report["workspace_removed"]
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
