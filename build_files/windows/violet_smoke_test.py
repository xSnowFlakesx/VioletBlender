# SPDX-License-Identifier: GPL-2.0-or-later

"""Check that an installed Blender loads Python, saves files, and renders with Cycles CPU."""

import tempfile
from pathlib import Path

import bpy
import numpy as np


def main():
    assert np.array([1, 2, 3]).sum() == 6
    scene = bpy.context.scene
    assert scene.camera is not None, "Factory startup must include a camera"
    assert bpy.data.objects.get("Cube") is not None, "Factory startup must include a cube"

    with tempfile.TemporaryDirectory(prefix="violet-smoke-") as directory:
        blend_file = str(Path(directory) / "smoke.blend")
        render_file = Path(directory) / "smoke.png"
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = 1
        scene.cycles.use_denoising = False
        scene.render.resolution_x = 32
        scene.render.resolution_y = 32
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = str(render_file)
        bpy.data.objects["Cube"]["violet_smoke_test"] = True

        bpy.ops.wm.save_as_mainfile(filepath=blend_file)
        bpy.ops.wm.open_mainfile(filepath=blend_file)
        assert bpy.data.objects["Cube"]["violet_smoke_test"], "Saved data did not survive reload"
        bpy.ops.render.render(write_still=True)
        assert render_file.is_file() and render_file.stat().st_size > 0, "Render output is missing"

    print(f"VIOLET_SMOKE_OK: Blender {bpy.app.version_string}; Python, NumPy, save/load, Cycles CPU")


if __name__ == "__main__":
    main()
