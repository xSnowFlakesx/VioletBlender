# SPDX-FileCopyrightText: 2026 VioletBlender contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""PMX import and model-scoped, non-destructive material organization."""

import json
import os
from collections import Counter
from pathlib import Path

import bpy


TEXTURE_ROLES = {
    "mmd_base_tex": ("Base texture", "texture_rel_path"),
    "mmd_sphere_tex": ("Sphere texture", "sphere_texture_rel_path"),
    "mmd_toon_tex": ("Toon texture", "toon_texture_rel_path"),
}


def model_root(obj):
    from mmd_tools.core.model import Model

    return Model.findRoot(obj) if obj else None


def model_meshes(root):
    from mmd_tools.core.model import Model

    return list(Model(root).meshes())


def model_materials(root):
    return list(dict.fromkeys(slot.material for obj in model_meshes(root)
                              for slot in obj.material_slots if slot.material))


def _canonical(path):
    return os.path.normcase(os.path.realpath(path))


def _image_settings(image):
    return (image.colorspace_settings.name, image.alpha_mode, image.use_view_as_render)


def _is_packed(image):
    return bool(image.packed_file or image.packed_files)


def _texture_path(image):
    return bpy.path.abspath(image.filepath.replace("\\", "/"), library=image.library)


def _texture_candidates(root, material, node, search_directory):
    source_dir = os.path.dirname(root.get("violet_pmx_source", ""))
    relative_property = TEXTURE_ROLES.get(node.name, ("", ""))[1]
    relative = getattr(material.mmd_material, relative_property, "") if relative_property else ""
    relative = relative.replace("\\", "/")
    raw = node.image.filepath.replace("\\", "/")
    exact = [_texture_path(node.image)]
    for directory in (source_dir, search_directory):
        if not directory:
            continue
        if relative:
            exact.append(os.path.join(directory, relative))
    return _unique_paths(exact), os.path.basename(relative or raw)


def _unique_paths(paths):
    unique = []
    seen = set()
    for path in paths:
        if not path:
            continue
        canonical = _canonical(path)
        if canonical not in seen:
            seen.add(canonical)
            unique.append(path)
    return unique


def _texture_index(search_directory):
    index = {}
    if search_directory and os.path.isdir(search_directory):
        # os.walk yields the search root itself before its descendants.
        for directory, _, filenames in os.walk(search_directory):
            filenames.sort(key=str.casefold)
            for filename in filenames:
                index.setdefault(filename.casefold(), []).append(os.path.join(directory, filename))
    return {name: _unique_paths(paths) for name, paths in index.items()}


def _resolve_texture(root, material, node, search_directory, search_index):
    exact, basename = _texture_candidates(root, material, node, search_directory)
    resolved = next((path for path in exact if os.path.isfile(path)), None)
    if resolved:
        return resolved, []
    matches = search_index.get(basename.casefold(), []) if basename else []
    if len(matches) == 1:
        return matches[0], []
    return None, matches if len(matches) > 1 else []


def organize_materials(root, search_directory=""):
    """Repair paths and reuse equivalent images without merging material slots.

    Images with different color space/alpha settings remain distinct. Materials,
    node links, PMX IDs and morph references are never reordered or recreated.
    """
    search_directory = bpy.path.abspath(search_directory) if search_directory else ""
    root["violet_texture_search_directory"] = search_directory
    search_index = _texture_index(search_directory)

    images = {}
    for image in bpy.data.images:
        if (image.source == "FILE" and os.path.isfile(_texture_path(image))
                and not image.get("violet_missing_texture", False)):
            key = (_canonical(_texture_path(image)), _image_settings(image))
            images.setdefault(key, image)

    repaired = reused = 0
    for material in model_materials(root):
        if not material.use_nodes or not material.node_tree or material.library:
            continue
        for node in material.node_tree.nodes:
            if node.type != "TEX_IMAGE" or not node.image:
                continue
            if node.name in TEXTURE_ROLES:
                node.label = TEXTURE_ROLES[node.name][0]
            image = node.image
            if image.source != "FILE" or _is_packed(image):
                continue
            resolved, _ = _resolve_texture(root, material, node, search_directory, search_index)
            if not resolved:
                continue
            settings = list(_image_settings(image))
            # MMD Tools marks its blank missing-file image with alpha_mode NONE.
            # When that file returns, use the decoded image's alpha convention;
            # a real source image's NONE/PREMUL setting remains authoritative.
            automatic_missing_alpha = (image.get("violet_missing_texture", False)
                                       and image.alpha_mode == "NONE")
            probe_image = None
            if automatic_missing_alpha:
                try:
                    probe_image = bpy.data.images.load(resolved, check_existing=False)
                except RuntimeError:
                    continue
                settings[1] = probe_image.alpha_mode
            key = (_canonical(resolved), tuple(settings))
            canonical_image = images.get(key)
            if canonical_image is None:
                if automatic_missing_alpha:
                    canonical_image = probe_image
                else:
                    try:
                        canonical_image = bpy.data.images.load(resolved, check_existing=False)
                    except RuntimeError:
                        continue
                canonical_image.colorspace_settings.name = settings[0]
                if not automatic_missing_alpha:
                    canonical_image.alpha_mode = settings[1]
                canonical_image.use_view_as_render = image.use_view_as_render
                images[key] = canonical_image
            elif probe_image:
                # The probe was only needed to determine native alpha handling.
                bpy.data.images.remove(probe_image)
            if not os.path.isfile(_texture_path(image)) or image.get("violet_missing_texture", False):
                repaired += 1
            elif canonical_image != image:
                reused += 1
            node.image = canonical_image
            # Keep MMD export metadata synchronized with repaired sphere/toon paths.
            if node.name == "mmd_toon_tex" and not material.mmd_material.is_shared_toon_texture:
                material.mmd_material.toon_texture = resolved

    report = audit_materials(root, search_directory)
    report.update(repaired_textures=repaired, reused_images=reused)
    write_report(root, report)
    return report


def _socket_report(node, name):
    socket = node.inputs.get(name) if node else None
    if socket is None:
        return None
    value = socket.default_value
    if isinstance(value, (float, int)):
        value = float(value)
    elif hasattr(value, "__iter__"):
        value = [float(component) for component in value]
    return {"default": value, "linked": socket.is_linked}


def audit_materials(root, search_directory=""):
    meshes = model_meshes(root)
    if not search_directory:
        search_directory = root.get("violet_texture_search_directory", "")
    search_directory = bpy.path.abspath(search_directory) if search_directory else ""
    search_index = _texture_index(search_directory)
    material_slots = {}
    for obj in meshes:
        face_counts = Counter(face.material_index for face in obj.data.polygons)
        for index, slot in enumerate(obj.material_slots):
            if slot.material:
                material_slots.setdefault(slot.material, []).append(
                    {"mesh": obj.name, "slot": index, "faces": face_counts[index]})
    rows = []
    missing = set()
    ambiguous = []
    for material in model_materials(root):
        textures = []
        if material.node_tree:
            for node in material.node_tree.nodes:
                if node.type != "TEX_IMAGE" or not node.image:
                    continue
                image = node.image
                path = _texture_path(image) if image.source == "FILE" else ""
                status = "packed" if _is_packed(image) else (
                    "generated" if image.source != "FILE" else (
                        "found" if os.path.isfile(path) and not image.get("violet_missing_texture", False) else "missing"))
                if status == "missing":
                    missing.add(path)
                textures.append({"role": node.label or node.name, "image": image.name,
                                 "path": path, "status": status,
                                 "color_space": image.colorspace_settings.name,
                                 "alpha_mode": image.alpha_mode})
                if status == "missing" and search_index:
                    candidates = _resolve_texture(root, material, node, search_directory,
                                                  search_index)[1]
                    if candidates:
                        ambiguous.append({"material": material.name,
                                          "role": node.label or node.name,
                                          "image": image.name,
                                          "basename": os.path.basename(path or image.filepath),
                                          "candidates": candidates})
        shader = material.node_tree.nodes.get("mmd_shader") if material.node_tree else None
        render_property = ("surface_render_method" if hasattr(material, "surface_render_method")
                           else "blend_method" if hasattr(material, "blend_method") else None)
        rows.append({"material": material.name,
                     "source_name_j": material.get("violet_pmx_name_j", material.mmd_material.name_j),
                     "source_name_e": material.get("violet_pmx_name_e", material.mmd_material.name_e),
                     "mmd_name_j": material.mmd_material.name_j, "alpha": material.mmd_material.alpha,
                     "shader_alpha": _socket_report(shader, "Alpha"),
                     "shader_base_alpha": _socket_report(shader, "Base Alpha"),
                     "render_method": getattr(material, render_property) if render_property else None,
                     "render_method_property": render_property,
                     "double_sided": material.mmd_material.is_double_sided,
                     "slots": material_slots.get(material, []), "textures": textures})
    return {"model": root.name, "source": root.get("violet_pmx_source", ""),
            "meshes": len(meshes), "material_count": len(rows),
            "missing_textures": sorted(missing), "ambiguous_textures": ambiguous, "materials": rows}


def write_report(root, report):
    text = bpy.data.texts.get(root.get("violet_material_report", ""))
    if text is None:
        text = bpy.data.texts.new("Violet Materials - " + root.name)
        root["violet_material_report"] = text.name
    text.clear()
    text.write(json.dumps(report, ensure_ascii=False, indent=2))
    root["violet_missing_textures"] = len(report["missing_textures"])
    root["violet_material_count"] = report["material_count"]


def pack_textures(root):
    images = {node.image for mat in model_materials(root) if mat.node_tree
              for node in mat.node_tree.nodes if node.type == "TEX_IMAGE" and node.image}
    packed = 0
    failures = []
    for image in images:
        if _is_packed(image):
            continue
        if image.source == "FILE" and (not os.path.isfile(_texture_path(image))
                                       or image.get("violet_missing_texture", False)):
            failures.append(image.filepath)
            continue
        try:
            image.pack()
            packed += 1
        except RuntimeError:
            failures.append(image.filepath or image.name)
    write_report(root, audit_materials(root))
    return packed, failures


def _validate_model(model):
    from mmd_tools.core import pmx

    if not model.vertices or not model.faces:
        raise pmx.InvalidFileError("PMX contains no mesh")
    if any(len(face) != 3 or any(index < 0 or index >= len(model.vertices) for index in face)
           for face in model.faces):
        raise pmx.InvalidFileError("Invalid PMX face indices")
    if (any(mat.vertex_count < 0 or mat.vertex_count % 3 for mat in model.materials) or
            sum(mat.vertex_count for mat in model.materials) != len(model.faces) * 3):
        raise pmx.InvalidFileError("PMX material face counts do not match geometry")
    for material in model.materials:
        indices = [material.texture, material.sphere_texture]
        if not material.is_shared_toon_texture:
            indices.append(material.toon_texture)
        if any(index < -1 or index >= len(model.textures) for index in indices):
            raise pmx.InvalidFileError("Invalid PMX texture index")
    for vertex in model.vertices:
        if any(index < -1 or index >= len(model.bones) for index in vertex.weight.bones):
            raise pmx.InvalidFileError("Invalid PMX bone weight index")


def import_pmx(context, filepath, scale=0.08, import_physics=False, pack=False):
    from mmd_tools.core import pmx
    from mmd_tools.core.pmx.importer import PMXImporter

    filepath = os.path.abspath(bpy.path.abspath(filepath))
    if Path(filepath).suffix.lower() != ".pmx":
        raise ValueError("Select a .pmx model")
    model = pmx.load(filepath)
    _validate_model(model)
    # Read/validate before touching the scene. Roll back newly created data on failure.
    collections = (bpy.data.objects, bpy.data.meshes, bpy.data.armatures,
                   bpy.data.materials, bpy.data.images, bpy.data.node_groups,
                   bpy.data.texts, bpy.data.collections)
    snapshots = [set(data) for data in collections]
    active_collection = context.view_layer.active_layer_collection
    active_object = context.view_layer.objects.active
    selected = list(context.selected_objects)
    had_physics_world = context.scene.rigidbody_world is not None
    try:
        collection = bpy.data.collections.new("PMX - " + (model.name or Path(filepath).stem))
        context.scene.collection.children.link(collection)
        context.view_layer.update()
        context.view_layer.active_layer_collection = context.view_layer.layer_collection.children[collection.name]
        types = {"MESH", "ARMATURE", "MORPHS", "DISPLAY"}
        if import_physics:
            types.add("PHYSICS")
        PMXImporter().execute(pmx=model, types=types, scale=scale, clean_model=False,
                              remove_doubles=False, fix_bone_order=False,
                              rename_LR_bones=False, fix_ik_links=False,
                              apply_bone_fixed_axis=False)
        roots = [obj for obj in bpy.data.objects if obj not in snapshots[0] and obj.mmd_type == "ROOT"]
        if len(roots) != 1:
            raise RuntimeError("PMX importer did not create a model root")
        root = roots[0]
        root["violet_pmx_source"] = filepath
        root["violet_pmx_version"] = "0.2.0"
        collection["violet_pmx_root"] = root.name
        for material, source in zip(model_materials(root), model.materials, strict=True):
            # MMD Tools requires unique editable names. Keep exact PMX names separately.
            material["violet_pmx_name_j"] = source.name
            material["violet_pmx_name_e"] = source.name_e
        report = organize_materials(root)
        if pack:
            pack_textures(root)
            report = audit_materials(root)
        return root, report
    except Exception:
        if context.object and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        if not had_physics_world and context.scene.rigidbody_world is not None:
            bpy.ops.rigidbody.world_remove()
        for data, before in zip(collections, snapshots):
            for item in set(data) - before:
                data.remove(item, do_unlink=True)
        for obj in selected:
            if obj.name in context.view_layer.objects:
                obj.select_set(True)
        context.view_layer.objects.active = active_object
        raise
    finally:
        context.view_layer.active_layer_collection = active_collection
