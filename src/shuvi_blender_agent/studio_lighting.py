"""Level 9 studio AREA rigs with mood palettes, shadow control, and per-light aim."""

from dataclasses import dataclass
from math import atan2, cos, pi, radians, sin, sqrt

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import ObjectTarget, object_name
from .operations import ObjectOperations
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, number, string
from .verification import compare

ROLES = ("Key", "Fill", "Rim")
# Energy in Watts; exact visual exposure still requires live Blender rendering.
PRESETS = {
    "SOFT_STUDIO": ((1200, 500, 850), ((1, 0.95, 0.88), (0.78, 0.87, 1), (1, 1, 1))),
    "DRAMATIC": ((1500, 170, 1300), ((1, 0.85, 0.72), (0.55, 0.72, 1), (1, 0.9, 0.76))),
    "WARM_PORTRAIT": (
        (1000, 410, 800),
        ((1, 0.83, 0.66), (0.83, 0.9, 1), (1, 0.72, 0.52)),
    ),
}
ANGLES = ((40, 35), (-55, 20), (165, 50))
SIZES = (1.6, 2.1, 1.0)

# M2 adds actual four- and five-fixture arrangements. These values
# are initial wattage/position presets, not rendered exposure guarantees.
EXPANDED_PRESETS = {
    "BEAUTY_CLAMSHELL": (
        ("Key", 20, 48, 2.3, 1100, (1.0, 0.93, 0.86)),
        ("Fill", -8, -28, 2.5, 750, (1.0, 0.95, 0.91)),
        ("Rim", 155, 45, 1.2, 680, (1.0, 0.90, 0.83)),
        ("Catchlight", -32, 12, 0.55, 190, (1.0, 1.0, 1.0)),
    ),
    "PRODUCT_FIVE_POINT": (
        ("Key", 38, 38, 2.4, 1350, (1.0, 0.98, 0.94)),
        ("Fill", -62, 20, 2.8, 600, (0.91, 0.95, 1.0)),
        ("Rim", 150, 46, 1.15, 1100, (1.0, 1.0, 1.0)),
        ("Top", 0, 78, 1.6, 790, (1.0, 0.99, 0.96)),
        ("Edge", -145, 16, 1.0, 440, (0.87, 0.94, 1.0)),
    ),
}
# Per-role color and power multipliers: real AREA light datablock adjustments.
# Mood changes leave fixture geometry and foreign scene state untouched.
# Size influences area-light penumbra; spread limits the emitter cone.
# use_shadow is the Blender 4.2+ common Light cast-shadow property.
# Neither sampling noise nor rendered appearance is certified by source tests.
SHADOW_PROFILES = {
    "STANDARD": (1.0, pi, True),
    "SOFT_CINEMATIC": (2.25, pi, True),
    "CRISP_DIRECTIONAL": (0.35, pi / 2, True),
    "NO_SHADOWS": (1.0, pi, False),
}
MOOD_STYLES = {
    "NEUTRAL": {},
    "GOLDEN_HOUR": {
        "Key": ((1.0, 0.70, 0.42), 1.15),
        "Fill": ((1.0, 0.77, 0.58), 0.70),
        "Rim": ((1.0, 0.42, 0.22), 1.30),
        "Catchlight": ((1.0, 0.90, 0.73), 0.80),
        "Top": ((1.0, 0.79, 0.51), 0.90),
        "Edge": ((1.0, 0.54, 0.30), 1.12),
    },
    "MOONLIT_BLUE": {
        "Key": ((0.42, 0.63, 1.0), 0.72),
        "Fill": ((0.25, 0.44, 0.90), 0.43),
        "Rim": ((0.63, 0.80, 1.0), 1.05),
        "Catchlight": ((0.77, 0.87, 1.0), 0.76),
        "Top": ((0.43, 0.58, 0.95), 0.60),
        "Edge": ((0.33, 0.67, 1.0), 0.85),
    },
    "TEAL_AMBER": {
        "Key": ((1.0, 0.57, 0.28), 1.20),
        "Fill": ((0.10, 0.83, 0.82), 0.48),
        "Rim": ((0.16, 0.88, 0.94), 1.25),
        "Catchlight": ((1.0, 0.84, 0.65), 0.80),
        "Top": ((1.0, 0.58, 0.29), 0.85),
        "Edge": ((0.08, 0.86, 0.79), 1.10),
    },
}
PRESET_DESCRIPTIONS = {
    "SOFT_STUDIO": "Balanced three-point neutral studio lighting",
    "DRAMATIC": "Three-point higher contrast with restrained fill",
    "WARM_PORTRAIT": "Three-point warm portrait with a cool fill",
    "BEAUTY_CLAMSHELL": "Four-light beauty portrait with low frontal fill",
    "PRODUCT_FIVE_POINT": "Five-light product illumination with top and edge lights",
}


def _layout_specs(preset):
    if preset in EXPANDED_PRESETS:
        return EXPANDED_PRESETS[preset]
    energies, colors = PRESETS[preset]
    return tuple(
        (role, angles[0], angles[1], size, energy, rgb)
        for role, angles, size, energy, rgb in zip(
            ROLES, ANGLES, SIZES, energies, colors, strict=True
        )
    )


@dataclass(frozen=True)
class StudioPresetCatalog:
    @classmethod
    def parse(cls, data):
        fields(data, set())
        return cls()


@dataclass(frozen=True)
class RigPreview:
    subject: ObjectTarget
    name_prefix: str
    preset: str
    distance_scale: float
    intensity_scale: float
    mood: str = "NEUTRAL"
    shadow_profile: str = "STANDARD"
    target_offsets: dict[str, tuple[float, float, float]] | None = None

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {"subject", "name_prefix", "preset", "distance_scale", "intensity_scale"},
            {"mood", "shadow_profile", "target_offsets"},
        )
        preset = string(data["preset"], "preset", limit=32)
        if preset not in PRESETS and preset not in EXPANDED_PRESETS:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Unknown studio lighting preset")
        mood = string(data.get("mood", "NEUTRAL"), "mood", limit=24)
        if mood not in MOOD_STYLES:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Unknown cinematic lighting mood")
        shadow_profile = string(data.get("shadow_profile", "STANDARD"), "shadow_profile", limit=32)
        if shadow_profile not in SHADOW_PROFILES:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Unknown shadow quality profile")
        offsets = data.get("target_offsets", {})
        if not isinstance(offsets, dict) or len(offsets) > 5:
            raise AgentError(
                ErrorCode.INVALID_REQUEST, "Target offsets must be a small role mapping"
            )
        allowed_roles = {role for role, *_ in _layout_specs(preset)}
        mapped = {}
        for role, value in offsets.items():
            if role not in allowed_roles or not isinstance(value, list) or len(value) != 3:
                raise AgentError(ErrorCode.INVALID_REQUEST, "Unknown role or invalid target offset")
            mapped[role] = tuple(number(v, "target offset", -0.45, 0.45) for v in value)
        prefix = object_name(data["name_prefix"])
        if len(prefix) > 40:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Light prefix exceeds 40 characters")
        return cls(
            ObjectTarget.parse(data["subject"]),
            prefix,
            preset,
            number(data["distance_scale"], "distance_scale", 2.5, 6.0),
            number(data["intensity_scale"], "intensity_scale", 0.25, 3.0),
            mood,
            shadow_profile,
            mapped,
        )


@dataclass(frozen=True)
class RigApply:
    preview: RigPreview
    expected_lighting_revision: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "subject",
                "name_prefix",
                "preset",
                "distance_scale",
                "intensity_scale",
                "expected_lighting_revision",
            },
            {"mood", "shadow_profile", "target_offsets"},
        )
        return cls(
            RigPreview.parse(
                {key: value for key, value in data.items() if key != "expected_lighting_revision"}
            ),
            string(data["expected_lighting_revision"], "expected_lighting_revision", limit=64),
        )


@dataclass(frozen=True)
class RigRelease:
    expected_lighting_token: str

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_lighting_token"})
        return cls(string(data["expected_lighting_token"], "expected_lighting_token", limit=64))



TUNABLE_FIELDS = ("energy", "color", "size", "use_shadow")


def _tune_fields(data):
    patch = fields(
        data,
        set(),
        {"energy_watts", "rgb", "emitter_size", "cast_shadows"},
    )
    if not patch:
        raise AgentError(ErrorCode.INVALID_REQUEST, "At least one light property is required")
    values = {}
    if "energy_watts" in patch:
        values["energy"] = number(patch["energy_watts"], "energy_watts", 1, 100_000)
    if "rgb" in patch:
        rgb = patch["rgb"]
        if not isinstance(rgb, list) or len(rgb) != 3:
            raise AgentError(ErrorCode.INVALID_REQUEST, "rgb requires three channels")
        values["color"] = [number(v, "rgb channel", 0, 1) for v in rgb]
    if "emitter_size" in patch:
        values["size"] = number(patch["emitter_size"], "emitter_size", 0.2, 50_000)
    if "cast_shadows" in patch:
        if type(patch["cast_shadows"]) is not bool:
            raise AgentError(ErrorCode.INVALID_REQUEST, "cast_shadows must be Boolean")
        values["use_shadow"] = patch["cast_shadows"]
    return values


@dataclass(frozen=True)
class TunePreview:
    token: str
    role: str
    settings: dict

    @classmethod
    def parse(cls, data):
        fields(data, {"expected_lighting_token", "role", "settings"})
        return cls(
            string(data["expected_lighting_token"], "expected_lighting_token", limit=64),
            string(data["role"], "role", limit=24),
            _tune_fields(data["settings"]),
        )


@dataclass(frozen=True)
class TuneApply:
    preview: TunePreview
    expected_tuning_revision: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {"expected_lighting_token", "role", "settings", "expected_tuning_revision"},
        )
        return cls(
            TunePreview.parse(
                {key: value for key, value in data.items() if key != "expected_tuning_revision"}
            ),
            string(data["expected_tuning_revision"], "expected_tuning_revision", limit=64),
        )


class StudioLightingOperations:
    """Creates three actual Blender area lights, verifies and owns their life cycle."""

    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy
        self._owned = {}

    @staticmethod
    def _pointer(value):
        return int(value.as_pointer()) if hasattr(value, "as_pointer") else id(value)

    def _in_table(self, obj):
        return any(self._pointer(item) == self._pointer(obj) for item in self.bpy.data.objects)

    def _in_lights(self, data):
        return any(self._pointer(item) == self._pointer(data) for item in self.bpy.data.lights)

    def _read(self, obj, data):
        snap = self.inspector.snapshot(obj)
        return {
            "name": snap["name"],
            "type": snap["type"],
            "location": snap["transform"]["location"],
            "rotation_euler": snap["transform"]["rotation_euler"],
            "rotation_mode": snap["transform"]["rotation_mode"],
            "scale": snap["transform"]["scale"],
            "scene_member": self.bpy.context.scene.objects.get(obj.name) is obj,
            "data_same": obj.data is data,
            "data_type": data.type,
            "data_name": data.name,
            "energy": float(data.energy),
            "color": list(data.color),
            "shape": data.shape,
            "size": float(data.size),
            "spread": float(data.spread),
            "use_shadow": bool(data.use_shadow),
            "users": int(data.users),
        }

    @staticmethod
    def _expected(entry):
        return {
            "name": entry["name"],
            "type": "LIGHT",
            "location": entry["location"],
            "rotation_euler": entry["rotation_euler"],
            "rotation_mode": "XYZ",
            "scale": [1.0, 1.0, 1.0],
            "scene_member": True,
            "data_same": True,
            "data_type": "AREA",
            "data_name": entry["name"],
            "energy": entry["energy"],
            "color": entry["color"],
            "shape": "DISK",
            "size": entry["size"],
            "spread": entry["spread"],
            "use_shadow": entry["use_shadow"],
            "users": 1,
        }

    def _plan(self, action: RigPreview):
        subject, snap = self.inspector.target(action.subject)
        if subject.type != "MESH":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Studio rig requires a mesh subject")
        center = [number(v, "subject center", -100_000, 100_000) for v in subject.location]
        dimensions = [number(v, "subject dimensions", 0, 10_000) for v in subject.dimensions]
        radius = sqrt(sum(v * v for v in dimensions)) / 2
        if radius < 0.001 or radius > 5_000:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Subject size cannot be safely framed")
        scene_revision = self.inspector.summary()["revision"]
        blockers = set()
        if subject.parent is not None or len(subject.constraints):
            blockers.add("PARENTED_OR_CONSTRAINED_SUBJECT")
        if subject.animation_data is not None:
            blockers.add("ANIMATED_SUBJECT_UNSUPPORTED")
        if subject.rotation_mode != "XYZ" or any(
            abs(float(value)) > 1e-5 for value in subject.rotation_euler
        ):
            blockers.add("ROTATED_SUBJECT_UNSUPPORTED")
        if any(abs(float(value) - 1) > 1e-5 for value in subject.scale):
            blockers.add("NONUNIT_SUBJECT_SCALE")
        if subject.library is not None or subject.override_library is not None:
            blockers.add("LINKED_SUBJECT_UNSUPPORTED")
        if self.bpy.context.mode != "OBJECT":
            blockers.add("OBJECT_MODE_REQUIRED")
        specs = _layout_specs(action.preset)
        if len(self.bpy.data.objects) + len(specs) > 10_000:
            blockers.add("SCENE_OBJECT_LIMIT")
        if self._owned:
            blockers.add("LIGHTING_RIG_ALREADY_MANAGED")
        entries = []
        size_factor, spread, casts_shadow = SHADOW_PROFILES[action.shadow_profile]
        for role, azimuth, elevation, size_mul, energy, rgb in specs:
            name = f"{action.name_prefix}_{role}"
            mood_rgb, mood_power = MOOD_STYLES[action.mood].get(role, (rgb, 1.0))
            if self.bpy.data.objects.get(name) is not None or any(
                light.name == name for light in self.bpy.data.lights
            ):
                blockers.add("LIGHT_NAME_COLLISION")
            distance = max(2.0, radius * action.distance_scale)
            az, el = radians(azimuth), radians(elevation)
            direction = [
                cos(el) * cos(az),
                cos(el) * sin(az),
                sin(el),
            ]
            location = [center[i] + distance * direction[i] for i in range(3)]
            offset = (action.target_offsets or {}).get(role, (0.0, 0.0, 0.0))
            aim_point = [center[i] + dimensions[i] * offset[i] for i in range(3)]
            # Blender lights emit along local -Z. Use the original exact
            # M1 angles for the default central target to avoid drift.
            if not any(offset):
                yaw_angle = az + pi / 2
                rotation = [pi / 2 - el, 0.0, atan2(sin(yaw_angle), cos(yaw_angle))]
            else:
                outward = [location[i] - aim_point[i] for i in range(3)]
                horizontal = sqrt(outward[0] ** 2 + outward[1] ** 2)
                if horizontal < 0.001:
                    raise AgentError(ErrorCode.SAFETY_DENIED, "Unsafe vertical light aim")
                aim_az = atan2(outward[1], outward[0])
                aim_el = atan2(outward[2], horizontal)
                yaw_angle = aim_az + pi / 2
                rotation = [
                    pi / 2 - aim_el,
                    0.0,
                    atan2(sin(yaw_angle), cos(yaw_angle)),
                ]
            entries.append(
                {
                    "role": role,
                    "name": name,
                    "location": location,
                    "rotation_euler": rotation,
                    "aim_point": aim_point,
                    "target_offset": list(offset),
                    "energy": float(energy * action.intensity_scale * mood_power),
                    "color": list(mood_rgb),
                    "size": float(max(0.2, radius * size_mul * size_factor)),
                    "spread": float(spread),
                    "use_shadow": casts_shadow,
                }
            )
        plan = {
            "preset": action.preset,
            "mood": action.mood,
            "shadow_profile": action.shadow_profile,
            "target_offsets": {
                key: list(value) for key, value in sorted((action.target_offsets or {}).items())
            },
            "subject_id": snap["object_id"],
            "subject_revision": snap["revision"],
            "scene_revision": scene_revision,
            "center": center,
            "radius": radius,
            "distance_scale": action.distance_scale,
            "intensity_scale": action.intensity_scale,
            "lights": entries,
            "blockers": sorted(blockers),
            "ready": not blockers,
            "source_only": True,
            "render_verified": False,
            "mutation_performed": False,
        }
        plan["lighting_revision"] = revision(plan)
        return subject, snap, plan

    def preview(self, request: Request, action: RigPreview):
        return Result(
            request.request_id, request.command_id, Status.SUCCEEDED, self._plan(action)[2]
        )

    def _cleanup(self, created, before_scene_revision):
        for obj, data in reversed(created):
            if obj is not None and self._in_table(obj):
                self.bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and self._in_lights(data):
                if data.users != 0:
                    raise AgentError(
                        ErrorCode.VERIFICATION_FAILED, "Light data is still referenced"
                    )
                self.bpy.data.lights.remove(data)
        self.bpy.context.view_layer.update()
        if self.inspector.summary()["revision"] != before_scene_revision or any(
            self._in_table(obj) or self._in_lights(data) for obj, data in created
        ):
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Studio lighting cleanup unverified")

    def apply(self, request: Request, action: RigApply):
        subject, subject_before, plan = self._plan(action.preview)
        if plan["lighting_revision"] != action.expected_lighting_revision:
            raise AgentError(ErrorCode.STALE_STATE, "Studio lighting plan changed since preview")
        if not plan["ready"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsafe three-point lighting setup")
        created = []
        try:
            for entry in plan["lights"]:
                data = self.bpy.data.lights.new(entry["name"], "AREA")
                created.append([None, data])
                data.shape = "DISK"
                data.size = entry["size"]
                data.spread = entry["spread"]
                data.use_shadow = entry["use_shadow"]
                data.energy = entry["energy"]
                data.color = entry["color"]
                obj = self.bpy.data.objects.new(entry["name"], data)
                created[-1][0] = obj
                self.bpy.context.scene.collection.objects.link(obj)
                obj.rotation_mode = "XYZ"
                obj.location = entry["location"]
                obj.rotation_euler = entry["rotation_euler"]
                obj.scale = [1.0, 1.0, 1.0]
            self.bpy.context.view_layer.update()
            after = [self._read(obj, data) for obj, data in created]
            expected = {
                "lights": [self._expected(entry) for entry in plan["lights"]],
                "subject_revision": subject_before["revision"],
                "created_count": len(plan["lights"]),
            }
            actual = {
                "lights": after,
                "subject_revision": self.inspector.snapshot(subject)["revision"],
                "created_count": sum(
                    self._in_table(obj) and self._in_lights(data) for obj, data in created
                ),
            }
            checked = compare(expected, actual)
            if checked.matched:
                after_scene_revision = self.inspector.summary()["revision"]
                token = revision(
                    {
                        "before": plan["scene_revision"],
                        "after": after_scene_revision,
                        "light_pointers": [self._pointer(obj) for obj, _ in created],
                    }
                )
                self._owned[token] = {
                    "created": created,
                    "roles": [entry["role"] for entry in plan["lights"]],
                    "before_scene": plan["scene_revision"],
                    "after_scene": after_scene_revision,
                    "subject": subject,
                    "subject_revision": subject_before["revision"],
                    "expected": expected["lights"],
                }
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {
                        "lighting_token": token,
                        "lights_created": len(created),
                        "roles": [entry["role"] for entry in plan["lights"]],
                        "source_only": True,
                        "render_verified": False,
                    },
                    verification=checked.to_dict(),
                )
        except Exception as exc:
            try:
                self._cleanup(created, plan["scene_revision"])
            except Exception as recovery_exc:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Lighting creation rollback unverified"
                ) from recovery_exc
            raise AgentError(
                ErrorCode.EXECUTION_ERROR, "Lighting creation interrupted; state restored"
            ) from exc

        self._cleanup(created, plan["scene_revision"])
        return Result(
            request.request_id,
            request.command_id,
            Status.FAILED,
            {"rolled_back": True, "recovery_verified": True},
            AgentError(ErrorCode.VERIFICATION_FAILED, "Lighting readback mismatch"),
            checked.to_dict(),
        )

    def release(self, request: Request, action: RigRelease):
        owned = self._owned.get(action.expected_lighting_token)
        if owned is None:
            raise AgentError(ErrorCode.STALE_STATE, "Lighting rig is not owned by this session")
        if self.inspector.summary()["revision"] != owned["after_scene"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Scene changed after lighting setup")
        created = owned["created"]
        if any(
            not self._in_table(obj)
            or not self._in_lights(data)
            or not compare(expected, self._read(obj, data)).matched
            for (obj, data), expected in zip(created, owned["expected"], strict=True)
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Managed light was changed or replaced")
        # Removal is only attempted after every light has been checked.
        self._cleanup(created, owned["before_scene"])
        checked = compare(
            {"remaining_owned_lights": 0, "original_scene_restored": True},
            {
                "remaining_owned_lights": sum(
                    self._in_table(obj) or self._in_lights(data) for obj, data in created
                ),
                "original_scene_restored": (
                    self.inspector.summary()["revision"] == owned["before_scene"]
                ),
            },
        )
        if not checked.matched:
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Lighting release readback failed")
        del self._owned[action.expected_lighting_token]
        return Result(
            request.request_id,
            request.command_id,
            Status.VERIFIED,
            {"removed_owned_lights": len(created), "restored_scene": True},
            verification=checked.to_dict(),
        )

    def _live_owned(self, token):
        owned = self._owned.get(token)
        if owned is None:
            raise AgentError(ErrorCode.STALE_STATE, "Unknown or foreign lighting token")
        if self.inspector.summary()["revision"] != owned["after_scene"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Scene changed since lighting setup")
        if self.inspector.snapshot(owned["subject"])["revision"] != owned["subject_revision"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Subject changed since lighting setup")
        if any(
            not self._in_table(obj)
            or not self._in_lights(data)
            or not compare(wanted, self._read(obj, data)).matched
            for (obj, data), wanted in zip(owned["created"], owned["expected"], strict=True)
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Managed light has changed externally")
        return owned

    def _mutate_lights(self, owned, expected):
        previous = [dict(row) for row in owned["expected"]]
        created = owned["created"]

        def write(settings):
            for (_obj, data), want in zip(created, settings, strict=True):
                for key in TUNABLE_FIELDS:
                    value = want[key]
                    setattr(data, key, list(value) if key == "color" else value)

        try:
            write(expected)
            self.bpy.context.view_layer.update()
            actual = [self._read(obj, data) for obj, data in created]
            checked = compare({"lights": expected}, {"lights": actual})
            scene_unchanged = self.inspector.summary()["revision"] == owned["after_scene"]
            if checked.matched and scene_unchanged:
                owned["expected"] = expected
                owned["after_scene"] = self.inspector.summary()["revision"]
                return checked
        except Exception as exc:
            try:
                write(previous)
                self.bpy.context.view_layer.update()
                restored = [self._read(obj, data) for obj, data in created]
                if (
                    not compare({"lights": previous}, {"lights": restored}).matched
                    or self.inspector.summary()["revision"] != owned["after_scene"]
                ):
                    raise AgentError(ErrorCode.VERIFICATION_FAILED, "Light rollback not verified")
            except Exception as rollback_error:
                raise AgentError(
                    ErrorCode.VERIFICATION_FAILED, "Light update recovery is uncertain"
                ) from rollback_error
            raise AgentError(
                ErrorCode.EXECUTION_ERROR, "Light update failed; previous settings restored"
            ) from exc

        # Readback mismatches are verified failures, not successful updates.
        try:
            write(previous)
            self.bpy.context.view_layer.update()
            restored = [self._read(obj, data) for obj, data in created]
            if (
                not compare({"lights": previous}, {"lights": restored}).matched
                or self.inspector.summary()["revision"] != owned["after_scene"]
            ):
                raise AgentError(ErrorCode.VERIFICATION_FAILED, "Light rollback not verified")
        except Exception as exc:
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED, "Light update recovery is uncertain"
            ) from exc
        return checked

    def _tune_plan(self, action: TunePreview):
        owned = self._live_owned(action.token)
        if action.role not in owned["roles"]:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Role not in managed lighting rig")
        index = owned["roles"].index(action.role)
        expected = [dict(item) for item in owned["expected"]]
        expected[index] = expected[index] | action.settings
        plan = {
            "role": action.role,
            "lighting_token": action.token,
            "current_light": owned["expected"][index],
            "proposed_light": expected[index],
            "current_rig": owned["expected"],
            "scene_revision": owned["after_scene"],
            "source_only": True,
            "render_verified": False,
            "mutation_performed": False,
        }
        plan["tuning_revision"] = revision(plan)
        return owned, expected, plan

    def tune_preview(self, request: Request, action: TunePreview):
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self._tune_plan(action)[2],
        )

    def tune_apply(self, request: Request, action: TuneApply):
        owned, expected, plan = self._tune_plan(action.preview)
        if plan["tuning_revision"] != action.expected_tuning_revision:
            raise AgentError(ErrorCode.STALE_STATE, "Light settings changed after preview")
        if plan["current_light"] == plan["proposed_light"]:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Light tuning patch changes nothing")
        checked = self._mutate_lights(owned, expected)
        if not checked.matched:
            return Result(
                request.request_id,
                request.command_id,
                Status.FAILED,
                {"rolled_back": True, "recovery_verified": True},
                AgentError(ErrorCode.VERIFICATION_FAILED, "Light tuning readback mismatch"),
                checked.to_dict(),
            )
        return Result(
            request.request_id,
            request.command_id,
            Status.VERIFIED,
            {
                "lighting_token": action.preview.token,
                "role": action.preview.role,
                "settings_updated": list(action.preview.settings),
                "source_only": True,
                "render_verified": False,
            },
            verification=checked.to_dict(),
        )

    def catalog(self, request: Request, action: StudioPresetCatalog):
        presets = []
        for name in PRESET_DESCRIPTIONS:
            specs = _layout_specs(name)
            presets.append(
                {
                    "preset": name,
                    "description": PRESET_DESCRIPTIONS[name],
                    "light_count": len(specs),
                    "fixtures": [
                        {
                            "role": role,
                            "azimuth_degrees": azimuth,
                            "elevation_degrees": elevation,
                            "size_multiplier": size,
                            "energy_watts": energy,
                            "rgb": list(rgb),
                        }
                        for role, azimuth, elevation, size, energy, rgb in specs
                    ],
                }
            )
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            {
                "presets": presets,
                "source_only": True,
                "render_verified": False,
                "mutation_performed": False,
            },
        )

    def tools(self):
        return [
            Tool(
                "lighting.preset_catalog",
                SafetyClass.READ_ONLY,
                StudioPresetCatalog.parse,
                self.catalog,
            ),
            Tool("lighting.studio_preview", SafetyClass.READ_ONLY, RigPreview.parse, self.preview),
            Tool("lighting.studio_apply", SafetyClass.MUTATION, RigApply.parse, self.apply),
            Tool("lighting.studio_release", SafetyClass.MUTATION, RigRelease.parse, self.release),
            Tool(
                "lighting.tune_preview",
                SafetyClass.READ_ONLY,
                TunePreview.parse,
                self.tune_preview,
            ),
            Tool("lighting.tune_apply", SafetyClass.MUTATION, TuneApply.parse, self.tune_apply),
        ]
