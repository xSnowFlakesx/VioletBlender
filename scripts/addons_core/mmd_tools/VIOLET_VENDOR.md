# Bundled MMD Tools

Source: <https://github.com/MMD-Blender/blender_mmd_tools>

Pinned release: **v4.5.14**, commit `f1d8a98db5e185cfa73c9b8a8a67fa42d9eb4b14`.
The upstream GPL-3.0-or-later license is included in `LICENSE`.

VioletBlender changes:

- Add legacy `bl_info` so the package works under `scripts/addons_core`.
- Extract the upstream OpenCC 0.1.7 wheel into `_vendor/opencc`, preserve its
  Apache-2.0 license and notice, import it relatively, and exclude `_vendor`
  from Blender class discovery. No pip installation or network access is required.
  Text line endings are normalized to LF; Python/document trailing whitespace is removed.
  Original wheel SHA-256:
  `41b3b92943c7bed291f448e9c7fad4b577c8c2eae30fcfe5a74edf8818493aa6`.
- Exclude the original MikuMikuDance toon bitmaps, sample models, wheels and
  type stubs. Generate an independent neutral two-level ramp when no user
  shared-toon folder is configured. Original shared toon IDs remain stored;
  the generated ramp is a preview fallback rather than a reproduction of
  the original ten toon textures.
- Use `surface_render_method` for overlapping-face transparency on Blender
  4.2+; retain the older API fallback.
- Mark missing-image placeholders so Violet can reload textures restored at
  their original path instead of reusing a cached blank image.

The separate `violet_pmx` add-on owns the Violet workflow. Keep upstream fixes
small and document changes here when upgrading the pinned release.
