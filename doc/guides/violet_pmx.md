# VioletBlender：PMX 导入与材质整理

0.3.1 提供 PMX 2.0 导入、模型独立集合、骨骼和权重、顶点及材质等 Morph、
UV 和自定义法线，以及模型范围内的贴图整理。底层固定使用 MMD Tools
v4.5.14，Violet 的入口和整理逻辑在 `violet_pmx` 中。VMD 骨骼动画和已组装的
顶点表情导入见[动作指南](violet_vmd.md)。

## 安装和使用

从 VioletBlender 源码构建的 Blender 会在启动时自动启用 Violet PMX。包括 Windows
便携版在内，打开 **File → Import** 即可使用，不必搜索或手动启用插件。随包的
MMD Tools 仍显示在插件首选项中，以便配置它自己的选项。

Windows 的 **PMX, VMD and materials on Windows** 工作流提供两种产物：

- `VioletBlender-windows-PMX-*`：包含已编译的 Blender 5.2 和 PMX 插件。
  解压后运行 `blender.exe`。
- `VioletBlender-PMX-addon-*`：内部的 `VioletBlender-pmx-addon.zip` 是离线插件包，
  可安装到之前的 VioletBlender 或 Blender 4.2+。通过 **Edit → Preferences →
  Add-ons → 菜单 → Install from Disk** 安装 ZIP，然后启用 **Violet PMX, VMD & Materials**。

离线插件 ZIP 仅用于手动安装，不包含 Blender 运行时文件。插件已包含 MMD Tools
依赖，无需 pip 或联网。使用自定义 PMX 包时请使用随包的 MMD Tools，避免同时启用
另一个来源的 MMD Tools 扩展。

1. 使用 **File → Import → Violet PMX (.pmx)**。默认缩放为 `0.08`；
   保留骨骼命名和顶点，不自动合并顶点。
2. 在视图中选中模型、骨架或模型根对象，按 **N → Violet**。
3. 点击 **Organize Materials** 更新贴图和材质报告。缺失贴图时，可先指定
   **Texture Folder**，再执行整理。先检查当前文件和 PMX 相对路径；随后递归搜索
   文件名，只有唯一候选才自动替换。搜索根目录本身也计入候选；重名时保留缺失
   状态，并在报告的 `ambiguous_textures` 中列出候选路径。
4. 选中网格可以查看、选择和重命名材质槽。相同名字的不同材质保留各自槽位，
   面的材质索引及 Morph 引用不会被合并或排序。原始 PMX 中英文名另存于材质
   自定义属性 `violet_pmx_name_j` / `violet_pmx_name_e`。
5. 点击 **View Material Report** 查看每个材质的槽位、面数、PMX 透明度、单双面、
   材质实际渲染方法、`mmd_shader` 的 `Alpha` / `Base Alpha` 默认值和连接状态，
   以及贴图用途、路径、色彩空间、Alpha 模式和缺失状态。报告保存在 `.blend` 的
   Text 数据中。
6. 点击 **Pack Model Textures** 后保存 `.blend`，可携带已找到的模型贴图。
   缺失贴图会保留在报告中，需修复后重新打包。

整理只处理所选 MMD 模型使用的材质；保留现有节点连接、MMD 属性和材质 Morph。
贴图按实际文件路径及色彩空间、Alpha 设置复用，不删除未使用的全局数据块。
贴图透明通道及 PMX 材质 Alpha 接入 MMD 材质节点，保留原有单双面设置。MMD Tools
为缺失文件创建的空白占位图，其自动 `NONE` Alpha 模式会在文件恢复时还原为图像
自身的 Alpha 模式；已载入图像的 Alpha 设置继续保留。

未设置外部共享 Toon 文件夹时，使用自行生成的中性双色阶预览贴图，保留 PMX 的
共享 Toon 编号。需要原始颜色时，可在 MMD Tools 首选项配置自己的共享 Toon
目录。首版尚未制作 Violet 的专用 Toon 渲染预设。

## 范围和验证

当前入口支持 **PMX 2.0**；PMX 2.1 会明确报错。物理数据可选择导入，
物理模拟的构建和调校仍使用 MMD Tools；本阶段验收聚焦网格、骨骼、Morph 和材质。
此入口不导入 PMD；VMD 动作请见[动作指南](violet_vmd.md)。随包 MMD Tools 的高级
操作仍然保留。

测试使用从零生成的模型，无第三方角色资源。覆盖材质重名、透明材质与贴图 Alpha、
中文路径、Windows 路径分隔符、缺失及歧义贴图、不同色彩空间、重复导入、失败回滚、
贴图打包、保存/重载和孤立三角面的 Cycles CPU Alpha 渲染。

可用独立命令检查用户提供的 PMX 2.0 文件。`--output` 指定一个输出目录，命令会在
其中写入 `report.json` 和打包贴图后的 `model.blend`；缺失或重名贴图会在报告中标出，
不阻止产物生成。blend 的活动场景只含待检查模型；创建该场景不会删除原场景内容。
该命令不会下载模型或附带第三方角色资源。自动测试只使用合成模型，
不能据此声称某个真实角色资产已完成验收。

```sh
blender --background --factory-startup --python-exit-code 1 \
  --python tests/python/violet_pmx_model_check.py -- \
  --model /path/to/model.pmx --output /path/to/check-output \
  --texture-dir /path/to/textures
```

Windows 便携版发布包根目录也提供 `violet_pmx_model_check.py`，可将上例中的
`blender` / `tests/python/violet_pmx_model_check.py` 替换为 `blender.exe` /
`violet_pmx_model_check.py`。

```sh
blender --background --factory-startup --python-exit-code 1 --python tests/python/violet_pmx_test.py
python build_files/utils/package_violet_pmx.py --output /path/to/output
```

快速 Windows 验证复用 **Windows build and startup** 工作流最近成功且未过期的
Blender 5.2 编译产物，安装当前插件后测试并重新打包。找不到基础产物时，需先运行
Windows 编译工作流。`violet-pmx-build.json` 分别记录可执行文件和插件的源代码提交，
不把插件更新误记为重新编译 C++。

上游来源、许可证及本地修改见
[`VIOLET_VENDOR.md`](../../scripts/addons_core/mmd_tools/VIOLET_VENDOR.md)。
