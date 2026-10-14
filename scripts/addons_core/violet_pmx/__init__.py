# SPDX-FileCopyrightText: 2026 VioletBlender contributors
# SPDX-License-Identifier: GPL-3.0-or-later

bl_info = {
    "name": "Violet PMX, VMD & Materials",
    "author": "VioletBlender contributors",
    "version": (0, 3, 0),
    "blender": (4, 2, 0),
    "location": "File > Import; 3D View > Sidebar > Violet",
    "description": "Import PMX models and VMD motion; organize materials and textures",
    "category": "Import-Export",
}

import addon_utils
import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from . import motion, workflow


class VIOLET_OT_import_pmx(bpy.types.Operator, ImportHelper):
    bl_idname = "violet.import_pmx"
    bl_label = "Import Violet PMX"
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = ".pmx"

    filter_glob: StringProperty(default="*.pmx", options={'HIDDEN'})
    scale: FloatProperty(name="Scale", default=0.08, min=0.00001, soft_max=10.0)
    import_physics: BoolProperty(name="Import Physics Data", default=False,
                                description="Import rigid bodies and joints; simulation is built separately in MMD Tools")
    pack_textures: BoolProperty(name="Pack Textures", default=False,
                               description="Store available textures inside the blend file")

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        try:
            root, report = workflow.import_pmx(context, self.filepath, self.scale,
                                               self.import_physics, self.pack_textures)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, "PMX import failed: " + str(exc))
            return {'CANCELLED'}
        missing = len(report['missing_textures'])
        self.report({'WARNING'} if missing else {'INFO'},
                    f"Imported {root.name}: {report['material_count']} materials, {missing} missing textures")
        return {'FINISHED'}


class VIOLET_OT_import_vmd(bpy.types.Operator, ImportHelper):
    bl_idname = "violet.import_vmd"
    bl_label = "Import Violet VMD Motion"
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = ".vmd"

    filter_glob: StringProperty(default="*.vmd", options={'HIDDEN'})
    start_frame: IntProperty(name="Start Frame", default=1, min=0)
    use_model_scale: BoolProperty(name="Use PMX Import Scale", default=True)
    scale: FloatProperty(name="Scale Override", default=0.08, min=0.00001, soft_max=10.0,
                         precision=4)
    update_timeline: BoolProperty(name="Update Timeline Range", default=True)

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and workflow.model_root(context.object) is not None

    def execute(self, context):
        root = workflow.model_root(context.object)
        try:
            report = motion.import_vmd(
                context, root, self.filepath,
                start_frame=self.start_frame,
                override_scale=not self.use_model_scale,
                scale=self.scale,
                update_timeline=self.update_timeline,
            )
        except motion.NoMatchingChannels as exc:
            motion.write_motion_report(root, exc.report)
            self.report({'ERROR'}, str(exc) + "; see View Motion Report")
            return {'CANCELLED'}
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, "VMD import failed: " + str(exc))
            return {'CANCELLED'}
        unmatched = len(report['unmatched_bones']) + len(report['unmatched_morphs'])
        self.report({'WARNING'} if unmatched else {'INFO'},
                    f"Imported motion to {len(report['imported_targets'])} targets; "
                    f"{unmatched} unmatched channels")
        return {'FINISHED'}


class VIOLET_OT_motion_report(bpy.types.Operator):
    bl_idname = "violet.motion_report"
    bl_label = "View Motion Report"
    bl_description = "Show VMD import details and unmatched channels in a separate Text report"

    @classmethod
    def poll(cls, context):
        root = workflow.model_root(context.object)
        report_name = root.get('violet_vmd_report') if root is not None else None
        return context.area is not None and report_name is not None and report_name in bpy.data.texts

    def execute(self, context):
        root = workflow.model_root(context.object)
        context.area.type = 'TEXT_EDITOR'
        context.area.spaces.active.text = bpy.data.texts[root['violet_vmd_report']]
        return {'FINISHED'}


class VIOLET_OT_organize_materials(bpy.types.Operator):
    bl_idname = "violet.organize_materials"
    bl_label = "Organize Materials"
    bl_description = "Repair texture paths, reuse compatible images and update the material report"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return workflow.model_root(context.object) is not None and context.mode == 'OBJECT'

    def execute(self, context):
        root = workflow.model_root(context.object)
        report = workflow.organize_materials(root, context.scene.violet_texture_directory)
        missing = len(report['missing_textures'])
        self.report({'WARNING'} if missing else {'INFO'},
                    f"Repaired {report['repaired_textures']} textures, reused {report['reused_images']} images; {missing} missing")
        return {'FINISHED'}


class VIOLET_OT_pack_textures(bpy.types.Operator):
    bl_idname = "violet.pack_textures"
    bl_label = "Pack Model Textures"
    bl_description = "Pack only this model's available images for a portable blend file"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return workflow.model_root(context.object) is not None and context.mode == 'OBJECT'

    def execute(self, context):
        packed, failures = workflow.pack_textures(workflow.model_root(context.object))
        self.report({'WARNING'} if failures else {'INFO'},
                    f"Packed {packed} images; {len(failures)} unavailable")
        return {'FINISHED'}


class VIOLET_OT_material_report(bpy.types.Operator):
    bl_idname = "violet.material_report"
    bl_label = "View Material Report"
    bl_description = "Show material slots, texture paths and missing textures in the Text Editor"

    @classmethod
    def poll(cls, context):
        return context.area is not None and workflow.model_root(context.object) is not None

    def execute(self, context):
        root = workflow.model_root(context.object)
        workflow.write_report(root, workflow.audit_materials(root))
        context.area.type = 'TEXT_EDITOR'
        context.area.spaces.active.text = bpy.data.texts[root['violet_material_report']]
        return {'FINISHED'}


class VIOLET_PT_pmx(bpy.types.Panel):
    bl_label = "PMX & Materials"
    bl_idname = "VIOLET_PT_pmx"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Violet"

    def draw(self, context):
        layout = self.layout
        layout.operator("violet.import_pmx", text="Import PMX", icon='IMPORT')
        root = workflow.model_root(context.object)
        if root is None:
            layout.label(text="Select an imported model")
            return
        layout.label(text=root.mmd_root.name or root.name, icon='OUTLINER_OB_ARMATURE')
        layout.separator()
        layout.label(text="Motion")
        layout.prop(context.scene, "violet_vmd_start_frame", text="Start Frame")
        layout.prop(context.scene, "violet_vmd_use_model_scale", text="Use PMX Scale")
        if not context.scene.violet_vmd_use_model_scale:
            layout.prop(context.scene, "violet_vmd_scale", text="Scale")
        layout.prop(context.scene, "violet_vmd_update_timeline", text="Update Timeline")
        op = layout.operator("violet.import_vmd", text="Import VMD", icon='ACTION')
        op.start_frame = context.scene.violet_vmd_start_frame
        op.use_model_scale = context.scene.violet_vmd_use_model_scale
        op.scale = context.scene.violet_vmd_scale
        op.update_timeline = context.scene.violet_vmd_update_timeline
        report_name = root.get('violet_vmd_report')
        if report_name is not None and report_name in bpy.data.texts:
            layout.operator("violet.motion_report", icon='TEXT')
        layout.separator()
        layout.label(text="Materials")
        layout.prop(context.scene, "violet_texture_directory", text="Texture Folder")
        layout.operator("violet.organize_materials", icon='MATERIAL')
        layout.operator("violet.pack_textures", icon='PACKAGE')
        layout.label(text=f"Missing textures: {root.get('violet_missing_textures', 0)}",
                     icon='ERROR' if root.get('violet_missing_textures', 0) else 'CHECKMARK')
        layout.operator("violet.material_report", icon='TEXT')
        obj = context.object
        if obj.type == 'MESH':
            layout.template_list("MATERIAL_UL_matslots", "violet", obj, "material_slots",
                                 obj, "active_material_index", rows=4)
            if obj.active_material:
                layout.prop(obj.active_material, "name", text="Material")
                layout.label(text="PMX: " + obj.active_material.get(
                    "violet_pmx_name_j", obj.active_material.mmd_material.name_j))


def menu_import(self, context):
    self.layout.operator(VIOLET_OT_import_pmx.bl_idname, text="Violet PMX (.pmx)")


CLASSES = (VIOLET_OT_import_pmx, VIOLET_OT_import_vmd, VIOLET_OT_motion_report,
           VIOLET_OT_organize_materials, VIOLET_OT_pack_textures,
           VIOLET_OT_material_report, VIOLET_PT_pmx)


def register():
    # One switch for the Violet UI and its bundled, offline PMX dependency.
    if not addon_utils.check("mmd_tools")[1]:
        if addon_utils.enable("mmd_tools", default_set=True, persistent=True) is None:
            raise RuntimeError("Enable the bundled MMD Tools before Violet PMX")
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.violet_texture_directory = StringProperty(
        name="Texture Folder", subtype='DIR_PATH',
        description="Optional folder to search recursively for missing textures; ambiguous names are left unresolved")
    bpy.types.Scene.violet_vmd_start_frame = IntProperty(
        name="VMD Start Frame", default=1, min=0,
        description="Place VMD frame 0 at this Blender frame")
    bpy.types.Scene.violet_vmd_use_model_scale = BoolProperty(
        name="Use PMX Import Scale", default=True,
        description="Read the scale saved when the selected PMX model was imported")
    bpy.types.Scene.violet_vmd_scale = FloatProperty(
        name="VMD Scale", default=0.08, min=0.00001, soft_max=10.0, precision=4,
        description="Scale factor used when the PMX import scale is not available or is overridden")
    bpy.types.Scene.violet_vmd_update_timeline = BoolProperty(
        name="Update Timeline Range", default=True,
        description="Set the scene range to the imported bone and vertex morph keys")
    bpy.types.TOPBAR_MT_file_import.append(menu_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    del bpy.types.Scene.violet_vmd_update_timeline
    del bpy.types.Scene.violet_vmd_scale
    del bpy.types.Scene.violet_vmd_use_model_scale
    del bpy.types.Scene.violet_vmd_start_frame
    del bpy.types.Scene.violet_texture_directory
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
