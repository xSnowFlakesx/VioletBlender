# SPDX-FileCopyrightText: 2026 VioletBlender contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""End-to-end PMX fixture tests, run by Blender rather than system Python.

No third-party character models are used. The fixture is generated from scratch.
"""

import json
import os
from pathlib import Path
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
assert addon_utils.enable('violet_pmx', default_set=True, persistent=True) is not None

from mmd_tools.core import pmx
from mmd_tools.core.model import Model
from mmd_tools.core.pmx.importer import PMXImporter
from violet_pmx import workflow


def close(actual, expected):
    assert len(actual) == len(expected), (actual, expected)
    assert all(abs(a - b) < 1e-5 for a, b in zip(actual, expected)), (actual, expected)


def make_fixture(directory):
    texture_dir = directory / 'textures'
    texture_dir.mkdir()
    image = bpy.data.images.new('fixture-rgba', width=2, height=2, alpha=True)
    image.pixels[:] = [1, 0.2, 0.3, 0.5] * 4
    image.filepath_raw = str(texture_dir / '共享.png')
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)
    model = pmx.Model()
    model.name = 'Violet 合成测试'
    model.name_e = 'Violet synthetic fixture'
    model.comment = 'Independently generated test geometry; no third-party model assets.'
    for name, location, parent in [('センター', (0, 0, 0), -1), ('腕', (0, 1, 0), 0)]:
        bone = pmx.Bone()
        bone.name = name
        bone.name_e = name
        bone.location = location
        bone.parent = parent
        bone.displayConnection = (0, 1, 0)
        model.bones.append(bone)
    for index, co in enumerate([(0, 0, 0), (1, 0, 0), (0, 1, 0),
                                (2, 0, 0), (3, 0, 0), (2, 1, 0)]):
        vertex = pmx.Vertex()
        vertex.co = co
        vertex.normal = (0, 0, -1)
        vertex.uv = ((index % 3) / 2, 0.25)
        vertex.weight = pmx.BoneWeight()
        if index == 1:
            vertex.weight.type = pmx.BoneWeight.BDEF2
            vertex.weight.bones = [0, 1]
            vertex.weight.weights = [0.25]
        else:
            vertex.weight.bones = [0]
        model.vertices.append(vertex)
    # Coincident triangles cover the Blender 5.x transparency compatibility path.
    model.faces = [(0, 1, 2), (0, 1, 2), (3, 4, 5)]
    for path in ['textures\\共享.png', '.\\textures\\共享.png', 'textures\\missing.png']:
        texture = pmx.Texture()
        texture.path = path
        model.textures.append(texture)
    for index, (name, alpha) in enumerate([('同名材质', 1), ('同名材质', 0.5), ('待修复', 1)]):
        material = pmx.Material()
        material.name = name
        material.name_e = f'Material {index}'
        material.diffuse = (0.8, 0.7, 0.6, alpha)
        material.specular = (0.1, 0.1, 0.1)
        material.ambient = (0.2, 0.2, 0.2)
        material.edge_color = (0, 0, 0, 1)
        material.shininess = 16
        material.texture = index
        material.vertex_count = 3
        material.is_double_sided = index != 2
        model.materials.append(material)
    morph = pmx.VertexMorph('笑い', 'Smile', pmx.Morph.CATEGORY_MOUTH)
    offset = pmx.VertexMorphOffset()
    offset.index = 2
    offset.offset = (0, 0.2, 0)
    morph.offsets.append(offset)
    model.morphs.append(morph)
    morph = pmx.MaterialMorph('透明', 'Transparency', pmx.Morph.CATEGORY_OHTER)
    offset = pmx.MaterialMorphOffset()
    offset.index = 1
    offset.offset_type = pmx.MaterialMorphOffset.TYPE_ADD
    offset.diffuse_offset = (0, 0, 0, -0.25)
    offset.specular_offset = offset.ambient_offset = (0, 0, 0)
    offset.edge_color_offset = (0, 0, 0, 0)
    offset.edge_size_offset = 0
    offset.texture_factor = offset.sphere_texture_factor = offset.toon_texture_factor = (0, 0, 0, 0)
    morph.offsets.append(offset)
    model.morphs.append(morph)
    filepath = directory / '测试.pmx'
    pmx.save(str(filepath), model)
    return filepath


def snapshot():
    return {name: set(getattr(bpy.data, name)) for name in
            ('objects', 'meshes', 'armatures', 'materials', 'images', 'node_groups', 'texts', 'collections')}


def main():
    with tempfile.TemporaryDirectory(prefix='violet-pmx-') as temp:
        directory = Path(temp)
        filepath = make_fixture(directory)
        cube = bpy.data.objects['Cube']
        cube_materials = list(cube.data.materials)
        assert bpy.ops.violet.import_pmx(filepath=str(filepath)) == {'FINISHED'}
        root = workflow.model_root(bpy.context.object)
        meshes = workflow.model_meshes(root)
        assert len(meshes) == 1
        obj = meshes[0]
        mesh = obj.data
        materials = list(mesh.materials)
        assert len(mesh.vertices) == 6
        assert len(mesh.polygons) == 3
        assert [face.material_index for face in mesh.polygons] == [0, 1, 2]
        assert set(mesh.polygons[0].vertices) == {0, 1, 2}
        close(mesh.vertices[2].co, (0, 0, 0.08))
        assert mesh.has_custom_normals
        close(mesh.corner_normals[0].vector, (0, -1, 0))
        for polygon in mesh.polygons:
            for loop_index in polygon.loop_indices:
                vertex_index = mesh.loops[loop_index].vertex_index
                close(mesh.uv_layers.active.data[loop_index].uv, ((vertex_index % 3) / 2, 0.75))
        armature = Model(root).armature()
        assert len(armature.data.bones) == 2
        assert armature.data.bones['腕'].parent.name == 'センター'
        close([obj.vertex_groups['センター'].weight(1), obj.vertex_groups['腕'].weight(1)], (0.25, 0.75))
        close(mesh.shape_keys.key_blocks['笑い'].data[2].co, (0, 0, 0.096))
        material_morph = root.mmd_root.material_morphs['透明'].data[0]
        assert material_morph.material == materials[1].name
        assert materials[0] != materials[1]
        assert materials[0]['violet_pmx_name_j'] == materials[1]['violet_pmx_name_j'] == '同名材质'
        close([materials[1].mmd_material.alpha], [0.5])
        assert materials[2].use_backface_culling
        assert materials[0].node_tree.nodes['mmd_base_tex'].image == materials[1].node_tree.nodes['mmd_base_tex'].image
        assert materials[0].node_tree.nodes['mmd_shader'].inputs['Alpha'].is_linked is False
        assert materials[0].node_tree.nodes['mmd_shader'].inputs['Base Alpha'].is_linked
        close([materials[1].node_tree.nodes['mmd_shader'].inputs['Alpha'].default_value], [0.5])
        report = workflow.audit_materials(root)
        assert report['material_count'] == 3 and len(report['missing_textures']) == 1, report
        assert obj.users_collection[0].name.startswith('PMX - ')
        before_slots = list(mesh.materials)
        before_indices = [face.material_index for face in mesh.polygons]
        workflow.organize_materials(root)
        assert list(mesh.materials) == before_slots
        assert [face.material_index for face in mesh.polygons] == before_indices
        assert list(cube.data.materials) == cube_materials

        # Two matching basenames are ambiguous, so no unrelated texture is substituted.
        repair_dir = directory / 'repair'
        for subdir in ('a', 'b'):
            target = repair_dir / subdir
            target.mkdir(parents=True)
            (target / 'missing.png').write_bytes((directory / 'textures/共享.png').read_bytes())
        report = workflow.organize_materials(root, str(repair_dir))
        assert len(report['missing_textures']) == 1
        (repair_dir / 'b/missing.png').unlink()
        report = workflow.organize_materials(root, str(repair_dir))
        assert not report['missing_textures'] and report['repaired_textures'] == 1, report
        assert not workflow.organize_materials(root, str(repair_dir))['repaired_textures']

        # An image with a deliberately different color space must not be consolidated.
        image_node = materials[1].node_tree.nodes['mmd_base_tex']
        different = image_node.image.copy()
        different.colorspace_settings.name = 'Non-Color'
        image_node.image = different
        workflow.organize_materials(root)
        assert image_node.image == different
        assert image_node.image != materials[0].node_tree.nodes['mmd_base_tex'].image

        # Independent reimport preserves both models and material morph targets.
        second, _ = workflow.import_pmx(bpy.context, str(filepath))
        assert second != root
        second_materials = workflow.model_materials(second)
        assert not set(second_materials).intersection(materials)
        assert second.mmd_root.material_morphs['透明'].data[0].material == second_materials[1].name

        # Invalid files, and a failure after scene creation, leave no partial model.
        broken = directory / 'broken.pmx'
        broken.write_bytes(filepath.read_bytes()[:100])
        before = snapshot()
        try:
            workflow.import_pmx(bpy.context, str(broken))
            raise AssertionError('Truncated PMX was accepted')
        except pmx.InvalidFileError:
            pass
        assert snapshot() == before
        original_execute = PMXImporter.execute

        def fail_after_import(self, **args):
            original_execute(self, **args)
            raise RuntimeError('injected post-import failure')

        with patch.object(PMXImporter, 'execute', fail_after_import):
            try:
                workflow.import_pmx(bpy.context, str(filepath))
                raise AssertionError('Expected injected failure')
            except RuntimeError as exc:
                assert str(exc) == 'injected post-import failure'
        assert snapshot() == before
        packed, failures = workflow.pack_textures(root)
        assert packed > 0 and not failures, failures
        saved_root_name = root.name
        blend_path = directory / 'portable.blend'
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
        for path in directory.rglob('*.png'):
            path.unlink()
        bpy.ops.wm.open_mainfile(filepath=str(blend_path))
        root = bpy.data.objects[saved_root_name]
        assert not workflow.audit_materials(root)['missing_textures']
        assert len(workflow.model_meshes(root)[0].data.shape_keys.key_blocks) == 2
        text = bpy.data.texts[root['violet_material_report']]
        assert json.loads(text.as_string())['material_count'] == 3
        # Prove the shader can compile and render, beyond checking its node metadata.
        bpy.context.scene.render.engine = 'CYCLES'
        bpy.context.scene.cycles.device = 'CPU'
        bpy.context.scene.cycles.samples = 1
        bpy.context.scene.cycles.use_denoising = False
        bpy.context.scene.render.resolution_x = bpy.context.scene.render.resolution_y = 32
        bpy.context.scene.render.resolution_percentage = 100
        for scene_object in bpy.context.scene.objects:
            if scene_object.type == 'MESH':
                scene_object.hide_render = scene_object != workflow.model_meshes(root)[0]
        camera = bpy.context.scene.camera
        camera.location = (0.12, -0.5, 0.15)
        from mathutils import Vector
        camera.rotation_euler = (Vector((0.12, 0, 0.04)) - camera.location).to_track_quat('-Z', 'Y').to_euler()
        bpy.context.scene.render.filepath = str(directory / 'preview.png')
        bpy.ops.render.render(write_still=True)
        assert (directory / 'preview.png').stat().st_size > 0
        preview = bpy.data.images.load(str(directory / 'preview.png'))
        red = list(preview.pixels)[::4]
        assert max(red) - min(red) > 0.01
        print('VIOLET_PMX_OK: geometry, UV, normals, bones, weights, morphs, materials, textures, rollback, save/load, render')
        print('VIOLET_PMX_BLENDER_VERSION:', bpy.app.version_string)


main()
