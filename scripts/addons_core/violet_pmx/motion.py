# SPDX-FileCopyrightText: 2026 VioletBlender contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transactional import of VMD bone and assembled vertex-shape-key motion."""

import json
import math
import os
import struct

import bpy


VMD_HEADER_SIZE = 50
VMD_BONE_RECORD_SIZE = 111
VMD_MORPH_RECORD_SIZE = 23
MAX_RECORDS_PER_SECTION = 10_000_000


class NoMatchingChannels(ValueError):
    def __init__(self, message, report):
        super().__init__(message)
        self.report = report


def _read_required_sections(filepath):
    """Validate the VMD header, bone section and morph section without scene access."""
    with open(filepath, "rb") as stream:
        data = stream.read()

    if len(data) < VMD_HEADER_SIZE:
        raise ValueError("VMD file is shorter than its 50-byte header")
    if not data[:30].startswith(b"Vocaloid Motion Data 0002"):
        raise ValueError("VMD file has an unsupported or invalid header")

    def read_count(offset, section, record_size):
        if offset + 4 > len(data):
            raise ValueError(f"VMD {section} section is missing its record count")
        count, = struct.unpack_from("<I", data, offset)
        if count > MAX_RECORDS_PER_SECTION:
            raise ValueError(f"VMD {section} record count is unreasonable ({count})")
        records_start = offset + 4
        remaining = len(data) - records_start
        if count > remaining // record_size:
            raise ValueError(f"VMD {section} section is truncated")
        return count, records_start

    bone_count, offset = read_count(VMD_HEADER_SIZE, "bone", VMD_BONE_RECORD_SIZE)
    for index in range(bone_count):
        _, x, y, z, qx, qy, qz, qw = struct.unpack_from("<I3f4f", data, offset + 15)
        if not all(math.isfinite(value) for value in (x, y, z, qx, qy, qz, qw)):
            raise ValueError(f"VMD bone record {index} contains a non-finite coordinate or quaternion")
        offset += VMD_BONE_RECORD_SIZE

    morph_count, offset = read_count(offset, "morph", VMD_MORPH_RECORD_SIZE)
    for index in range(morph_count):
        _, weight = struct.unpack_from("<If", data, offset + 15)
        if not math.isfinite(weight):
            raise ValueError(f"VMD morph record {index} contains a non-finite weight")
        offset += VMD_MORPH_RECORD_SIZE

    return bone_count, morph_count


def _resolve_scale(root, override_enabled, override_value):
    if override_enabled:
        scale = float(override_value)
        source = "user override"
    elif "violet_pmx_scale" in root:
        scale = float(root["violet_pmx_scale"])
        source = "saved PMX import scale"
    else:
        scale = float(root.empty_display_size) * 0.2
        source = "inferred from root.empty_display_size × 0.2"

    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Motion scale must be a positive finite number")
    warning = None
    if source.startswith("inferred"):
        warning = "This older PMX model has no saved import scale; the motion scale was inferred."
    return scale, source, warning


def _model_morph_types(root):
    result = {}
    if root is None:
        return result
    for collection_name, morph_type in (
        ("vertex_morphs", "vertex"),
        ("uv_morphs", "uv"),
        ("bone_morphs", "bone"),
        ("material_morphs", "material"),
        ("group_morphs", "group"),
    ):
        for morph in getattr(root.mmd_root, collection_name, ()):
            result.setdefault(morph.name, set()).add(morph_type)
    return result


def _animation_data(id_block):
    return getattr(id_block, "animation_data", None)


def _preflight_target(id_block, label, motion_paths):
    anim_data = _animation_data(id_block)
    if anim_data is not None and any(len(track.strips) for track in anim_data.nla_tracks):
        raise ValueError(f"{label} has NLA strips; move or remove them before importing motion")
    if anim_data is not None:
        conflicts = sorted({driver.data_path for driver in anim_data.drivers
                            if not driver.mute and driver.data_path in motion_paths})
        if conflicts:
            raise ValueError(f"{label} has active drivers on VMD channels: {', '.join(conflicts)}")


def _motion_paths(armature, bone_map, matched_bones, parsed, motion_meshes,
                  mesh_shape_keys, matched_morph_names):
    paths = {}
    if armature is not None and matched_bones:
        armature_paths = set()
        for name in matched_bones:
            pose_bone = bone_map[name]
            armature_paths.add(f'pose.bones["{pose_bone.name}"].location')
            rotation_path = {
                "QUATERNION": "rotation_quaternion",
                "AXIS_ANGLE": "rotation_axis_angle",
            }.get(pose_bone.rotation_mode, "rotation_euler")
            armature_paths.add(f'pose.bones["{pose_bone.name}"].{rotation_path}')
        for key_frame in parsed.propertyAnimation:
            for bone_name, _enabled in key_frame.ik_states:
                pose_bone = bone_map.get(bone_name)
                if pose_bone is not None:
                    armature_paths.add(f'pose.bones["{pose_bone.name}"].mmd_ik_toggle')
        paths[armature] = armature_paths

    for mesh in motion_meshes:
        key = mesh.data.shape_keys
        names = mesh_shape_keys[mesh] & set(matched_morph_names)
        paths[key] = {
            f'key_blocks["{name}"].value' for name in names
        }
    return paths


def _snapshot_target(id_block, label):
    anim_data = _animation_data(id_block)
    anim_values = {}
    if anim_data is not None:
        for prop in anim_data.bl_rna.properties:
            if prop.identifier in {"rna_type", "action", "action_slot", "drivers", "nla_tracks"}:
                continue
            if prop.is_readonly or prop.type not in {"BOOLEAN", "ENUM", "FLOAT", "INT", "STRING"}:
                continue
            try:
                value = getattr(anim_data, prop.identifier)
                anim_values[prop.identifier] = tuple(value) if prop.is_array else value
            except (AttributeError, TypeError, ValueError, RuntimeError):
                pass
    return {
        "id_block": id_block,
        "label": label,
        "had_animation_data": anim_data is not None,
        "action": anim_data.action if anim_data else None,
        "action_slot": getattr(anim_data, "action_slot", None) if anim_data else None,
        "fake_user": anim_data.action.use_fake_user if anim_data and anim_data.action else None,
        "anim_values": anim_values,
    }


def _restore_target(snapshot):
    id_block = snapshot["id_block"]
    if not snapshot["had_animation_data"]:
        if id_block.animation_data is not None:
            id_block.animation_data_clear()
        return
    anim_data = id_block.animation_data_create()
    old_action = snapshot["action"]
    anim_data.action = old_action
    if hasattr(anim_data, "action_slot"):
        try:
            anim_data.action_slot = snapshot["action_slot"]
        except (TypeError, ValueError, RuntimeError):
            pass
    for name, value in snapshot["anim_values"].items():
        try:
            setattr(anim_data, name, value)
        except (AttributeError, TypeError, ValueError, RuntimeError):
            pass
    if old_action is not None and snapshot["fake_user"] is not None:
        old_action.use_fake_user = snapshot["fake_user"]


def _snapshot_pose(armature):
    if armature is None:
        return None
    result = {}
    for pose_bone in armature.pose.bones:
        entry = {
            "location": tuple(pose_bone.location),
            "rotation_mode": pose_bone.rotation_mode,
            "rotation_euler": tuple(pose_bone.rotation_euler),
            "rotation_quaternion": tuple(pose_bone.rotation_quaternion),
            "rotation_axis_angle": tuple(pose_bone.rotation_axis_angle),
            "scale": tuple(pose_bone.scale),
        }
        if hasattr(pose_bone, "mmd_ik_toggle"):
            entry["mmd_ik_toggle"] = pose_bone.mmd_ik_toggle
        result[pose_bone.name] = entry
    return result


def _snapshot_constraints(root, armature):
    from mmd_tools.core.model import FnModel

    result = []
    for obj in FnModel.iterate_child_objects(root):
        for constraint in obj.constraints:
            result.append((constraint, constraint.influence, constraint.mute))
    if armature is not None:
        for pose_bone in armature.pose.bones:
            for constraint in pose_bone.constraints:
                result.append((constraint, constraint.influence, constraint.mute))
    return result


def _restore_constraints(snapshots):
    for constraint, influence, mute in snapshots:
        constraint.influence = influence
        constraint.mute = mute


def _restore_pose(armature, snapshot):
    if armature is None or snapshot is None:
        return
    for name, entry in snapshot.items():
        pose_bone = armature.pose.bones.get(name)
        if pose_bone is None:
            continue
        pose_bone.location = entry["location"]
        pose_bone.rotation_mode = entry["rotation_mode"]
        pose_bone.rotation_euler = entry["rotation_euler"]
        pose_bone.rotation_quaternion = entry["rotation_quaternion"]
        pose_bone.rotation_axis_angle = entry["rotation_axis_angle"]
        pose_bone.scale = entry["scale"]
        if "mmd_ik_toggle" in entry:
            pose_bone.mmd_ik_toggle = entry["mmd_ik_toggle"]


def _snapshot_shape_keys(shape_keys):
    if shape_keys is None:
        return None
    return {
        key.name: (key.value, key.slider_min, key.slider_max)
        for key in shape_keys.key_blocks
    }


def _restore_shape_keys(shape_keys, snapshot):
    if snapshot is None or shape_keys is None:
        return
    for name, (value, slider_min, slider_max) in snapshot.items():
        key = shape_keys.key_blocks.get(name)
        if key is not None:
            key.value = value
            key.slider_min = slider_min
            key.slider_max = slider_max


def _all_actions():
    return set(bpy.data.actions)


def _action_curves(action):
    return list(action.fcurves) if action is not None else []


def write_motion_report(root, report):
    text_name = root.get("violet_vmd_report")
    text = bpy.data.texts.get(text_name) if text_name else None
    if text is None:
        text = bpy.data.texts.new(f"Violet VMD Report - {root.name}")
        root["violet_vmd_report"] = text.name
    text.clear()
    text.write(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return text


def import_vmd(context, root, filepath, *, start_frame=1, override_scale=False,
               scale=0.08, update_timeline=True):
    """Import matched bones and shape keys, restoring all edits if import fails."""
    from mmd_tools.core.model import FnModel
    from mmd_tools.core.vmd import File
    from mmd_tools.core.vmd.importer import VMDImporter
    from mmd_tools.utils import makePmxBoneMap

    filepath = os.path.abspath(bpy.path.abspath(filepath))
    if os.path.splitext(filepath)[1].lower() != ".vmd":
        raise ValueError("Select a .vmd motion file")
    if not isinstance(start_frame, int) or start_frame < 0:
        raise ValueError("Start frame must be a non-negative integer")
    bone_count, morph_count = _read_required_sections(filepath)
    parsed = File()
    parsed.load(filepath=filepath)

    armature = FnModel.find_armature_object(root)
    meshes = [mesh for mesh in FnModel.iterate_mesh_objects(root)
              if FnModel.find_root_object(mesh) == root]
    bone_map = makePmxBoneMap(armature) if armature is not None else {}
    motion_bone_names = set(parsed.boneAnimation.keys())
    matched_bones = sorted(motion_bone_names & set(bone_map))
    unmatched_bones = sorted(motion_bone_names - set(bone_map))

    mesh_shape_keys = {}
    all_shape_names = set()
    for mesh in meshes:
        shape_keys = mesh.data.shape_keys
        names = set(shape_keys.key_blocks.keys()) - {"Basis"} if shape_keys else set()
        mesh_shape_keys[mesh] = names
        all_shape_names.update(names)
    motion_morph_names = set(parsed.shapeKeyAnimation.keys())
    matched_morph_names = sorted(motion_morph_names & all_shape_names)
    unmatched_morphs = sorted(motion_morph_names - all_shape_names)
    known_morph_types = _model_morph_types(root)
    requires_assembly = [
        {"name": name, "types": sorted(known_morph_types[name])}
        for name in unmatched_morphs if name in known_morph_types
    ]
    unmatched_morphs = [
        {"name": name, "pmx_types": sorted(known_morph_types[name]) if name in known_morph_types else []}
        for name in unmatched_morphs
    ]

    matched_morph_set = set(matched_morph_names)
    model_mesh_set = set(meshes)
    motion_meshes = []
    seen_shape_keys = set()
    for mesh in meshes:
        shape_keys = mesh.data.shape_keys
        if shape_keys is None or not (mesh_shape_keys[mesh] & matched_morph_set):
            continue
        if shape_keys not in seen_shape_keys:
            seen_shape_keys.add(shape_keys)
            motion_meshes.append(mesh)

    for mesh in motion_meshes:
        shape_keys = mesh.data.shape_keys
        external_users = [obj.name for obj in bpy.data.objects
                          if obj.type == "MESH" and obj not in model_mesh_set
                          and obj.data.shape_keys == shape_keys]
        if external_users:
            raise ValueError(
                f"Shape Key data used by {mesh.name} is also linked to mesh object(s) "
                f"outside this PMX model: {', '.join(sorted(external_users))}"
            )

    targets = []
    if matched_bones and armature is not None:
        targets.append((armature, f"{armature.name} (armature)"))
    for mesh in motion_meshes:
        targets.append((mesh.data.shape_keys, f"{mesh.name} (shape keys)"))

    motion_report = {
        "format": "VMD",
        "source": filepath,
        "source_bone_records": bone_count,
        "source_morph_records": morph_count,
        "start_frame": start_frame,
        "fps": 30,
        "scale": None,
        "scale_source": None,
        "matched_bones": matched_bones,
        "unmatched_bones": unmatched_bones,
        "matched_morphs": matched_morph_names,
        "unmatched_morphs": unmatched_morphs,
        "morphs_requiring_assembly": requires_assembly,
        "imported_targets": [],
        "preserved_actions": [],
        "frame_range": None,
        "warnings": [],
    }
    if not targets:
        motion_report["warnings"].append("No VMD bone or vertex shape-key channels match this model.")
        raise NoMatchingChannels("No matching bone or vertex shape-key channels", motion_report)

    matching_frames = [key.frame_number
                       for name in matched_bones
                       for key in parsed.boneAnimation[name]]
    matching_frames.extend(key.frame_number
                           for name in matched_morph_names
                           for key in parsed.shapeKeyAnimation[name])
    if matched_bones:
        matching_frames.extend(
            key_frame.frame_number
            for key_frame in parsed.propertyAnimation
            if any(bone_name in bone_map for bone_name, _enabled in key_frame.ik_states)
        )
    frame_hard_max = context.scene.bl_rna.properties["frame_end"].hard_max
    if matching_frames and start_frame + max(matching_frames) > frame_hard_max:
        raise ValueError(
            f"A matched VMD keyframe exceeds Blender's scene frame limit ({frame_hard_max})"
        )

    resolved_scale, scale_source, scale_warning = _resolve_scale(root, override_scale, scale)
    motion_report["scale"] = resolved_scale
    motion_report["scale_source"] = scale_source
    if scale_warning:
        motion_report["warnings"].append(scale_warning)

    expected_paths = _motion_paths(armature, bone_map, matched_bones, parsed,
                                   motion_meshes, mesh_shape_keys, matched_morph_names)
    for id_block, label in targets:
        _preflight_target(id_block, label, expected_paths.get(id_block, set()))

    action_snapshots = [_snapshot_target(id_block, label) for id_block, label in targets]
    pose_snapshot = _snapshot_pose(armature) if armature is not None and matched_bones else None
    constraint_snapshots = _snapshot_constraints(root, armature) if matched_bones else []
    shape_snapshots = {
        mesh.data.shape_keys: _snapshot_shape_keys(mesh.data.shape_keys)
        for mesh in motion_meshes
    }
    action_ids_before = _all_actions()
    text_ids_before = set(bpy.data.texts)
    scene = context.scene
    scene_snapshot = {
        "frame_current": scene.frame_current,
        "frame_subframe": scene.frame_subframe,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "fps": scene.render.fps,
        "fps_base": scene.render.fps_base,
    }
    report_text_name_before = root.get("violet_vmd_report")
    old_report_text = bpy.data.texts.get(report_text_name_before) if report_text_name_before else None
    old_report_body = old_report_text.as_string() if old_report_text else None

    try:
        # Detach previous actions so VMDImporter creates clean actions instead of
        # silently appending curves to an existing action.
        for snapshot in action_snapshots:
            anim_data = _animation_data(snapshot["id_block"])
            if anim_data is not None:
                anim_data.action = None

        scene.frame_current = start_frame
        importer = VMDImporter(
            filepath, scale=resolved_scale, bone_mapper=makePmxBoneMap,
            frame_margin=0, use_nla=False,
            convert_mmd_camera=False, convert_mmd_light=False,
        )
        if matched_bones and armature is not None:
            importer.assign(armature)
        for mesh in motion_meshes:
            importer.assign(mesh)

        actual_frames = []
        for snapshot in action_snapshots:
            target_id = snapshot["id_block"]
            anim_data = _animation_data(target_id)
            new_action = anim_data.action if anim_data else None
            if new_action is None or new_action == snapshot["action"]:
                raise RuntimeError(f"VMD importer did not create a new action for {snapshot['label']}")
            if hasattr(anim_data, "action_blend_type"):
                anim_data.action_blend_type = 'REPLACE'
            if hasattr(anim_data, "action_influence"):
                anim_data.action_influence = 1.0
            curves = _action_curves(new_action)
            if not curves:
                raise RuntimeError(f"VMD importer created no curves for {snapshot['label']}")
            for curve in curves:
                actual_frames.extend(point.co.x for point in curve.keyframe_points)
            old_action = snapshot["action"]
            if old_action is not None:
                old_action.use_fake_user = True
                motion_report["preserved_actions"].append({
                    "target": snapshot["label"],
                    "name": old_action.name,
                    "fake_user": True,
                })
            motion_report["imported_targets"].append({
                "target": snapshot["label"],
                "action": new_action.name,
                "fcurves": len(curves),
            })

        if not actual_frames:
            raise RuntimeError("VMD importer created no keyframes")
        scene.frame_set(start_frame)
        frame_start = min(actual_frames)
        frame_end = max(actual_frames)
        motion_report["frame_range"] = [int(math.floor(frame_start)), int(math.ceil(frame_end))]
        scene.render.fps = 30
        scene.render.fps_base = 1.0
        if update_timeline:
            scene.frame_start, scene.frame_end = motion_report["frame_range"]

        write_motion_report(root, motion_report)
        return motion_report
    except Exception:
        for snapshot in action_snapshots:
            _restore_target(snapshot)
        scene.frame_start = scene_snapshot["frame_start"]
        scene.frame_end = scene_snapshot["frame_end"]
        scene.render.fps = scene_snapshot["fps"]
        scene.render.fps_base = scene_snapshot["fps_base"]
        scene.frame_set(scene_snapshot["frame_current"],
                        subframe=scene_snapshot["frame_subframe"])
        _restore_pose(armature, pose_snapshot)
        for shape_keys, snapshot in shape_snapshots.items():
            _restore_shape_keys(shape_keys, snapshot)
        _restore_constraints(constraint_snapshots)
        if report_text_name_before is None:
            if "violet_vmd_report" in root:
                del root["violet_vmd_report"]
        else:
            root["violet_vmd_report"] = report_text_name_before
            if old_report_text is not None:
                old_report_text.clear()
                old_report_text.write(old_report_body or "")
        for action in set(bpy.data.actions) - action_ids_before:
            bpy.data.actions.remove(action)
        for text in set(bpy.data.texts) - text_ids_before:
            bpy.data.texts.remove(text)
        raise
