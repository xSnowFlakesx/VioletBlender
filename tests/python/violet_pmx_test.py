# SPDX-FileCopyrightText: 2026 VioletBlender contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""End-to-end PMX fixture tests, run by Blender rather than system Python.

No third-party character models are used. The fixture is generated from scratch.
"""

import json
import os
from pathlib import Path
import sys
import struct
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


def close_alpha(actual, expected):
    # The fixture PNG stores alpha in 8 bits, so 0.5 is quantized to 128/255.
    assert abs(float(actual) - expected) < 0.02, (actual, expected)


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
        first_report = report['materials'][0]
        assert first_report['textures'][0]['alpha_mode'] == materials[0].node_tree.nodes['mmd_base_tex'].image.alpha_mode
        assert first_report['shader_alpha'] == {'default': 1.0, 'linked': False}, first_report
        assert first_report['shader_base_alpha']['linked'] is True, first_report
        assert first_report['render_method'] is not None, first_report
        assert obj.users_collection[0].name.startswith('PMX - ')
        before_slots = list(mesh.materials)
        before_indices = [face.material_index for face in mesh.polygons]
        workflow.organize_materials(root)
        assert list(mesh.materials) == before_slots
        assert [face.material_index for face in mesh.polygons] == before_indices
        assert list(cube.data.materials) == cube_materials

        # A match at the search root and one in a child are ambiguous.
        repair_dir = directory / 'repair'
        repair_dir.mkdir()
        root_match = repair_dir / 'missing.png'
        root_match.write_bytes((directory / 'textures/共享.png').read_bytes())
        child_match = repair_dir / 'other' / 'missing.png'
        child_match.parent.mkdir()
        child_match.write_bytes((directory / 'textures/共享.png').read_bytes())
        report = workflow.organize_materials(root, str(repair_dir))
        assert len(report['missing_textures']) == 1
        assert len(report['ambiguous_textures']) == 1, report
        assert set(report['ambiguous_textures'][0]['candidates']) == {str(root_match), str(child_match)}
        (repair_dir / 'other/missing.png').unlink()
        # A real image with explicit NONE at this path must not be reused for
        # the blank missing-file placeholder's automatic NONE.
        real_none = bpy.data.images.load(str(root_match), check_existing=False)
        real_none.alpha_mode = 'NONE'
        report = workflow.organize_materials(root, str(repair_dir))
        assert not report['missing_textures'] and report['repaired_textures'] == 1, report
        repaired_image = materials[2].node_tree.nodes['mmd_base_tex'].image
        assert repaired_image.alpha_mode == 'STRAIGHT', repaired_image.alpha_mode
        assert repaired_image != real_none and real_none.alpha_mode == 'NONE'
        close_alpha(repaired_image.pixels[3], 0.5)
        assert not workflow.organize_materials(root, str(repair_dir))['repaired_textures']

        # An image with a deliberately different color space must not be consolidated.
        image_node = materials[1].node_tree.nodes['mmd_base_tex']
        different = image_node.image.copy()
        different.colorspace_settings.name = 'Non-Color'
        different.alpha_mode = 'PREMUL'
        image_node.image = different
        workflow.organize_materials(root)
        assert image_node.image == different
        assert image_node.image.alpha_mode == 'PREMUL'
        assert image_node.image != materials[0].node_tree.nodes['mmd_base_tex'].image
        none_node = materials[0].node_tree.nodes['mmd_base_tex']
        explicit_none = none_node.image.copy()
        explicit_none.alpha_mode = 'NONE'
        none_node.image = explicit_none
        workflow.organize_materials(root)
        assert none_node.image.alpha_mode == 'NONE'

        # Independent reimport preserves both models and material morph targets.
        second, _ = workflow.import_pmx(bpy.context, str(filepath))
        assert second != root
        second_materials = workflow.model_materials(second)
        assert not set(second_materials).intersection(materials)
        assert second.mmd_root.material_morphs['透明'].data[0].material == second_materials[1].name
        # The PMX exact relative path wins even when its basename is duplicated.
        exact_dir = directory / 'exact-search'
        exact_match = exact_dir / 'textures' / 'missing.png'
        exact_match.parent.mkdir(parents=True)
        exact_match.write_bytes((directory / 'textures/共享.png').read_bytes())
        (exact_dir / 'missing.png').write_bytes((directory / 'textures/共享.png').read_bytes())
        duplicate = exact_dir / 'other' / 'missing.png'
        duplicate.parent.mkdir()
        duplicate.write_bytes((directory / 'textures/共享.png').read_bytes())
        report = workflow.organize_materials(second, str(exact_dir))
        assert report['repaired_textures'] == 1 and not report['missing_textures'], report
        assert not report['ambiguous_textures'], report
        exact_image = second_materials[2].node_tree.nodes['mmd_base_tex'].image
        assert workflow._canonical(bpy.path.abspath(exact_image.filepath)) == workflow._canonical(exact_match)
        assert exact_image.alpha_mode == 'STRAIGHT'
        close_alpha(exact_image.pixels[3], 0.5)
        # A missing placeholder with a user-selected PREMUL mode keeps it.
        node2 = second_materials[2].node_tree.nodes['mmd_base_tex']
        premul_placeholder = bpy.data.images.new('explicit-premul-missing', 1, 1)
        premul_placeholder.source = 'FILE'
        premul_placeholder.filepath = str(directory / 'textures/not-yet-restored.png')
        premul_placeholder['violet_missing_texture'] = True
        premul_placeholder.alpha_mode = 'PREMUL'
        node2.image = premul_placeholder
        report = workflow.organize_materials(second, str(exact_dir))
        assert report['repaired_textures'] == 1 and not report['missing_textures'], report
        assert node2.image.alpha_mode == 'PREMUL', node2.image.alpha_mode

        # Invalid files, and a failure after scene creation, leave no partial model.
        broken = directory / 'broken.pmx'
        broken.write_bytes(filepath.read_bytes()[:100])
        before = snapshot()
        unsupported = directory / 'pmx21.pmx'
        payload = filepath.read_bytes()
        unsupported.write_bytes(payload[:4] + struct.pack('<f', 2.1) + payload[8:])
        try:
            workflow.import_pmx(bpy.context, str(unsupported))
            raise AssertionError('Unsupported PMX 2.1 was accepted')
        except pmx.UnsupportedVersionError:
            pass
        assert snapshot() == before
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
                workflow.import_pmx(bpy.context, str(filepath), import_physics=True)
                raise AssertionError('Expected injected failure')
            except RuntimeError as exc:
                assert str(exc) == 'injected post-import failure'
        assert snapshot() == before
        assert bpy.context.scene.rigidbody_world is None
        packed, failures = workflow.pack_textures(root)
        assert packed > 0 and not failures, failures
        saved_root_name = root.name
        blend_path = directory / 'portable.blend'
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
        for path in directory.rglob('*.png'):
            path.unlink()
        bpy.ops.wm.open_mainfile(filepath=str(blend_path))
        root = bpy.data.objects[saved_root_name]
        materials = workflow.model_materials(root)
        assert not workflow.audit_materials(root)['missing_textures']
        packed_restored = materials[2].node_tree.nodes['mmd_base_tex'].image
        assert workflow._is_packed(packed_restored) and packed_restored.alpha_mode == 'STRAIGHT'
        close_alpha(packed_restored.pixels[3], 0.5)
        assert len(workflow.model_meshes(root)[0].data.shape_keys.key_blocks) == 2
        text = bpy.data.texts[root['violet_material_report']]
        assert json.loads(text.as_string())['material_count'] == 3
        # Prove both PMX alpha and texture alpha survive pack/save/reload in an
        # isolated render, without coincident faces or edge pixels in the sample.
        bpy.context.scene.render.engine = 'CYCLES'
        bpy.context.scene.cycles.device = 'CPU'
        bpy.context.scene.cycles.samples = 64
        bpy.context.scene.cycles.seed = 0
        bpy.context.scene.cycles.use_animated_seed = False
        bpy.context.scene.cycles.use_denoising = False
        bpy.context.scene.render.film_transparent = True
        bpy.context.scene.render.resolution_x = bpy.context.scene.render.resolution_y = 128
        bpy.context.scene.render.resolution_percentage = 100
        for scene_object in bpy.context.scene.objects:
            scene_object.hide_render = True
        camera = bpy.context.scene.camera
        camera.location = (0, 0, 4)
        camera.rotation_euler = (0, 0, 0)
        camera.data.type = 'ORTHO'
        camera.data.ortho_scale = 4
        mesh = bpy.data.meshes.new('alpha-isolated-triangles')
        mesh.from_pydata([(-1.6, -0.8, 0), (-0.4, -0.8, 0), (-1, 0.8, 0),
                          (0.4, -0.8, 0), (1.6, -0.8, 0), (1, 0.8, 0)], [],
                         [(0, 1, 2), (3, 4, 5)])
        mesh.materials.append(materials[2])
        mesh.materials.append(materials[1])
        mesh.polygons[1].material_index = 1
        uv = mesh.uv_layers.new(name='UVMap')
        for polygon in mesh.polygons:
            for loop_index in polygon.loop_indices:
                uv.data[loop_index].uv = (0.5, 0.5)
        test_object = bpy.data.objects.new('isolated-alpha-check', mesh)
        bpy.context.scene.collection.objects.link(test_object)
        test_object.hide_render = False
        preview_path = directory / 'alpha-preview.png'
        bpy.context.scene.render.image_settings.file_format = 'PNG'
        bpy.context.scene.render.image_settings.color_mode = 'RGBA'
        bpy.context.scene.render.filepath = str(preview_path)
        bpy.ops.render.render(write_still=True)
        result = bpy.data.images.load(str(preview_path), check_existing=False)
        result_pixels = list(result.pixels)
        render_width, render_height = result.size[:]
        assert len(result_pixels) == render_width * render_height * 4, (result.size[:], len(result_pixels))
        def alpha_mean(world_x, world_y=0):
            radius = 0.16
            x0 = int(((world_x - radius) / camera.data.ortho_scale + 0.5) * render_width)
            x1 = int(((world_x + radius) / camera.data.ortho_scale + 0.5) * render_width)
            y0 = int(((world_y - radius) / camera.data.ortho_scale + 0.5) * render_height)
            y1 = int(((world_y + radius) / camera.data.ortho_scale + 0.5) * render_height)
            values = [result_pixels[(y * render_width + x) * 4 + 3]
                      for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
            return sum(values) / len(values)
        close_alpha(alpha_mean(-1), 0.5)
        close_alpha(alpha_mean(1), 0.25)
        print('VIOLET_PMX_OK: geometry, UV, normals, bones, weights, morphs, materials, textures, rollback, save/load, render')
        print('VIOLET_PMX_BLENDER_VERSION:', bpy.app.version_string)


if __name__ == '__main__':
    main()
