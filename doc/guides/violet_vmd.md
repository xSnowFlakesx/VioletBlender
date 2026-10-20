# VioletBlender：VMD 动作导入

0.4.0 可将 VMD 的骨骼动作及与现有 Shape Key 精确同名的顶点表情导入选中的
PMX 模型。插件包和 MMD Tools 依赖见[PMX 指南](violet_pmx.md)。

## 使用

1. 先在视图中选中 PMX 模型根对象、骨架或网格，然后使用 **File → Import →
   Violet VMD Motion (.vmd)**。未选中模型时菜单项会禁用，并显示“Select an imported PMX model”提示。
2. 在文件选择器的导入选项中设置 **Start Frame**。VMD 第 0 帧默认对应 Blender 第 1 帧。
3. 默认使用 PMX 导入时保存在模型根对象上的缩放值；旧模型没有该值时会按
   `root.empty_display_size × 0.2` 推断，并在动作报告中标明。关闭 **Use PMX Import Scale**
   可填写 **Scale Override**。
4. 选择 `.vmd` 并点击 **Import VMD**。动作源帧率按 30 fps 解释，导入后场景设为
   30 fps。默认根据实际导入的骨骼和表情曲线调整时间范围。
5. 可在 **N → Violet → View Motion Report** 中查看 JSON 报告。报告保存在 blend 的
   独立 Text 数据中，列出匹配与未匹配通道、需要先组装的 PMX Morph、使用的缩放值和新建 Action。

也可以在 **N → Violet** 面板中设置相同选项并点击 **Import VMD**。

VMD 骨骼按 MMD 日文骨骼名映射，即使 Blender 中的骨骼已重命名也会按 PMX 名称
查找；表情只按已有顶点 Shape Key 名精确匹配。UV、骨骼、材质及群组 Morph 不会由
本首版转换成顶点 Shape Key，报告会将这些未匹配项列为需要其他 MMD Tools 流程处理。
没有匹配通道时，动作导入会取消并报告结果。

导入为每个目标新建活动 Action，旧 Action 会保留并标记为 Fake User，在报告中记录。
含有 NLA strip 的目标会在修改场景前明确拒绝导入，防止动作与现有 NLA 混合。
有活动驱动控制目标骨骼变换、IK 开关或表情值时会在修改场景前拒绝导入。失败时会
还原活动 Action/slot、Fake User、姿态、Shape Key 值和滑块、IK 与约束状态、场景帧率、
当前帧（含子帧）及时间范围，并删除本次创建的数据。其他模型的动作数据不会修改；
当前帧、帧率和播放范围属于场景全局设置，成功导入会更新这些设置。

本功能只导入骨骼动作和已存在的顶点 Shape Key 表情，不导入相机、灯光、物理或 Toon
动画。VMD 必需的骨骼和 Morph 段会在场景修改前检查截断、计数、有限数值和文件头；
不支持的内容和未匹配通道会写入报告。
