# SPDX-FileCopyrightText: 2026 VioletBlender contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generated-fixture tests for transactional PMX-scoped VMD import."""

import json
import math
import os
from pathlib import Path
import runpy
import struct
import tempfile
import sys
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

from mmd_tools.core.model import Model
from mmd_tools.core.vmd.importer import VMDImporter
from violet_pmx import motion, workflow


def write_vmd(path, bones=(), morphs=()):
    with open(path, 'wb') as stream:
        stream.write(struct.pack('<30s20s', b'Vocaloid Motion Data 0002', b'Synthetic fixture'))
        stream.write(struct.pack('<I', len(bones)))
        interpolation = [20, 20, 107, 107] * 16
        for name, frame, location, rotation in bones:
            stream.write(struct.pack('<15sI3f4f64b', name.encode('cp932'), frame,
                                     *location, *rotation, *interpolation))
        stream.write(struct.pack('<I', len(morphs)))
        for name, frame, weight in morphs:
            stream.write(struct.pack('<15sIf', name.encode('cp932'), frame, weight))
        # Empty camera, light, self-shadow and property sections.
        stream.write(struct.pack('<IIII', 0, 0, 0, 0))


def make_motion(directory, name='motion.vmd'):
    path = directory / name
    write_vmd(path,
              bones=[
                  ('腕', 0, (0, 0, 0), (0, 0, 0, 1)),
                  ('腕', 30, (2, 0, 0), (math.sqrt(0.5), 0, 0, math.sqrt(0.5))),
                  ('unknown-bone', 900, (4, 0, 0), (0, 0, 0, 1)),
              ],
              morphs=[
                  ('笑い', 0, 0.0), ('笑い', 30, 1.0),
                  ('透明', 900, 0.75), ('unknown-morph', 1200, 1.0),
              ])
    return path


def action_slot(anim_data):
    return getattr(anim_data, 'action_slot', None)


def ensure_alternate_slot(action, anim_data, id_type):
    if not hasattr(action, 'slots') or not hasattr(anim_data, 'action_slot') or not len(action.slots):
        return None
    current = anim_data.action_slot
    alternate = action.slots.new(name='Violet test alternate', id_type=id_type)
    anim_data.action_slot = alternate
    assert anim_data.action_slot == alternate
    return alternate


def action_curve(action, data_path, index=0):
    curve = action.fcurves.find(data_path, index=index)
    assert curve is not None, (action.name, data_path, index)
    return curve


def assert_vector_close(actual, expected, tolerance=1e-5):
    assert len(actual) == len(expected), (actual, expected)
    assert all(abs(float(a) - float(b)) <= tolerance for a, b in zip(actual, expected)), (actual, expected)


def assert_motion_evaluates(root, start_frame, scale, bone_name='腕'):
    armature = Model(root).armature()
    mesh = next(Model(root).meshes())
    arm_action = armature.animation_data.action
    key_action = mesh.data.shape_keys.animation_data.action
    bone_path = f'pose.bones["{bone_name}"].location'
    rotation_path = f'pose.bones["{bone_name}"].rotation_quaternion'
    location_curves = [action_curve(arm_action, bone_path, axis) for axis in range(3)]
    rotation_curves = [action_curve(arm_action, rotation_path, axis) for axis in range(4)]
    weight_curve = action_curve(key_action, 'key_blocks["笑い"].value')
    expected_values = tuple(curve.evaluate(start_frame + 30) for curve in location_curves)
    assert_vector_close(expected_values, (2.0 * scale, 0, 0))
    assert abs(weight_curve.evaluate(start_frame) - 0.0) < 1e-5
    assert abs(weight_curve.evaluate(start_frame + 15) - 0.5) < 1e-4
    assert abs(weight_curve.evaluate(start_frame + 30) - 1.0) < 1e-5
    assert_vector_close([curve.evaluate(start_frame + 30) for curve in rotation_curves],
                        (math.sqrt(0.5), -math.sqrt(0.5), 0, 0))
    assert_vector_close([curve.evaluate(start_frame + 15) for curve in rotation_curves],
                        ((1 + math.sqrt(0.5)) / 2, -math.sqrt(0.5) / 2, 0, 0))

    scene = bpy.context.scene
    scene.frame_set(start_frame)
    pose_bone = armature.pose.bones[bone_name]
    assert_vector_close(pose_bone.location, [curve.evaluate(start_frame) for curve in location_curves])
    assert_vector_close(pose_bone.rotation_quaternion,
                        [curve.evaluate(start_frame) for curve in rotation_curves])
    assert abs(mesh.data.shape_keys.key_blocks['笑い'].value - 0.0) < 1e-5
    scene.frame_set(start_frame + 15)
    actual_mid = tuple(pose_bone.location)
    expected_mid = tuple(curve.evaluate(start_frame + 15) for curve in location_curves)
    assert_vector_close(actual_mid, expected_mid)
    assert_vector_close(actual_mid, (scale, 0, 0))
    assert_vector_close(pose_bone.rotation_quaternion,
                        [curve.evaluate(start_frame + 15) for curve in rotation_curves])
    assert_vector_close(pose_bone.rotation_quaternion,
                        ((1 + math.sqrt(0.5)) / 2, -math.sqrt(0.5) / 2, 0, 0))
    assert abs(mesh.data.shape_keys.key_blocks['笑い'].value - 0.5) < 1e-4
    scene.frame_set(start_frame + 30)
    assert_vector_close(pose_bone.location,
                        [curve.evaluate(start_frame + 30) for curve in location_curves])
    assert_vector_close(pose_bone.location, (2.0 * scale, 0, 0))
    assert_vector_close(pose_bone.rotation_quaternion,
                        [curve.evaluate(start_frame + 30) for curve in rotation_curves])
    assert abs(mesh.data.shape_keys.key_blocks['笑い'].value - 1.0) < 1e-5


def main():
    fixture = runpy.run_path(str(REPO / 'tests/python/violet_pmx_test.py'),
                             run_name='violet_pmx_fixture')
    make_fixture = fixture['make_fixture']
    with tempfile.TemporaryDirectory(prefix='violet-vmd-') as temp:
        directory = Path(temp)
        pmx_path = make_fixture(directory)
        root_a, _ = workflow.import_pmx(bpy.context, str(pmx_path), scale=0.08)
        root_b, _ = workflow.import_pmx(bpy.context, str(pmx_path), scale=0.16)
        motion_path = make_motion(directory)
        arm_a = Model(root_a).armature()
        mesh_a = next(Model(root_a).meshes())
        arm_b = Model(root_b).armature()
        mesh_b = next(Model(root_b).meshes())
        arm_a.data.bones['腕'].name = 'renamed_arm'
        assert arm_a.pose.bones['renamed_arm'].mmd_bone.name_j == '腕'
        assert root_a['violet_pmx_scale'] == 0.08
        assert root_b['violet_pmx_scale'] == 0.16

        report = motion.import_vmd(bpy.context, root_a, str(motion_path), start_frame=10)
        assert report['scale_source'] == 'saved PMX import scale'
        assert report['matched_bones'] == ['腕']
        assert report['unmatched_bones'] == ['unknown-bone']
        assert report['matched_morphs'] == ['笑い']
        assert {entry['name'] for entry in report['unmatched_morphs']} == {'透明', 'unknown-morph'}
        assert {entry['name'] for entry in report['morphs_requiring_assembly']} == {'透明'}
        assert report['frame_range'] == [10, 40], report['frame_range']
        assert (bpy.context.scene.render.fps, bpy.context.scene.render.fps_base) == (30, 1.0)
        assert (bpy.context.scene.frame_start, bpy.context.scene.frame_end) == (10, 40)
        motion_report_text = bpy.data.texts[root_a['violet_vmd_report']]
        assert json.loads(motion_report_text.as_string())['matched_bones'] == ['腕']
        assert mesh_b.data.shape_keys.animation_data is None
        assert arm_b.animation_data is None
        assert all(abs(value) < 1e-7 for value in arm_b.pose.bones['腕'].location)
        assert abs(mesh_b.data.shape_keys.key_blocks['笑い'].value) < 1e-7
        assert_motion_evaluates(root_a, 10, 0.08, bone_name='renamed_arm')
        assert arm_a.animation_data.action_blend_type == 'REPLACE'
        assert abs(arm_a.animation_data.action_influence - 1.0) < 1e-7
        assert mesh_a.data.shape_keys.animation_data.action_blend_type == 'REPLACE'
        assert abs(mesh_a.data.shape_keys.animation_data.action_influence - 1.0) < 1e-7

        # A failure after the armature was assigned must roll back all targets,
        # values, timeline settings, Action slots, and newly created datablocks.
        old_arm_action = arm_a.animation_data.action
        old_key_action = mesh_a.data.shape_keys.animation_data.action
        old_arm_fake_user = old_arm_action.use_fake_user
        old_key_fake_user = old_key_action.use_fake_user
        if hasattr(arm_a.animation_data, 'action_blend_type'):
            arm_a.animation_data.action_blend_type = 'ADD'
            arm_a.animation_data.action_influence = 0.35
            mesh_a.data.shape_keys.animation_data.action_blend_type = 'ADD'
            mesh_a.data.shape_keys.animation_data.action_influence = 0.4
        old_arm_slot = ensure_alternate_slot(old_arm_action, arm_a.animation_data, 'OBJECT')
        old_key_slot = ensure_alternate_slot(old_key_action, mesh_a.data.shape_keys.animation_data, 'KEY')
        arm_a.pose.bones['renamed_arm'].location = (0.15, 0.2, 0.25)
        mesh_a.data.shape_keys.key_blocks['笑い'].value = 0.3
        mesh_a.data.shape_keys.key_blocks['笑い'].slider_min = -0.25
        saved_pose = tuple(arm_a.pose.bones['renamed_arm'].location)
        saved_weight = mesh_a.data.shape_keys.key_blocks['笑い'].value
        saved_slider = (mesh_a.data.shape_keys.key_blocks['笑い'].slider_min,
                        mesh_a.data.shape_keys.key_blocks['笑い'].slider_max)
        saved_scene = (bpy.context.scene.frame_current, bpy.context.scene.frame_subframe,
                       bpy.context.scene.frame_start,
                       bpy.context.scene.frame_end, bpy.context.scene.render.fps,
                       bpy.context.scene.render.fps_base)
        action_ids_before = set(bpy.data.actions)
        text_ids_before = set(bpy.data.texts)
        original_assign = VMDImporter.assign
        assignments = 0

        def fail_after_armature(self, target, action_name=None):
            nonlocal assignments
            result = original_assign(self, target, action_name)
            assignments += 1
            if assignments == 1:
                raise RuntimeError('synthetic failure after partial import')
            return result

        try:
            with patch.object(VMDImporter, 'assign', fail_after_armature):
                motion.import_vmd(bpy.context, root_a, str(motion_path), start_frame=50)
            raise AssertionError('Injected importer failure did not escape')
        except RuntimeError as exc:
            assert 'synthetic failure' in str(exc)
        assert arm_a.animation_data.action == old_arm_action
        assert mesh_a.data.shape_keys.animation_data.action == old_key_action
        assert arm_a.animation_data.action.use_fake_user == old_arm_fake_user
        assert mesh_a.data.shape_keys.animation_data.action.use_fake_user == old_key_fake_user
        if old_arm_slot is not None:
            assert action_slot(arm_a.animation_data) == old_arm_slot
        if old_key_slot is not None:
            assert action_slot(mesh_a.data.shape_keys.animation_data) == old_key_slot
        assert_vector_close(arm_a.pose.bones['renamed_arm'].location, saved_pose)
        assert abs(mesh_a.data.shape_keys.key_blocks['笑い'].value - saved_weight) < 1e-7
        assert (mesh_a.data.shape_keys.key_blocks['笑い'].slider_min,
                mesh_a.data.shape_keys.key_blocks['笑い'].slider_max) == saved_slider
        assert (bpy.context.scene.frame_current, bpy.context.scene.frame_subframe,
                bpy.context.scene.frame_start,
                bpy.context.scene.frame_end, bpy.context.scene.render.fps,
                bpy.context.scene.render.fps_base) == saved_scene
        if hasattr(arm_a.animation_data, 'action_blend_type'):
            assert arm_a.animation_data.action_blend_type == 'ADD'
            assert abs(arm_a.animation_data.action_influence - 0.35) < 1e-7
            assert mesh_a.data.shape_keys.animation_data.action_blend_type == 'ADD'
            assert abs(mesh_a.data.shape_keys.animation_data.action_influence - 0.4) < 1e-7
        assert set(bpy.data.actions) == action_ids_before
        assert set(bpy.data.texts) == text_ids_before

        # A second successful import replaces the active actions but keeps the
        # prior actions recoverable, and the other PMX model remains untouched.
        report = motion.import_vmd(bpy.context, root_a, str(motion_path), start_frame=10)
        assert len(report['preserved_actions']) == 2
        assert old_arm_action.use_fake_user and old_key_action.use_fake_user
        assert arm_a.animation_data.action != old_arm_action
        assert mesh_a.data.shape_keys.animation_data.action != old_key_action
        assert arm_a.animation_data.action_blend_type == 'REPLACE'
        assert abs(arm_a.animation_data.action_influence - 1.0) < 1e-7
        assert mesh_a.data.shape_keys.animation_data.action_blend_type == 'REPLACE'
        assert abs(mesh_a.data.shape_keys.animation_data.action_influence - 1.0) < 1e-7
        assert arm_b.animation_data is None and mesh_b.data.shape_keys.animation_data is None
        assert_motion_evaluates(root_a, 10, 0.08, bone_name='renamed_arm')
        preserved_action_names = (old_arm_action.name, old_key_action.name)

        # The model's saved 0.16 scale is applied independently to the same VMD.
        report_b = motion.import_vmd(bpy.context, root_b, str(motion_path), start_frame=5)
        assert report_b['scale'] == 0.16
        assert_motion_evaluates(root_b, 5, 0.16)

        # A late failure after changing the current frame restores the previous
        # frame/subframe evaluation of other animated models as well.
        scene = bpy.context.scene
        scene.frame_set(31, subframe=0.25)
        other_pose = tuple(arm_b.pose.bones['腕'].location)
        other_rotation = tuple(arm_b.pose.bones['腕'].rotation_quaternion)
        other_weight = mesh_b.data.shape_keys.key_blocks['笑い'].value
        try:
            with patch.object(motion, 'write_motion_report', side_effect=RuntimeError('synthetic late report failure')):
                motion.import_vmd(bpy.context, root_a, str(motion_path), start_frame=8)
            raise AssertionError('Injected late failure did not escape')
        except RuntimeError as exc:
            assert 'synthetic late report failure' in str(exc)
        assert (scene.frame_current, scene.frame_subframe) == (31, 0.25)
        assert_vector_close(arm_b.pose.bones['腕'].location, other_pose)
        assert_vector_close(arm_b.pose.bones['腕'].rotation_quaternion, other_rotation)
        assert abs(mesh_b.data.shape_keys.key_blocks['笑い'].value - other_weight) < 1e-6

        # Active drivers on imported channels would take precedence over Actions,
        # so reject those targets while preserving their drivers and Actions.
        shape_key = mesh_b.data.shape_keys.key_blocks['笑い']
        shape_action_before = mesh_b.data.shape_keys.animation_data.action
        shape_driver = shape_key.driver_add('value')
        assert shape_driver.data_path == 'key_blocks["笑い"].value'
        try:
            motion.import_vmd(bpy.context, root_b, str(motion_path))
            raise AssertionError('Expected active Shape Key driver rejection')
        except ValueError as exc:
            assert 'active drivers' in str(exc)
        assert mesh_b.data.shape_keys.animation_data.action == shape_action_before
        assert any(driver.data_path == 'key_blocks["笑い"].value'
                   for driver in mesh_b.data.shape_keys.animation_data.drivers)
        shape_key.driver_remove('value')

        bone = arm_b.pose.bones['腕']
        arm_action_before = arm_b.animation_data.action
        bone_driver = bone.driver_add('location', 0)
        assert bone_driver.data_path == 'pose.bones["腕"].location'
        try:
            motion.import_vmd(bpy.context, root_b, str(motion_path))
            raise AssertionError('Expected active bone driver rejection')
        except ValueError as exc:
            assert 'active drivers' in str(exc)
        assert arm_b.animation_data.action == arm_action_before
        assert any(driver.data_path == 'pose.bones["腕"].location'
                   for driver in arm_b.animation_data.drivers)
        bone.driver_remove('location', 0)

        # A Key datablock shared with an object outside the selected PMX model
        # cannot be animated without also changing that external object.
        external_user = bpy.data.objects.new('outside-key-user', mesh_b.data)
        scene.collection.objects.link(external_user)
        key_action_before_external = mesh_b.data.shape_keys.animation_data.action
        try:
            motion.import_vmd(bpy.context, root_b, str(motion_path))
            raise AssertionError('Expected shared Shape Key rejection')
        except ValueError as exc:
            assert 'outside this PMX model' in str(exc)
        assert mesh_b.data.shape_keys.animation_data.action == key_action_before_external
        bpy.data.objects.remove(external_user, do_unlink=True)

        # Matched channels beyond Blender's frame limit are rejected up front.
        frame_limit = scene.bl_rna.properties['frame_end'].hard_max
        overflow = directory / 'frame-overflow.vmd'
        write_vmd(overflow, bones=[('腕', 5, (0, 0, 0), (0, 0, 0, 1))])
        frame_before = (scene.frame_current, scene.frame_subframe, scene.frame_start,
                        scene.frame_end, scene.render.fps, scene.render.fps_base)
        arm_action_before = arm_b.animation_data.action
        try:
            motion.import_vmd(bpy.context, root_b, str(overflow), start_frame=frame_limit - 4)
            raise AssertionError('Expected matched frame limit rejection')
        except ValueError as exc:
            assert 'scene frame limit' in str(exc)
        assert arm_b.animation_data.action == arm_action_before
        assert (scene.frame_current, scene.frame_subframe, scene.frame_start,
                scene.frame_end, scene.render.fps, scene.render.fps_base) == frame_before

        # An unmatched file reports every missing channel and performs no edits.
        no_match_path = directory / 'no-match.vmd'
        write_vmd(no_match_path,
                  bones=[('missing', 0, (0, 0, 0), (0, 0, 0, 1))],
                  morphs=[('missing-morph', 0, 1.0)])
        active_before = arm_b.animation_data.action
        try:
            motion.import_vmd(bpy.context, root_b, str(no_match_path))
            raise AssertionError('Expected NoMatchingChannels')
        except motion.NoMatchingChannels as exc:
            assert exc.report['unmatched_bones'] == ['missing']
            assert exc.report['unmatched_morphs'][0]['name'] == 'missing-morph'
        assert arm_b.animation_data.action == active_before

        # Both truncated required sections and invalid finite values are rejected
        # before touching the scene or existing animation.
        before_scene = (bpy.context.scene.frame_current, bpy.context.scene.frame_subframe,
                        bpy.context.scene.frame_start,
                        bpy.context.scene.frame_end, bpy.context.scene.render.fps,
                        bpy.context.scene.render.fps_base)
        before_arm_action = arm_b.animation_data.action
        truncated = directory / 'truncated.vmd'
        truncated.write_bytes(b'Vocaloid Motion Data 0002'.ljust(50, b'\x00') + struct.pack('<I', 2))
        invalid = directory / 'invalid.vmd'
        write_vmd(invalid, bones=[('腕', 0, (float('nan'), 0, 0), (0, 0, 0, 1))])
        for path in (truncated, invalid):
            try:
                motion.import_vmd(bpy.context, root_b, str(path))
                raise AssertionError(f'Expected invalid VMD rejection: {path.name}')
            except ValueError:
                pass
            assert arm_b.animation_data.action == before_arm_action
            assert (bpy.context.scene.frame_current, bpy.context.scene.frame_subframe,
                    bpy.context.scene.frame_start,
                    bpy.context.scene.frame_end, bpy.context.scene.render.fps,
                    bpy.context.scene.render.fps_base) == before_scene

        # Save and reload, then evaluate the persisted actions on the real pose
        # and shape-key datablocks, not just the keyframe point arrays.
        root_a_name, root_b_name = root_a.name, root_b.name
        filepath = directory / 'vmd-roundtrip.blend'
        bpy.ops.wm.save_as_mainfile(filepath=str(filepath))
        bpy.ops.wm.open_mainfile(filepath=str(filepath))
        root_a = bpy.data.objects[root_a_name]
        root_b = bpy.data.objects[root_b_name]
        assert_motion_evaluates(root_a, 10, 0.08, bone_name='renamed_arm')
        assert_motion_evaluates(root_b, 5, 0.16)
        for action_name in preserved_action_names:
            preserved_action = bpy.data.actions.get(action_name)
            assert preserved_action is not None and preserved_action.use_fake_user, action_name
        for root in (root_a, root_b):
            report_text = bpy.data.texts[root['violet_vmd_report']]
            assert json.loads(report_text.as_string())['format'] == 'VMD'
        print('VIOLET_VMD_OK: validation, scale, bone/morph evaluation, reports, rollback, repeated import, model isolation, save/load')
        print('VIOLET_VMD_BLENDER_VERSION:', bpy.app.version_string)


if __name__ == '__main__':
    main()
