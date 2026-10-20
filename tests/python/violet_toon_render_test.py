# SPDX-FileCopyrightText: 2026 VioletBlender contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Render generated MMD materials to check Toon bands, texture color and alpha.

Run with an Eevee-capable device, or Linux Mesa software rendering. No external
models or images are used. VIOLET_TOON_PREVIEW_DIR keeps the PNGs and metrics.
"""

import json
import math
import os
from pathlib import Path
import sys
import tempfile

import addon_utils
import bpy


REPO = Path(__file__).resolve().parents[2]
if not os.environ.get('VIOLET_PMX_INSTALLED'):
    sys.path.insert(0, str(REPO / 'scripts/addons_core'))
if not addon_utils.check('violet_pmx')[1]:
    assert addon_utils.enable('violet_pmx', default_set=True, persistent=True) is not None

from mmd_tools.core.model import Model
from violet_pmx import toon


WIDTH, HEIGHT, CAMERA_WIDTH = 960, 320, 18.0
COSINES = [0.02 + 0.98 * index / 15 for index in range(16)]


def material(name, alpha=1.0, texture=None):
    result = bpy.data.materials.new(name)
    result.use_nodes = True
    settings = result.mmd_material
    settings.diffuse_color = (1.0, 1.0, 1.0)
    settings.ambient_color = (0.0, 0.0, 0.0)
    settings.specular_color = (0.0, 0.0, 0.0)
    settings.alpha = alpha
    settings.is_double_sided = True
    if texture:
        image_node = result.node_tree.nodes.new('ShaderNodeTexImage')
        image_node.name = 'mmd_base_tex'
        image_node.image = texture
        image_node.interpolation = 'Closest'
        shader = result.node_tree.nodes['mmd_shader']
        result.node_tree.links.new(image_node.outputs['Color'], shader.inputs['Base Tex'])
        result.node_tree.links.new(image_node.outputs['Alpha'], shader.inputs['Base Alpha'])
    return result


def patch(name, x, y, width, height, cosine, mat, armature):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(-width / 2, -height / 2, 0), (width / 2, -height / 2, 0),
                      (width / 2, height / 2, 0), (-width / 2, height / 2, 0)],
                     [], [(0, 1, 2, 3)])
    mesh.polygons[0].use_smooth = True
    normal = (math.sqrt(1 - cosine * cosine), 0, cosine)
    mesh.normals_split_custom_set_from_vertices([normal] * 4)
    uv = mesh.uv_layers.new(name='UVMap')
    for loop, coordinate in zip(uv.data, [(0, 0), (1, 0), (1, 1), (0, 1)], strict=True):
        loop.uv = coordinate
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = armature
    obj.location = (x, y, 0)
    mesh.materials.append(mat)
    return obj


def render(directory, name):
    path = directory / (name + '.png')
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        assert tuple(image.size) == (WIDTH, HEIGHT)
        return list(image.pixels[:])
    finally:
        bpy.data.images.remove(image)


def sample(pixels, x, y, radius=3):
    center_x = int((x / CAMERA_WIDTH + 0.5) * WIDTH)
    camera_height = CAMERA_WIDTH * HEIGHT / WIDTH
    center_y = int((y / camera_height + 0.5) * HEIGHT)
    points = [((row * WIDTH + column) * 4)
              for row in range(center_y - radius, center_y + radius + 1)
              for column in range(center_x - radius, center_x + radius + 1)]
    return tuple(sum(pixels[offset + channel] for offset in points) / len(points)
                 for channel in range(4))


def plateaus(pixels):
    values = [sample(pixels, index - 7.5, 1.2)[0] for index in range(16)]
    levels = []
    for value in sorted(values):
        if not levels or abs(value - levels[-1]) > 0.035:
            levels.append(value)
    return values, levels


def check_texture_and_alpha(pixels):
    results = []
    for x, expected in [(-4.0, 0.8), (0.0, 0.4), (4.0, 0.0)]:
        red = sample(pixels, x - 0.6, -1.2, radius=5)
        green = sample(pixels, x + 0.6, -1.2, radius=5)
        assert abs(red[3] - expected) < 0.065, (expected, red)
        assert abs(green[3] - expected) < 0.065, (expected, green)
        if expected:
            assert red[0] > red[1] * 3 and red[0] > 0.1, red
            assert green[1] > green[0] * 3 and green[1] > 0.1, green
        results.append({'expected_alpha': expected, 'red': red, 'green': green})
    return results


def main(directory):
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE_NEXT'
    scene.eevee.taa_render_samples = 64
    scene.render.resolution_x = WIDTH
    scene.render.resolution_y = HEIGHT
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.film_transparent = True
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.0

    camera = bpy.data.objects.new('Toon test camera', bpy.data.cameras.new('Toon test camera'))
    scene.collection.objects.link(camera)
    camera.location = (0, 0, 10)
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = CAMERA_WIDTH
    scene.camera = camera
    sun = bpy.data.objects.new('Toon test sun', bpy.data.lights.new('Toon test sun', 'SUN'))
    scene.collection.objects.link(sun)
    sun.data.energy = math.pi
    sun.data.use_shadow = False

    model = Model.create('Generated Toon render model')
    root = model.rootObject()
    armature = model.armature()
    white = material('Toon white')
    for index, cosine in enumerate(COSINES):
        patch('Normal sample %02d' % index, index - 7.5, 1.2, 0.85, 0.9,
              cosine, white, armature)

    texture = bpy.data.images.new('Generated red-green alpha texture', width=2, height=1, alpha=True)
    texture.pixels[:] = [1, 0.05, 0.02, 0.8, 0.02, 1, 0.05, 0.8]
    texture.pack()
    for x, alpha in [(-4.0, 1.0), (0.0, 0.5), (4.0, 0.0)]:
        mat = material('Toon texture alpha %.1f' % alpha, alpha, texture)
        patch('Texture sample %.1f' % alpha, x, -1.2, 3.0, 1.1, 1.0, mat, armature)

    baseline = render(directory, 'original')
    root.violet_toon_threshold = 0.6
    root.violet_toon_shadow_brightness = 0.2
    root.violet_toon_preset = 'TWO_BANDS'
    toon.apply(root)
    two = render(directory, 'two-bands')
    two_values, two_levels = plateaus(two)
    assert len(two_levels) == 2 and two_levels[-1] - two_levels[0] > 0.2, two_values
    two_alpha = check_texture_and_alpha(two)
    root.violet_toon_preset = 'THREE_BANDS'
    toon.update(root)
    three = render(directory, 'three-bands')
    three_values, three_levels = plateaus(three)
    assert len(three_levels) == 3 and three_levels[-1] - three_levels[0] > 0.2, three_values
    three_alpha = check_texture_and_alpha(three)
    toon.restore(root)
    restored = render(directory, 'restored')
    error = sum(abs(left - right) for left, right in zip(baseline, restored, strict=True)) / len(baseline)
    assert error < 0.003, error
    metrics = {'blender_version': bpy.app.version_string,
               'two_band_samples': two_values, 'two_band_levels': two_levels,
               'three_band_samples': three_values, 'three_band_levels': three_levels,
               'two_band_texture_alpha': two_alpha, 'three_band_texture_alpha': three_alpha,
               'restored_mean_absolute_error': error}
    (directory / 'metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    print('VIOLET_TOON_RENDER_OK: two/three lighting bands, texture colors, alpha, original restoration')
    print('VIOLET_TOON_RENDER_BLENDER_VERSION:', bpy.app.version_string)
    print('VIOLET_TOON_RENDER_METRICS:', json.dumps(metrics))


if __name__ == '__main__':
    preview_dir = os.environ.get('VIOLET_TOON_PREVIEW_DIR')
    if preview_dir:
        destination = Path(preview_dir)
        destination.mkdir(parents=True, exist_ok=True)
        main(destination)
    else:
        with tempfile.TemporaryDirectory(prefix='violet-toon-render-') as temp:
            main(Path(temp))
