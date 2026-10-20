# SPDX-FileCopyrightText: 2026 VioletBlender contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transactional, model-scoped Eevee Toon 0.4 material outputs."""

import uuid

import bpy

from . import workflow


OWNER_KEY = "violet_toon_owner"
SCHEMA_KEY = "violet_toon_schema"
NODE_OWNER_KEY = "violet_toon_node_owner"
NODE_ROLE_KEY = "violet_toon_node_role"
GROUP_OWNER_KEY = "violet_toon_group_owner"
GROUP_SCHEMA_KEY = "violet_toon_group_schema"
SCHEMA = 1
ROLES = ("ramp_group", "multiply", "emission", "transparent", "mix", "eevee_output")
GROUP_ROLES = ("diffuse", "shader_to_rgb", "rgb_to_bw", "ramp", "group_output")


def _tag(node, owner, role):
    node[NODE_OWNER_KEY] = owner
    node[NODE_ROLE_KEY] = role


def _role_nodes(nodes, owner):
    result = {}
    unexpected = []
    for node in nodes:
        if NODE_OWNER_KEY not in node:
            continue
        if node.get(NODE_OWNER_KEY) != owner:
            raise ValueError(f"Material contains a Toon node owned by another model: {node.name}")
        role = node.get(NODE_ROLE_KEY)
        if role not in ROLES or role in result:
            unexpected.append(node.name)
        else:
            result[role] = node
    if unexpected:
        raise ValueError("The owned Toon graph contains unknown or duplicate nodes: " +
                         ", ".join(unexpected))
    return result


def _outputs(material):
    return [node for node in material.node_tree.nodes
            if node.type == 'OUTPUT_MATERIAL']


def _cycles_output(material):
    outputs = [node for node in _outputs(material) if node.target in {'ALL', 'CYCLES'}]
    active_cycles = [node for node in outputs if node.target == 'CYCLES' and node.is_active_output]
    active_all = [node for node in outputs if node.target == 'ALL' and node.is_active_output]
    selected = active_cycles or active_all
    if len(selected) != 1:
        raise ValueError(f"{material.name} must have exactly one active original Cycles output")
    return selected[0]


def _local_materials(root):
    meshes = [obj for obj in workflow.model_meshes(root)
              if obj.type == 'MESH' and workflow.model_root(obj) == root]
    if not meshes:
        raise ValueError("The selected PMX model has no local mesh objects")
    if root.library is not None or root.is_library_indirect:
        raise ValueError("The PMX model root must be editable and local")
    materials = list(dict.fromkeys(slot.material for obj in meshes
                                   for slot in obj.material_slots if slot.material))
    if not materials:
        raise ValueError("The selected PMX model has no materials")
    mesh_set = set(meshes)
    for material in materials:
        if material.library is not None or material.is_library_indirect:
            raise ValueError(f"Material {material.name} is linked and cannot be edited")
        external_users = [obj.name for obj in bpy.data.objects if obj not in mesh_set and
                          any(slot.material == material for slot in obj.material_slots)]
        if external_users:
            raise ValueError(f"Material {material.name} is also used outside this model: " +
                             ", ".join(external_users[:4]))
    return meshes, materials


def _validate_base_material(material):
    if not material.use_nodes or material.node_tree is None:
        raise ValueError(f"Material {material.name} must use nodes")
    shader = material.node_tree.nodes.get("mmd_shader")
    if shader is None or shader.type != 'GROUP':
        raise ValueError(f"Material {material.name} has no MMD Tools mmd_shader node")
    if shader.outputs.get("Color") is None or shader.outputs.get("Alpha") is None:
        raise ValueError(f"Material {material.name} needs mmd_shader Color and Alpha outputs")
    _cycles_output(material)
    return shader


def _material_preflight(material, owner=None):
    shader = _validate_base_material(material)
    outputs = [node for node in _outputs(material) if node.target == 'EEVEE']
    tagged = _role_nodes(material.node_tree.nodes, owner) if owner else None
    if owner is None:
        if outputs:
            raise ValueError(f"Material {material.name} already has an Eevee output")
        if any(NODE_OWNER_KEY in node for node in material.node_tree.nodes):
            raise ValueError(f"Material {material.name} contains an unmanaged Violet Toon graph")
    else:
        if tagged is None or set(tagged) != set(ROLES):
            raise ValueError(f"Material {material.name} has an incomplete owned Toon graph")
        if len(outputs) != 1 or outputs[0] != tagged["eevee_output"]:
            raise ValueError(f"Material {material.name} has an unexpected Eevee output")
    return shader


def _group_nodes(group, owner):
    result = {}
    for node in group.nodes:
        role = node.get(NODE_ROLE_KEY)
        if node.get(NODE_OWNER_KEY) != owner or role not in GROUP_ROLES or role in result:
            raise ValueError(f"Owned Toon ramp group {group.name} was edited")
        result[role] = node
    if set(result) != set(GROUP_ROLES):
        raise ValueError(f"Owned Toon ramp group {group.name} is incomplete")
    return result


def _group_instances(group):
    instances = []
    for datablock in (*bpy.data.materials, *bpy.data.worlds, *bpy.data.lights,
                      *bpy.data.scenes, *getattr(bpy.data, "linestyles", ())):
        tree = getattr(datablock, "node_tree", None)
        if tree is None:
            continue
        for node in tree.nodes:
            if node.type == 'GROUP' and node.node_tree == group:
                instances.append((datablock, node))
    for tree in bpy.data.node_groups:
        if tree == group:
            continue
        for node in tree.nodes:
            if node.type == 'GROUP' and node.node_tree == group:
                instances.append((tree, node))
    return instances


def _link_signature(tree, role_by_node, owned_roles=None):
    owned_roles = set(role_by_node.values()) if owned_roles is None else set(owned_roles)
    owned_nodes = {node for node, role in role_by_node.items() if role in owned_roles}
    def socket_key(socket, sockets):
        duplicates = [candidate for candidate in sockets if candidate.name == socket.name]
        return socket.identifier if len(duplicates) > 1 else socket.name

    return {(role_by_node.get(link.from_node, link.from_node.name),
             socket_key(link.from_socket, link.from_node.outputs),
             role_by_node.get(link.to_node, link.to_node.name),
             socket_key(link.to_socket, link.to_node.inputs))
            for link in tree.links
            if link.from_node in owned_nodes or link.to_node in owned_nodes}


def _expected_outer_links():
    return {
        ("mmd_shader", "Color", "multiply", "Color2"),
        ("ramp_group", "Color", "multiply", "Color1"),
        ("multiply", "Color", "emission", "Color"),
        ("transparent", "BSDF", "mix", "Shader"),
        ("emission", "Emission", "mix", "Shader_001"),
        ("mmd_shader", "Alpha", "mix", "Fac"),
        ("mix", "Shader", "eevee_output", "Surface"),
    }


def _expected_group_links():
    return {
        ("diffuse", "BSDF", "shader_to_rgb", "Shader"),
        ("shader_to_rgb", "Color", "rgb_to_bw", "Color"),
        ("rgb_to_bw", "Val", "ramp", "Fac"),
        ("ramp", "Color", "group_output", "Color"),
    }


def _set_ramp(ramp_node, preset, threshold, shadow):
    color_ramp = ramp_node.color_ramp
    color_ramp.interpolation = 'CONSTANT'
    while len(color_ramp.elements) > 2:
        color_ramp.elements.remove(color_ramp.elements[-1])
    elements = color_ramp.elements
    elements[0].position = 0.0
    elements[0].color = (shadow, shadow, shadow, 1.0)
    elements[1].position = threshold
    elements[1].color = (1.0, 1.0, 1.0, 1.0)
    if preset == 'THREE_BANDS':
        middle = color_ramp.elements.new(threshold / 2.0)
        middle.color = ((1.0 + shadow) / 2.0, (1.0 + shadow) / 2.0,
                        (1.0 + shadow) / 2.0, 1.0)


def _make_group(material, owner):
    group = bpy.data.node_groups.new("Violet Toon 0.4", 'ShaderNodeTree')
    try:
        group[GROUP_OWNER_KEY] = owner
        group[GROUP_SCHEMA_KEY] = SCHEMA
        group.interface.new_socket(name="Color", in_out='OUTPUT', socket_type='NodeSocketColor')
        nodes = group.nodes
        diffuse = nodes.new('ShaderNodeBsdfDiffuse')
        _tag(diffuse, owner, "diffuse")
        diffuse.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        diffuse.inputs["Roughness"].default_value = 0.0
        shader_to_rgb = nodes.new('ShaderNodeShaderToRGB')
        _tag(shader_to_rgb, owner, "shader_to_rgb")
        rgb_to_bw = nodes.new('ShaderNodeRGBToBW')
        _tag(rgb_to_bw, owner, "rgb_to_bw")
        ramp = nodes.new('ShaderNodeValToRGB')
        _tag(ramp, owner, "ramp")
        group_output = nodes.new('NodeGroupOutput')
        _tag(group_output, owner, "group_output")
        group.links.new(diffuse.outputs["BSDF"], shader_to_rgb.inputs["Shader"])
        group.links.new(shader_to_rgb.outputs["Color"], rgb_to_bw.inputs["Color"])
        group.links.new(rgb_to_bw.outputs["Val"], ramp.inputs["Fac"])
        group.links.new(ramp.outputs["Color"], group_output.inputs["Color"])
        return group
    except Exception:
        bpy.data.node_groups.remove(group)
        raise


def _create_graph(material, owner, preset, threshold, shadow):
    tree = material.node_tree
    output_flags = [(node, node.is_active_output) for node in _outputs(material)]
    group = None
    created = []
    try:
        group = _make_group(material, owner)
        group_nodes = _group_nodes(group, owner)
        _set_ramp(group_nodes["ramp"], preset, threshold, shadow)
        nodes = tree.nodes
        group_node = nodes.new('ShaderNodeGroup')
        created.append(group_node)
        group_node.node_tree = group
        _tag(group_node, owner, "ramp_group")
        multiply = nodes.new('ShaderNodeMixRGB')
        created.append(multiply)
        _tag(multiply, owner, "multiply")
        multiply.blend_type = 'MULTIPLY'
        multiply.inputs["Fac"].default_value = 1.0
        emission = nodes.new('ShaderNodeEmission')
        created.append(emission)
        _tag(emission, owner, "emission")
        emission.inputs["Strength"].default_value = 1.0
        transparent = nodes.new('ShaderNodeBsdfTransparent')
        created.append(transparent)
        _tag(transparent, owner, "transparent")
        mix = nodes.new('ShaderNodeMixShader')
        created.append(mix)
        _tag(mix, owner, "mix")
        eevee_output = nodes.new('ShaderNodeOutputMaterial')
        created.append(eevee_output)
        eevee_output.target = 'EEVEE'
        eevee_output.is_active_output = False
        _tag(eevee_output, owner, "eevee_output")

        shader = nodes.get("mmd_shader")
        tree.links.new(group_node.outputs["Color"], multiply.inputs["Color1"])
        tree.links.new(shader.outputs["Color"], multiply.inputs["Color2"])
        tree.links.new(multiply.outputs["Color"], emission.inputs["Color"])
        tree.links.new(transparent.outputs["BSDF"], mix.inputs["Shader"])
        tree.links.new(emission.outputs["Emission"], mix.inputs[2])
        tree.links.new(shader.outputs["Alpha"], mix.inputs["Fac"])
        tree.links.new(mix.outputs["Shader"], eevee_output.inputs["Surface"])
        for node, active in output_flags:
            node.is_active_output = active
        eevee_output.is_active_output = False
        return group
    except Exception:
        for node in reversed(created):
            if node.id_data == tree:
                tree.nodes.remove(node)
        if group is not None and group.name in bpy.data.node_groups:
            bpy.data.node_groups.remove(group)
        for node, active in output_flags:
            if node.id_data == tree:
                node.is_active_output = active
        raise


def _validate_graph(material, owner, applied_preset, applied_threshold, applied_shadow, group):
    shader = _material_preflight(material, owner)
    roles = _role_nodes(material.node_tree.nodes, owner)
    if group is None or group.bl_idname != 'ShaderNodeTree':
        raise ValueError(f"Material {material.name} lost its owned Toon ramp group")
    if group.get(GROUP_OWNER_KEY) != owner or group.get(GROUP_SCHEMA_KEY) != SCHEMA:
        raise ValueError(f"Material {material.name} has an invalid owned Toon group")
    if roles["ramp_group"].node_tree != group:
        raise ValueError(f"Material {material.name} has a replaced Toon ramp group")
    group_instances = _group_instances(group)
    if (len(group_instances) != 1 or group_instances[0][0] != material or
            group_instances[0][1] != roles["ramp_group"]):
        raise ValueError(f"Material {material.name} has a shared or edited Toon ramp group")
    node_types = {
        "ramp_group": "GROUP", "multiply": "MIX_RGB", "emission": "EMISSION",
        "transparent": "BSDF_TRANSPARENT", "mix": "MIX_SHADER",
        "eevee_output": "OUTPUT_MATERIAL",
    }
    if any(roles[role].type != node_type for role, node_type in node_types.items()):
        raise ValueError(f"Material {material.name} has edited Toon node types")
    if any(node.mute for node in roles.values()):
        raise ValueError(f"Material {material.name} has muted Toon nodes")
    if roles["eevee_output"].target != 'EEVEE' or roles["eevee_output"].is_active_output:
        raise ValueError(f"Material {material.name} has an edited Eevee output")
    if tuple(roles["transparent"].inputs["Color"].default_value) != (1.0, 1.0, 1.0, 1.0):
        raise ValueError(f"Material {material.name} has an edited Toon transparent color")
    role_by_node = {node: role for role, node in roles.items()}
    role_by_node[shader] = "mmd_shader"
    if _link_signature(material.node_tree, role_by_node, ROLES) != _expected_outer_links():
        raise ValueError(f"Material {material.name} has edited Toon links")
    multiply = roles["multiply"]
    if multiply.blend_type != 'MULTIPLY' or abs(multiply.inputs["Fac"].default_value - 1.0) > 1e-6:
        raise ValueError(f"Material {material.name} has edited Toon multiply settings")
    if abs(roles["emission"].inputs["Strength"].default_value - 1.0) > 1e-6:
        raise ValueError(f"Material {material.name} has edited Toon emission settings")
    group_roles = _group_nodes(group, owner)
    if any(group_roles[role].type != node_type for role, node_type in {
            "diffuse": "BSDF_DIFFUSE", "shader_to_rgb": "SHADERTORGB",
            "rgb_to_bw": "RGBTOBW", "ramp": "VALTORGB", "group_output": "GROUP_OUTPUT"}.items()):
        raise ValueError(f"Material {material.name} has edited Toon ramp nodes")
    if any(node.mute for node in group_roles.values()):
        raise ValueError(f"Material {material.name} has muted Toon ramp nodes")
    group_signature = _link_signature(group, {node: role for role, node in group_roles.items()})
    if group_signature != _expected_group_links():
        raise ValueError(f"Material {material.name} has edited Toon ramp links")
    diffuse = group_roles["diffuse"]
    if (tuple(diffuse.inputs["Color"].default_value) != (1.0, 1.0, 1.0, 1.0) or
            abs(diffuse.inputs["Roughness"].default_value) > 1e-6):
        raise ValueError(f"Material {material.name} has edited Toon diffuse settings")
    color_ramp = group_roles["ramp"].color_ramp
    expected_count = 3 if applied_preset == 'THREE_BANDS' else 2
    if color_ramp.interpolation != 'CONSTANT' or len(color_ramp.elements) != expected_count:
        raise ValueError(f"Material {material.name} has edited Toon ramp settings")
    expected = [(0.0, applied_shadow, applied_shadow, applied_shadow)]
    if applied_preset == 'THREE_BANDS':
        middle = (1.0 + applied_shadow) / 2.0
        expected.append((applied_threshold / 2.0, middle, middle, middle))
    expected.append((applied_threshold, 1.0, 1.0, 1.0))
    for element, (position, red, green, blue) in zip(color_ramp.elements, expected, strict=True):
        actual = tuple(element.color)
        if (abs(element.position - position) > 1e-5 or
                any(abs(actual[i] - value) > 1e-5 for i, value in enumerate((red, green, blue))) or
                abs(actual[3] - 1.0) > 1e-5):
            raise ValueError(f"Material {material.name} has edited Toon ramp values")
    return roles, group_roles


def _validate_owner(root):
    owner = root.get(OWNER_KEY)
    if not owner or root.get(SCHEMA_KEY) != SCHEMA:
        raise ValueError("This PMX model has no supported Violet Toon setup")
    entries = list(root.violet_toon_materials)
    if not entries or any(entry.owner != owner or entry.material is None for entry in entries):
        raise ValueError("The model's managed Toon material list is incomplete")
    if len({entry.material.as_pointer() for entry in entries}) != len(entries):
        raise ValueError("The model's managed Toon material list contains duplicates")
    return owner, entries


def _validate_model_materials(root, owner, entries):
    meshes, current = _local_materials(root)
    managed = [entry.material for entry in entries]
    if set(current) != set(managed):
        raise ValueError("Model material slots changed; restore Toon before updating")
    for entry in entries:
        _validate_graph(entry.material, owner, entry.applied_preset,
                        entry.applied_threshold, entry.applied_shadow, entry.group)
    return meshes, managed


def _capture_root_state(root):
    return (root.get(OWNER_KEY), root.get(SCHEMA_KEY), root.violet_toon_preset,
            root.violet_toon_threshold, root.violet_toon_shadow_brightness,
            [(entry.material, entry.group, entry.owner, entry.applied_preset,
              entry.applied_threshold, entry.applied_shadow) for entry in root.violet_toon_materials])


def _restore_root_state(root, state):
    owner, schema, preset, threshold, shadow, entries = state
    root.violet_toon_materials.clear()
    for material, group, entry_owner, applied_preset, applied_threshold, applied_shadow in entries:
        entry = root.violet_toon_materials.add()
        entry.material = material
        entry.group = group
        entry.owner = entry_owner
        entry.applied_preset = applied_preset
        entry.applied_threshold = applied_threshold
        entry.applied_shadow = applied_shadow
    root.violet_toon_preset = preset
    root.violet_toon_threshold = threshold
    root.violet_toon_shadow_brightness = shadow
    if owner is None:
        root.pop(OWNER_KEY, None)
    else:
        root[OWNER_KEY] = owner
    if schema is None:
        root.pop(SCHEMA_KEY, None)
    else:
        root[SCHEMA_KEY] = schema


def _clear_owner_state(root):
    root.violet_toon_materials.clear()
    root.pop(OWNER_KEY, None)
    root.pop(SCHEMA_KEY, None)


def apply(root):
    """Apply the current model settings after a complete, read-only preflight."""
    if root is None or root.library is not None:
        raise ValueError("Select an editable local PMX model")
    if OWNER_KEY in root or len(root.violet_toon_materials):
        raise ValueError("This model already has a Violet Toon setup; use Update Model")
    meshes, materials = _local_materials(root)
    for material in materials:
        _material_preflight(material)
    owner = uuid.uuid4().hex
    preset = root.violet_toon_preset
    threshold = float(root.violet_toon_threshold)
    shadow = float(root.violet_toon_shadow_brightness)
    created = []
    try:
        for material in materials:
            group = _create_graph(material, owner, preset, threshold, shadow)
            created.append((material, group))
        root_state = _capture_root_state(root)
        try:
            root[OWNER_KEY] = owner
            root[SCHEMA_KEY] = SCHEMA
            root.violet_toon_materials.clear()
            for material, group in created:
                entry = root.violet_toon_materials.add()
                entry.material = material
                entry.group = group
                entry.owner = owner
                entry.applied_preset = preset
                entry.applied_threshold = threshold
                entry.applied_shadow = shadow
        except Exception:
            _restore_root_state(root, root_state)
            raise
    except Exception:
        for material, group in reversed(created):
            _remove_graph(material, owner, group)
            if group is not None and group.name in bpy.data.node_groups and group.users == 0:
                bpy.data.node_groups.remove(group)
        raise
    return len(created)


def update(root):
    """Update only owned ramp values; reject edited or structurally changed graphs."""
    owner, entries = _validate_owner(root)
    _validate_model_materials(root, owner, entries)
    preset = root.violet_toon_preset
    threshold = float(root.violet_toon_threshold)
    shadow = float(root.violet_toon_shadow_brightness)
    before = [(entry, entry.applied_preset, entry.applied_threshold, entry.applied_shadow)
              for entry in entries]
    updated = []
    try:
        for entry in entries:
            group_nodes = _group_nodes(entry.group, owner)
            _set_ramp(group_nodes["ramp"], preset, threshold, shadow)
            updated.append(entry)
            entry.applied_preset = preset
            entry.applied_threshold = threshold
            entry.applied_shadow = shadow
    except Exception:
        for entry, old_preset, old_threshold, old_shadow in before:
            if entry.group is not None and entry.group.name in bpy.data.node_groups:
                group_nodes = _group_nodes(entry.group, owner)
                _set_ramp(group_nodes["ramp"], old_preset, old_threshold, old_shadow)
            entry.applied_preset = old_preset
            entry.applied_threshold = old_threshold
            entry.applied_shadow = old_shadow
        raise
    return len(updated)


def _remove_graph(material, owner, group):
    roles = _role_nodes(material.node_tree.nodes, owner)
    if roles and set(roles) != set(ROLES):
        raise ValueError(f"Material {material.name} has an incomplete Violet Toon graph")
    for role in reversed(ROLES):
        node = roles.get(role)
        if node is not None:
            material.node_tree.nodes.remove(node)


def _remove_group_if_unused(group):
    if group is not None and group.name in bpy.data.node_groups and group.users == 0:
        bpy.data.node_groups.remove(group)


def _recreate_graph(material, owner, group, preset, threshold, shadow):
    """Reattach a removed outer graph to its still-preserved owned group."""
    if group is None or group.name not in bpy.data.node_groups:
        group = _make_group(material, owner)
        _set_ramp(_group_nodes(group, owner)["ramp"], preset, threshold, shadow)
    else:
        _set_ramp(_group_nodes(group, owner)["ramp"], preset, threshold, shadow)
    # Reuse graph builder's validated, known graph construction while preserving
    # the group datablock required for rollback.
    tree = material.node_tree
    output_flags = [(node, node.is_active_output) for node in _outputs(material)]
    made = []
    try:
        group_node = tree.nodes.new('ShaderNodeGroup')
        made.append(group_node)
        group_node.node_tree = group
        _tag(group_node, owner, "ramp_group")
        multiply = tree.nodes.new('ShaderNodeMixRGB')
        made.append(multiply)
        _tag(multiply, owner, "multiply")
        multiply.blend_type = 'MULTIPLY'
        multiply.inputs["Fac"].default_value = 1.0
        emission = tree.nodes.new('ShaderNodeEmission')
        made.append(emission)
        _tag(emission, owner, "emission")
        emission.inputs["Strength"].default_value = 1.0
        transparent = tree.nodes.new('ShaderNodeBsdfTransparent')
        made.append(transparent)
        _tag(transparent, owner, "transparent")
        mix = tree.nodes.new('ShaderNodeMixShader')
        made.append(mix)
        _tag(mix, owner, "mix")
        output = tree.nodes.new('ShaderNodeOutputMaterial')
        made.append(output)
        output.target = 'EEVEE'
        output.is_active_output = False
        _tag(output, owner, "eevee_output")
        shader = tree.nodes.get("mmd_shader")
        tree.links.new(group_node.outputs["Color"], multiply.inputs["Color1"])
        tree.links.new(shader.outputs["Color"], multiply.inputs["Color2"])
        tree.links.new(multiply.outputs["Color"], emission.inputs["Color"])
        tree.links.new(transparent.outputs["BSDF"], mix.inputs["Shader"])
        tree.links.new(emission.outputs["Emission"], mix.inputs[2])
        tree.links.new(shader.outputs["Alpha"], mix.inputs["Fac"])
        tree.links.new(mix.outputs["Shader"], output.inputs["Surface"])
        for node, active in output_flags:
            node.is_active_output = active
        output.is_active_output = False
    except Exception:
        for node in reversed(made):
            if node.id_data == tree:
                tree.nodes.remove(node)
        for node, active in output_flags:
            if node.id_data == tree:
                node.is_active_output = active
        raise


def _discard_owned_nodes(material, owner):
    for node in tuple(material.node_tree.nodes):
        if node.get(NODE_OWNER_KEY) == owner:
            material.node_tree.nodes.remove(node)


def restore(root):
    """Remove only Violet-owned nodes and groups, restoring all originals in place."""
    owner, entries = _validate_owner(root)
    _validate_model_materials(root, owner, entries)
    saved = [(entry.material, entry.group, entry.applied_preset,
              entry.applied_threshold, entry.applied_shadow) for entry in entries]
    root_state = _capture_root_state(root)
    try:
        for material, group, preset, threshold, shadow in saved:
            _remove_graph(material, owner, group)
        # Commit the restored material state before deleting unused helper groups.
        _clear_owner_state(root)
    except Exception:
        # Keep complete graphs intact and rebuild any graph partially removed by
        # the failed operation. The preflighted groups remain alive until commit.
        rollback_errors = []
        for material, group, preset, threshold, shadow in saved:
            try:
                try:
                    _validate_graph(material, owner, preset, threshold, shadow, group)
                except Exception:
                    _discard_owned_nodes(material, owner)
                    _recreate_graph(material, owner, group, preset, threshold, shadow)
            except Exception as rollback_exc:
                rollback_errors.append(rollback_exc)
        try:
            _restore_root_state(root, root_state)
        except Exception as rollback_exc:
            rollback_errors.append(rollback_exc)
        if rollback_errors:
            raise RuntimeError("Restore failed and rollback was incomplete: " +
                               "; ".join(str(error) for error in rollback_errors))
        raise
    for _material, group, _preset, _threshold, _shadow in saved:
        _remove_group_if_unused(group)
    return len(saved)


def register_properties():
    from bpy.props import (CollectionProperty, EnumProperty, FloatProperty,
                           PointerProperty, StringProperty)

    class VIOLET_PG_toon_material(bpy.types.PropertyGroup):
        material: PointerProperty(type=bpy.types.Material)
        group: PointerProperty(type=bpy.types.NodeTree)
        owner: StringProperty()
        applied_preset: EnumProperty(items=(('TWO_BANDS', "Two Bands", ""),
                                            ('THREE_BANDS', "Three Bands", "")),
                                     default='TWO_BANDS')
        applied_threshold: FloatProperty(default=0.5)
        applied_shadow: FloatProperty(default=0.25)

    bpy.utils.register_class(VIOLET_PG_toon_material)
    bpy.types.Object.violet_toon_materials = CollectionProperty(type=VIOLET_PG_toon_material)
    bpy.types.Object.violet_toon_preset = EnumProperty(
        name="Bands", items=(('TWO_BANDS', "Two Bands", "Shadow and light"),
                             ('THREE_BANDS', "Three Bands", "Shadow, middle, and light")),
        default='TWO_BANDS')
    bpy.types.Object.violet_toon_threshold = bpy.props.FloatProperty(
        name="Highlight Threshold", default=0.5, min=0.02, max=0.98, precision=3)
    bpy.types.Object.violet_toon_shadow_brightness = bpy.props.FloatProperty(
        name="Shadow Brightness", default=0.25, min=0.0, max=1.0, precision=3)
    return VIOLET_PG_toon_material


def unregister_properties(property_group):
    del bpy.types.Object.violet_toon_shadow_brightness
    del bpy.types.Object.violet_toon_threshold
    del bpy.types.Object.violet_toon_preset
    del bpy.types.Object.violet_toon_materials
    bpy.utils.unregister_class(property_group)
