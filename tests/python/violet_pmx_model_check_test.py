# SPDX-FileCopyrightText: 2026 VioletBlender contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Exercise the model-check CLI in separate Blender processes with synthetic PMX."""

import json
from pathlib import Path
import runpy
import subprocess
import tempfile

import bpy


HERE = Path(__file__).resolve().parent
FIXTURE = runpy.run_path(str(HERE / 'violet_pmx_test.py'), run_name='violet_fixture')


def run_check(arguments, expect_success=True):
    command = [bpy.app.binary_path, '--background', '--factory-startup',
               '--python-exit-code', '1', '--python', str(HERE / 'violet_pmx_model_check.py'),
               '--', *map(str, arguments)]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding='utf-8', errors='replace', timeout=180)
    if expect_success and result.returncode != 0:
        print(result.stdout[-12000:])
        raise AssertionError(f'Model-check CLI failed: {result.returncode}')
    if not expect_success:
        assert result.returncode != 0, 'Invalid model was reported as successful'
    return result


def main():
    from violet_pmx import workflow

    with tempfile.TemporaryDirectory(prefix='violet-model-check-') as temp:
        directory = Path(temp)
        filepath = FIXTURE['make_fixture'](directory)
        missing_output = directory / 'missing-output'
        run_check(['--model', filepath, '--output', missing_output])
        report = json.loads((missing_output / 'report.json').read_text(encoding='utf-8'))
        assert report['material_count'] == 3
        assert len(report['missing_textures']) == 1
        assert (missing_output / 'model.blend').stat().st_size > 0

        repair_directory = directory / 'repair'
        repair_directory.mkdir()
        (repair_directory / 'missing.png').write_bytes((directory / 'textures/共享.png').read_bytes())
        output = directory / 'portable-output'
        run_check(['--model', filepath, '--output', output, '--texture-dir', repair_directory])
        report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
        assert report['material_count'] == 3 and not report['missing_textures'], report
        for material in report['materials']:
            assert all(texture['status'] == 'packed' for texture in material['textures']), material
        repaired = report['materials'][2]
        base_texture = next(texture for texture in repaired['textures'] if texture['role'] == 'Base texture')
        assert base_texture['alpha_mode'] != 'NONE', base_texture

        # Portability means the saved output remains complete without source PNG files.
        for path in directory.rglob('*.png'):
            path.unlink()
        bpy.ops.wm.open_mainfile(filepath=str(output / 'model.blend'))
        roots = [obj for obj in bpy.data.objects if obj.mmd_type == 'ROOT']
        assert len(roots) == 1
        root = roots[0]
        assert not workflow.audit_materials(root)['missing_textures']
        meshes = workflow.model_meshes(root)
        assert len(meshes) == 1 and len(meshes[0].data.vertices) == 6
        assert {obj for obj in bpy.context.scene.objects if obj.type == 'MESH'} == set(meshes), \
            'Saved review scene contains meshes outside the imported model'
        assert [face.material_index for face in meshes[0].data.polygons] == [0, 1, 2]
        assert meshes[0].data.shape_keys.key_blocks.get('笑い') is not None
        material = meshes[0].data.materials[2]
        image = material.node_tree.nodes['mmd_base_tex'].image
        assert image.packed_file and image.alpha_mode != 'NONE'

        invalid_output = directory / 'invalid-output'
        run_check(['--model', directory / 'absent.pmx', '--output', invalid_output], expect_success=False)
        assert not (invalid_output / 'report.json').exists()
        assert not (invalid_output / 'model.blend').exists()
        print('VIOLET_PMX_MODEL_CHECK_OK: CLI arguments, missing report, recovery, portable blend, failure exit')


if __name__ == '__main__':
    main()
