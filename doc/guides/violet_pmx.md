# VioletBlender：PMX 导入与材质整理

首版提供 PMX 2.0 导入、模型独立集合、骨骼和权重、顶点及材质等 Morph、
UV 和自定义法线，以及模型范围内的贴图整理。底层固定使用 MMD Tools
v4.5.14，Violet 的入口和整理逻辑在 `violet_pmx` 中。

## 安装和使用

Windows 的 **PMX import and materials on Windows** 工作流提供两种产物：

- `VioletBlender-windows-PMX-*`：包含已编译的 Blender 5.2 和 PMX 插件。
  解压后运行 `blender.exe`。
- `VioletBlender-PMX-addon-*`：内部的 `VioletBlender-pmx-addon.zip` 是离线插件包，
  可安装到之前的 VioletBlender 或 Blender 4.2+。
  在 **Edit → Preferences → Add-ons → 菜单 → Install from Disk** 选择该 ZIP。

在 Add-ons 搜索并启用 **Violet PMX Import & Materials**；它会自动启用随包提供的
MMD Tools。插件已包含依赖，无需 pip 或联网。使用自定义 PMX 包时请使用随包的
MMD Tools，避免同时启用另一个来源的 MMD Tools 扩展。

1. 使用 **File → Import → Violet PMX (.pmx)**。默认缩放为 `0.08`；
   保留骨骼命名和顶点，不自动合并顶点。
2. 在视图中选中模型、骨架或模型根对象，按 **N → Violet**。
3. 点击 **Organize Materials** 更新贴图和材质报告。缺失贴图时，可先指定
   **Texture Folder**，再执行整理。先按 PMX 相对路径寻找，随后递归搜索文件名；
   多个同名文件不会自动替换。
4. 选中网格可以查看、选择和重命名材质槽。相同名字的不同材质保留各自槽位，
   面的材质索引及 Morph 引用不会被合并或排序。原始 PMX 中英文名另存于材质
   自定义属性 `violet_pmx_name_j` / `violet_pmx_name_e`。
5. 点击 **View Material Report** 查看每个材质的槽位、面数、透明度、单双面、
   贴图用途、路径及缺失状态。报告保存在 `.blend` 的 Text 数据中。
6. 点击 **Pack Model Textures** 后保存 `.blend`，可携带已找到的模型贴图。
   缺失贴图会保留在报告中，需修复后重新打包。

整理只处理所选 MMD 模型使用的材质；保留现有节点连接、MMD 属性和材质 Morph。
贴图按实际文件路径及色彩空间、Alpha 设置复用，不删除未使用的全局数据块。
贴图透明通道及 PMX 材质 Alpha 接入 MMD 材质节点，保留原有单双面设置。

未设置外部共享 Toon 文件夹时，使用自行生成的中性双色阶预览贴图，保留 PMX 的
共享 Toon 编号。需要原始颜色时，可在 MMD Tools 首选项配置自己的共享 Toon
目录。首版尚未制作 Violet 的专用 Toon 渲染预设。

## 范围和验证

当前入口支持 **PMX 2.0**；PMX 2.1 会明确报错。物理数据可选择导入，
物理模拟的构建和调校仍使用 MMD Tools；本阶段验收聚焦网格、骨骼、Morph 和材质。
此入口不导入 PMD/VMD，随包 MMD Tools 的高级操作仍然保留。

测试使用从零生成的模型，无第三方角色资源。覆盖材质重名、重叠面透明、中文路径、
Windows 路径分隔符、缺失及歧义贴图、不同色彩空间、重复导入、失败回滚、
贴图打包、保存/重载和 Cycles CPU 渲染。用户实际模型与交互视窗仍需后续验收。

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
