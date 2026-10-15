# SPDX-FileCopyrightText: 2026 VioletBlender contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Verify native PMX/VMD startup, menus, operators, and script reloads."""

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

# This is the startup assertion: it must run before importing fixture scripts,
# which intentionally enable Violet themselves for standalone test use.
violet_default, violet_loaded = addon_utils.check('violet_pmx')
mmd_default, mmd_loaded = addon_utils.check('mmd_tools')
assert violet_default and violet_loaded, (violet_default, violet_loaded)
assert mmd_default and mmd_loaded, (mmd_default, mmd_loaded)
assert 'violet_pmx' not in bpy.context.preferences.addons
assert 'mmd_tools' in bpy.context.preferences.addons


class MenuCollector:
    def __init__(self):
        self.items = []
        self.layout = self

    def operator(self, identifier, *, text, **kwargs):
        self.items.append((identifier, text, kwargs))
        return object()


def assert_import_menu():
    import violet_pmx

    draw_funcs = bpy.types.TOPBAR_MT_file_import._dyn_ui_initialize()
    violet_callbacks = [func for func in draw_funcs
                        if getattr(func, '__module__', '') == 'violet_pmx'
                        and getattr(func, '__name__', '') == 'menu_import']
    assert violet_callbacks == [violet_pmx.menu_import], violet_callbacks

    collector = MenuCollector()
    violet_callbacks[0](collector, bpy.context)
    assert collector.items == [
        ('violet.import_pmx', 'Violet PMX (.pmx)', {}),
        ('violet.import_vmd', 'Violet VMD Motion (.vmd)', {}),
    ], collector.items


assert_import_menu()

# Exercise Blender's actual preference and script reset path before generating
# fixtures. Hidden Violet should return, then restore its visible MMD dependency.
assert bpy.ops.wm.read_factory_settings(use_empty=True) == {'FINISHED'}
violet_default, violet_loaded = addon_utils.check('violet_pmx')
mmd_default, mmd_loaded = addon_utils.check('mmd_tools')
assert violet_default and violet_loaded, (violet_default, violet_loaded)
assert mmd_default and mmd_loaded, (mmd_default, mmd_loaded)
assert 'violet_pmx' not in bpy.context.preferences.addons
assert 'mmd_tools' in bpy.context.preferences.addons
assert_import_menu()

violet_module = sys.modules['violet_pmx']
poll_messages = []
with patch.object(violet_module.VIOLET_OT_import_vmd, 'poll_message_set',
                  classmethod(lambda cls, message: poll_messages.append(message))):
    assert not violet_module.VIOLET_OT_import_vmd.poll(bpy.context)
assert poll_messages == ['Select an imported PMX model'], poll_messages

# The regular fixture scripts enable Violet themselves. The startup checks above
# already established that native initialization worked before these imports.
pmx_fixture = runpy.run_path(str(REPO / 'tests/python/violet_pmx_test.py'),
                             run_name='violet_native_pmx_fixture')
vmd_helpers = runpy.run_path(str(REPO / 'tests/python/violet_vmd_test.py'),
                             run_name='violet_native_vmd_helpers')
from violet_pmx import workflow


def select_object(obj):
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


with tempfile.TemporaryDirectory(prefix='violet-native-import-') as temp:
    directory = Path(temp)
    pmx_path = pmx_fixture['make_fixture'](directory)
    assert bpy.ops.violet.import_pmx(filepath=str(pmx_path), scale=0.08) == {'FINISHED'}
    root = workflow.model_root(bpy.context.object)
    assert root is not None and root.get('violet_pmx_scale') == 0.08

    vmd_path = vmd_helpers['make_motion'](directory)
    assert bpy.ops.violet.import_vmd(filepath=str(vmd_path), start_frame=10) == {'FINISHED'}
    vmd_helpers['assert_motion_evaluates'](root, 10, 0.08)

    bpy.utils.load_scripts(reload_scripts=True)
    assert addon_utils.check('violet_pmx') == (True, True)
    assert addon_utils.check('mmd_tools') == (True, True)
    assert 'violet_pmx' not in bpy.context.preferences.addons
    assert 'mmd_tools' in bpy.context.preferences.addons
    assert_import_menu()

    assert bpy.ops.violet.import_pmx(filepath=str(pmx_path), scale=0.08) == {'FINISHED'}
    reloaded_root = workflow.model_root(bpy.context.object)
    assert reloaded_root is not None and reloaded_root != root
    select_object(reloaded_root)
    assert bpy.ops.violet.import_vmd(filepath=str(vmd_path), start_frame=7) == {'FINISHED'}
    vmd_helpers['assert_motion_evaluates'](reloaded_root, 7, 0.08)

print('VIOLET_NATIVE_IMPORT_OK: factory startup, factory reset, File > Import, PMX/VMD operators, reload')
print('VIOLET_NATIVE_IMPORT_BLENDER_VERSION:', bpy.app.version_string)
