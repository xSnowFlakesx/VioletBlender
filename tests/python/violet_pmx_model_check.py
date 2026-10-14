# SPDX-FileCopyrightText: 2026 VioletBlender contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Import, audit, pack, and save one PMX model for offline review.

Run with Blender's background Python and arguments after ``--``. This tool
never downloads models or adds third-party character assets.
"""

import argparse
import json
import os
from pathlib import Path
import sys

import addon_utils
import bpy


if not os.environ.get("VIOLET_PMX_INSTALLED"):
    script_path = Path(__file__).resolve()
    parents = script_path.parents
    if (script_path.parent.name == "python" and len(parents) > 2
            and parents[1].name == "tests"):
        addon_source = parents[2] / "scripts/addons_core"
        if addon_source.is_dir():
            sys.path.insert(0, str(addon_source))


def _arguments(argv=None):
    if argv is None:
        argv = sys.argv
        argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Path to a PMX 2.0 file")
    parser.add_argument("--output", required=True, help="Directory for report.json and model.blend")
    parser.add_argument("--texture-dir", default="", help="Optional recursive texture search directory")
    return parser.parse_args(argv)


def _make_model_scene():
    """Use an empty active scene while preserving the startup/user scene."""
    if bpy.context.window is None:
        raise RuntimeError("The PMX model check needs a Blender window context to select its output scene")
    scene = bpy.data.scenes.new("Violet PMX Model Check")
    bpy.context.window.scene = scene
    return scene


def main(argv=None):
    args = _arguments(argv)
    model_path = Path(bpy.path.abspath(args.model)).expanduser().resolve()
    output_dir = Path(bpy.path.abspath(args.output)).expanduser().resolve()
    texture_dir = Path(bpy.path.abspath(args.texture_dir)).expanduser().resolve() if args.texture_dir else ""
    if not model_path.is_file():
        raise FileNotFoundError(f"PMX model does not exist: {model_path}")
    output_dir.mkdir(parents=True, exist_ok=True)

    if addon_utils.enable("violet_pmx", default_set=True, persistent=True) is None:
        raise RuntimeError("Could not enable the bundled Violet PMX add-on")
    from violet_pmx import workflow

    _make_model_scene()
    root, _ = workflow.import_pmx(bpy.context, str(model_path))
    report = workflow.organize_materials(root, str(texture_dir) if texture_dir else "")
    packed, failures = workflow.pack_textures(root)
    report = workflow.audit_materials(root, str(texture_dir) if texture_dir else "")
    report["model_check"] = {"packed_textures": packed, "pack_failures": failures}
    workflow.write_report(root, report)

    report_path = output_dir / "report.json"
    blend_path = output_dir / "model.blend"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    print("VIOLET_PMX_MODEL_CHECK:", json.dumps({
        "report": str(report_path), "blend": str(blend_path),
        "materials": report["material_count"],
        "missing_textures": len(report["missing_textures"]),
        "ambiguous_textures": len(report.get("ambiguous_textures", [])),
        "pack_failures": len(failures),
    }, ensure_ascii=False))
    return report


if __name__ == "__main__":
    main()
