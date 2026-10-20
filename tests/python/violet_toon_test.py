# SPDX-FileCopyrightText: 2026 VioletBlender contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generated-fixture tests for the transactional Eevee Toon material branch."""

import os
from pathlib import Path
import runpy
import sys
import tempfile
from unittest.mock import patch

import addon_utils
import bpy


REPO = Path(__file__).resolve().parents[2]
if not os.environ.get('VIOLET_PMX_INSTALLED'):
    sys.path.insert(0, str(REPO / 'scripts/addons_core'))
if os.environ.get('VIOLET_PMX_EXPECT_VERSION'):
    expected_version = tuple(map(int, os.environ['VIOLET_PMX_EXPECT_VERSION'].split('.')))
    assert bpy.app.version[:len(expected_version)] == expected_version, bpy.app.version_string
if not addon_utils.check('violet_pmx')[1]:
    assert addon_utils.enable('violet_pmx', default_set=True, persistent=True) is not None

from violet_pmx import toon, workflow


def select_object(obj):
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def output_flags(material):
    return tuple(sorted((node.name, node.target, bool(node.is_active_output))
                        for node in material.node_tree.nodes if node.type == 'OUTPUT_MATERIAL'))


def original_snapshot(material):
    tree = material.node_tree
    nodes = tuple(sorted((node.name, node.bl_idname, node.type) for node in tree.nodes))
    links = tuple(sorted((link.from_node.name, link.from_socket.identifier,
                          link.to_node.name, link.to_socket.identifier) for link in tree.links))
    shader = tree.nodes['mmd_shader']
    shader_values = tuple((socket.name, socket.is_linked,
                           tuple(socket.default_value) if hasattr(socket.default_value, '__iter__')
                           else socket.default_value)
                          for socket in shader.inputs)
    texture_nodes = tuple(sorted((node.name, node.image.name if node.image else None,
                                  bpy.path.abspath(node.image.filepath) if node.image else None)
                                 for node in tree.nodes if node.type == 'TEX_IMAGE'))
    drivers = ()
    if tree.animation_data:
        drivers = tuple(sorted((curve.data_path, curve.array_index,
                                curve.driver.type,
                                curve.driver.expression if curve.driver.type == 'SCRIPTED' else None,
                                tuple((variable.name, variable.type,
                                       tuple((target.id_type,
                                              target.id.name if target.id else None,
                                              target.data_path)
                                             for target in variable.targets))
                                      for variable in curve.driver.variables))
                               for curve in tree.animation_data.drivers))
    return {"nodes": nodes, "links": links, "outputs": output_flags(material),
            "shader_values": shader_values, "textures": texture_nodes, "drivers": drivers,
            "render": (getattr(material, "surface_render_method", None),
                       getattr(material, "blend_method", None))}


def assert_same_original(material, snapshot):
    current = original_snapshot(material)
    assert current == snapshot, (material.name,
                                 {key: (snapshot[key], current[key])
                                  for key in snapshot if snapshot[key] != current[key]})


def owned_group_count(owner=None):
    return sum(group.get(toon.GROUP_OWNER_KEY) == owner if owner else
               toon.GROUP_OWNER_KEY in group for group in bpy.data.node_groups)


def main():
    fixture = runpy.run_path(str(REPO / 'tests/python/violet_pmx_test.py'),
                             run_name='violet_toon_fixture')
    with tempfile.TemporaryDirectory(prefix='violet-toon-') as temp:
        directory = Path(temp)
        pmx_path = fixture['make_fixture'](directory)
        root_a, _ = workflow.import_pmx(bpy.context, str(pmx_path))
        root_b, _ = workflow.import_pmx(bpy.context, str(pmx_path))
        root_c, _ = workflow.import_pmx(bpy.context, str(pmx_path))
        mats_a = workflow.model_materials(root_a)
        mats_b = workflow.model_materials(root_b)
        mats_c = workflow.model_materials(root_c)
        # Exercise a real MMD material socket driver and verify it evaluates through
        # save/reopen and Toon updates without changing its original driver path.
        driver_path = 'nodes["mmd_shader"].inputs["Alpha"].default_value'
        curve = mats_a[0].node_tree.driver_add(driver_path)
        curve.driver.type = 'SCRIPTED'
        curve.driver.expression = "0.6"
        bpy.context.view_layer.update()
        assert curve.is_valid
        assert abs(mats_a[0].node_tree.nodes['mmd_shader'].inputs['Alpha'].default_value - 0.6) < 1e-5
        snapshots = [original_snapshot(material) for material in mats_a]
        morph_material = root_a.mmd_root.material_morphs['透明'].data[0].material
        morph_before = (morph_material,
                        tuple(root_a.mmd_root.material_morphs['透明'].data[0].diffuse_color))
        cycle_outputs = [toon._cycles_output(material) for material in mats_a]
        assert all(output.target in {'ALL', 'CYCLES'} for output in cycle_outputs)

        # A failure after one material was built must leave no nodes or groups.
        groups_before = set(bpy.data.node_groups)
        node_sets_before = [tuple(sorted((node.name, node.bl_idname, node.type)
                                         for node in material.node_tree.nodes))
                            for material in mats_c]
        create_graph = toon._create_graph
        calls = 0

        def fail_second_create(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("forced apply failure")
            return create_graph(*args, **kwargs)

        with patch.object(toon, '_create_graph', side_effect=fail_second_create):
            try:
                toon.apply(root_c)
            except RuntimeError as exc:
                assert "forced apply failure" in str(exc)
            else:
                raise AssertionError("forced Apply failure did not propagate")
        assert set(bpy.data.node_groups) == groups_before
        assert toon.OWNER_KEY not in root_c
        assert all(not any(toon.NODE_OWNER_KEY in node for node in material.node_tree.nodes)
                   for material in mats_c)

        # Failure while tagging the first outer node must remove that newly-created
        # but still-unowned node, its helper group, and all model metadata changes.
        real_tag = toon._tag

        def fail_first_ramp_tag(node, graph_owner, role):
            if role == "ramp_group":
                raise RuntimeError("forced outer Toon tag failure")
            return real_tag(node, graph_owner, role)

        with patch.object(toon, '_tag', side_effect=fail_first_ramp_tag):
            try:
                toon.apply(root_c)
            except RuntimeError as exc:
                assert "forced outer Toon tag failure" in str(exc)
            else:
                raise AssertionError("forced outer-node tag failure did not propagate")
        assert set(bpy.data.node_groups) == groups_before
        assert toon.OWNER_KEY not in root_c
        assert len(root_c.violet_toon_materials) == 0
        assert [tuple(sorted((node.name, node.bl_idname, node.type)
                             for node in material.node_tree.nodes))
                for material in mats_c] == node_sets_before

        select_object(root_a)
        assert bpy.ops.violet.toon_apply() == {'FINISHED'}
        owner = root_a[toon.OWNER_KEY]
        assert len(root_a.violet_toon_materials) == len(mats_a)
        assert all(material.node_tree.nodes.get('mmd_shader') is not None for material in mats_a)
        assert all(not any(toon.NODE_OWNER_KEY in node for node in material.node_tree.nodes)
                   for material in mats_b)
        assert owned_group_count(owner) == len(mats_a)
        for material, old_output in zip(mats_a, cycle_outputs, strict=True):
            roles = toon._role_nodes(material.node_tree.nodes, owner)
            assert roles['eevee_output'].target == 'EEVEE'
            assert not roles['eevee_output'].is_active_output
            assert toon._cycles_output(material) == old_output
            assert material.node_tree.get_output_node('EEVEE') == roles['eevee_output']
            assert material.node_tree.get_output_node('CYCLES') == old_output
            assert (getattr(material, "surface_render_method", None),
                    getattr(material, "blend_method", None)) == snapshots[mats_a.index(material)]["render"]

        # Update and Restore must refuse hand edits to the owned graph before mutation.
        first_entry = root_a.violet_toon_materials[0]
        first_roles = toon._role_nodes(first_entry.material.node_tree.nodes, owner)
        fac_socket = first_roles['multiply'].inputs['Fac']
        original_fac = fac_socket.default_value
        fac_socket.default_value = 0.75
        try:
            try:
                toon.update(root_a)
            except ValueError as exc:
                assert "edited Toon multiply settings" in str(exc)
            else:
                raise AssertionError("Update accepted a manually edited owned graph")
        finally:
            fac_socket.default_value = original_fac
        toon._validate_model_materials(root_a, owner, list(root_a.violet_toon_materials))

        multiply_node = first_roles['multiply']
        multiply_node.mute = True
        try:
            try:
                toon.update(root_a)
            except ValueError as exc:
                assert "muted Toon nodes" in str(exc)
            else:
                raise AssertionError("Update accepted a muted owned Toon node")
        finally:
            multiply_node.mute = False

        ramp_node = toon._group_nodes(first_entry.group, owner)['ramp']
        ramp_node.mute = True
        try:
            try:
                toon.update(root_a)
            except ValueError as exc:
                assert "muted Toon ramp nodes" in str(exc)
            else:
                raise AssertionError("Update accepted a muted owned ramp node")
        finally:
            ramp_node.mute = False

        transparent_color = first_roles['transparent'].inputs['Color']
        original_transparent_color = tuple(transparent_color.default_value)
        transparent_color.default_value = (0.2, 0.3, 0.4, 1.0)
        try:
            try:
                toon.update(root_a)
            except ValueError as exc:
                assert "edited Toon transparent color" in str(exc)
            else:
                raise AssertionError("Update accepted an edited transparent color")
        finally:
            transparent_color.default_value = original_transparent_color
        toon._validate_model_materials(root_a, owner, list(root_a.violet_toon_materials))

        # A helper group borrowed by a different material is protected from updates.
        borrower = bpy.data.materials.new("borrowed Toon group")
        borrower.use_nodes = True
        borrowed_node = borrower.node_tree.nodes.new('ShaderNodeGroup')
        borrowed_node.node_tree = first_entry.group
        try:
            try:
                toon.update(root_a)
            except ValueError as exc:
                assert "shared or edited Toon ramp group" in str(exc)
            else:
                raise AssertionError("Update accepted a borrowed owned group")
        finally:
            bpy.data.materials.remove(borrower)
        toon._validate_model_materials(root_a, owner, list(root_a.violet_toon_materials))

        world_borrower = bpy.data.worlds.new("borrowed Toon group world")
        world_borrower.use_nodes = True
        world_node = world_borrower.node_tree.nodes.new('ShaderNodeGroup')
        world_node.node_tree = first_entry.group
        try:
            try:
                toon.update(root_a)
            except ValueError as exc:
                assert "shared or edited Toon ramp group" in str(exc)
            else:
                raise AssertionError("Update accepted a Toon group borrowed by a World")
        finally:
            bpy.data.worlds.remove(world_borrower)
        toon._validate_model_materials(root_a, owner, list(root_a.violet_toon_materials))

        root_a.violet_toon_preset = 'THREE_BANDS'
        root_a.violet_toon_threshold = 0.63
        root_a.violet_toon_shadow_brightness = 0.2
        assert bpy.ops.violet.toon_update() == {'FINISHED'}
        for entry in root_a.violet_toon_materials:
            assert entry.applied_preset == 'THREE_BANDS'
            assert abs(entry.applied_threshold - 0.63) < 1e-5
            assert len(toon._group_nodes(entry.group, owner)['ramp'].color_ramp.elements) == 3

        # A partial update failure reverts prior ramps and their saved settings.
        old_applied = [(entry.applied_preset, entry.applied_threshold, entry.applied_shadow)
                       for entry in root_a.violet_toon_materials]
        root_a.violet_toon_preset = 'TWO_BANDS'
        root_a.violet_toon_threshold = 0.41
        real_set_ramp = toon._set_ramp
        calls = 0

        def fail_once(ramp, preset, threshold, shadow):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("forced update failure")
            return real_set_ramp(ramp, preset, threshold, shadow)

        with patch.object(toon, '_set_ramp', side_effect=fail_once):
            try:
                toon.update(root_a)
            except RuntimeError as exc:
                assert "forced update failure" in str(exc)
            else:
                raise AssertionError("forced Update failure did not propagate")
        assert [(entry.applied_preset, entry.applied_threshold, entry.applied_shadow)
                for entry in root_a.violet_toon_materials] == old_applied
        assert all(len(toon._group_nodes(entry.group, owner)['ramp'].color_ramp.elements) == 3
                   for entry in root_a.violet_toon_materials)

        # A material used by an object outside its PMX root is refused in preflight.
        external_mesh = bpy.data.meshes.new("outside Toon user")
        external_obj = bpy.data.objects.new("outside Toon user", external_mesh)
        bpy.context.scene.collection.objects.link(external_obj)
        external_mesh.materials.append(mats_b[0])
        try:
            try:
                toon.apply(root_b)
            except ValueError as exc:
                assert "outside this model" in str(exc)
            else:
                raise AssertionError("shared material was accepted")
            assert all(not any(toon.NODE_OWNER_KEY in node for node in material.node_tree.nodes)
                       for material in mats_b)
        finally:
            bpy.data.objects.remove(external_obj, do_unlink=True)
            bpy.data.meshes.remove(external_mesh)

        renamed_material = root_a.violet_toon_materials[0].material
        renamed_material.name = renamed_material.name + " renamed"
        blend_path = directory / "toon-roundtrip.blend"
        assert bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False) == {'FINISHED'}
        assert bpy.ops.wm.open_mainfile(filepath=str(blend_path)) == {'FINISHED'}
        root_a = next(obj for obj in bpy.data.objects if obj.get(toon.OWNER_KEY) == owner)
        select_object(root_a)
        assert any(entry.material.name.endswith(" renamed") for entry in root_a.violet_toon_materials)
        toon._validate_model_materials(root_a, owner, list(root_a.violet_toon_materials))
        assert root_a.mmd_root.material_morphs['透明'].data[0].material == morph_before[0]
        assert tuple(root_a.mmd_root.material_morphs['透明'].data[0].diffuse_color) == morph_before[1]
        bpy.context.view_layer.update()
        driver_material = next(entry.material for entry in root_a.violet_toon_materials
                               if entry.material.node_tree.animation_data and
                               entry.material.node_tree.animation_data.drivers)
        assert abs(driver_material.node_tree.nodes['mmd_shader'].inputs['Alpha'].default_value - 0.6) < 1e-5

        # Restore failure after one removal recreates that owned graph in place.
        remove_graph = toon._remove_graph
        calls = 0

        def fail_second_remove(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("forced restore failure")
            return remove_graph(*args, **kwargs)

        with patch.object(toon, '_remove_graph', side_effect=fail_second_remove):
            try:
                toon.restore(root_a)
            except RuntimeError as exc:
                assert "forced restore failure" in str(exc)
            else:
                raise AssertionError("forced Restore failure did not propagate")
        toon._validate_model_materials(root_a, owner, list(root_a.violet_toon_materials))
        assert owned_group_count(owner) == len(root_a.violet_toon_materials)

        # A failure after one node has been removed from the current material is
        # also rolled back into a complete graph.
        partial_failure = False

        def fail_after_partial_remove(material, graph_owner, group):
            nonlocal partial_failure
            if not partial_failure:
                partial_failure = True
                roles = toon._role_nodes(material.node_tree.nodes, graph_owner)
                material.node_tree.nodes.remove(roles['eevee_output'])
                raise RuntimeError("forced partial restore failure")
            return remove_graph(material, graph_owner, group)

        with patch.object(toon, '_remove_graph', side_effect=fail_after_partial_remove):
            try:
                toon.restore(root_a)
            except RuntimeError as exc:
                assert "forced partial restore failure" in str(exc)
            else:
                raise AssertionError("partial Restore failure did not propagate")
        toon._validate_model_materials(root_a, owner, list(root_a.violet_toon_materials))
        assert owned_group_count(owner) == len(root_a.violet_toon_materials)

        # A failed metadata commit restores the model owner and material entries.
        clear_owner_state = toon._clear_owner_state

        def fail_after_owner_commit(root):
            clear_owner_state(root)
            raise RuntimeError("forced Restore metadata failure")

        with patch.object(toon, '_clear_owner_state', side_effect=fail_after_owner_commit):
            try:
                toon.restore(root_a)
            except RuntimeError as exc:
                assert "forced Restore metadata failure" in str(exc)
            else:
                raise AssertionError("Restore metadata failure did not propagate")
        assert root_a.get(toon.OWNER_KEY) == owner
        assert len(root_a.violet_toon_materials) == len(mats_a)
        toon._validate_model_materials(root_a, owner, list(root_a.violet_toon_materials))
        assert owned_group_count(owner) == len(root_a.violet_toon_materials)

        assert bpy.ops.violet.toon_restore() == {'FINISHED'}
        assert toon.OWNER_KEY not in root_a
        assert owned_group_count(owner) == 0
        # The collection is cleared on Restore, so match the serialized originals by
        # their stable PMX order and source-name property, including duplicate names.
        restored = workflow.model_materials(root_a)
        assert len(restored) == len(snapshots)
        for material, snapshot in zip(restored, snapshots, strict=True):
            assert_same_original(material, snapshot)
        assert restored[0].node_tree.animation_data is not None
        assert len(restored[0].node_tree.animation_data.drivers) == 1
        bpy.context.view_layer.update()
        assert abs(restored[0].node_tree.nodes['mmd_shader'].inputs['Alpha'].default_value - 0.6) < 1e-5
        assert_same_original(restored[0], snapshots[0])
        restored_morph = root_a.mmd_root.material_morphs['透明'].data[0]
        assert restored_morph.material == morph_before[0]
        assert tuple(restored_morph.diffuse_color) == morph_before[1]
    print(f'VIOLET_TOON_OK: Blender {bpy.app.version_string}; output selection, rollback, model isolation, material pointer persistence, restore')
    print('VIOLET_TOON_RENDER_SKIPPED: run tests/python/violet_toon_render_test.py for pixel validation')


if __name__ == '__main__':
    main()
