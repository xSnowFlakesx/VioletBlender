# VioletBlender：Eevee Toon 材质预设

Violet PMX 0.4.0 为每个 PMX 模型提供二段和三段的 Eevee Toon 预设。选择模型所属的
网格对象，在 **Material Properties → Violet Toon 0.4** 面板中配置；面板操作作用于
整个模型。插件不会替用户切换场景引擎。

## 使用

1. 在 **Material Properties → Violet Toon 0.4** 选择 **Two Bands** 或
   **Three Bands**。
2. 调整 **Highlight Threshold**。二段模式在此亮度处从阴影切换到高光；三段模式
   在阈值的一半处切换到中间色，再在阈值处切换到高光。
3. 调整 **Shadow Brightness**，控制灰度阴影亮度。三段模式的中间亮度是阴影与白色
   的平均值。
4. 点击 **Apply to Model** 添加 Toon 输出。修改参数后点击 **Update Model**。
   **Restore Original** 移除 Violet 新增的节点，保留原有材质图。

预设使用白色漫反射光照、`Shader to RGB`、灰度转换和常量色带。材质颜色来自现有
`mmd_shader.Color`，并与 Toon 色带相乘；Alpha 来自现有 `mmd_shader.Alpha`，用于
混合透明和发光输出。现有基础、Toon、Sphere 贴图和 Morph 输入连接保持原样。发光
输出不包含原 MMD 高光响应。

Toon 节点接入独立的 `EEVEE` 材质输出，原有 `ALL` / `CYCLES` 输出及其连接和活动
状态继续保留。Eevee 场景渲染使用 Toon 分支，Cycles 场景渲染使用原分支。Material
Preview 可以独立使用 Eevee；要让最终渲染使用 Toon 分支，请将场景渲染引擎设为 Eevee。

## 范围和恢复

Apply、Update 和 Restore 会在修改前检查整个模型的材质。模型根对象和材质必须是本地
可编辑数据，模型材质不能被其他场景对象共享；出现共享、已有 Eevee 输出、外来 Toon
节点或不兼容 MMD shader 时，操作会报告原因并保持模型不变。材质被重命名、保存并
重新打开后，管理记录仍通过材质数据块引用保持关联。

Update 和 Restore 会检查 Violet 自己拥有的节点及色带。如果这些节点被手动修改，
操作会拒绝继续，避免覆盖编辑内容。成功 Restore 只删除 Violet 拥有的节点和不再使用
的色带组；原节点、贴图、Morph、驱动器以及输出选择保持原样。操作中途失败时会回滚
已完成的 Toon 变更。

## 验证

生成合成 PMX fixture 并测试 Toon 操作器、Apply/Update/Restore 回滚、Eevee 与 Cycles
输出选择、原始节点/连接/输出活动状态、模型隔离、材质重命名后的保存重载、共享材质
拒绝，以及 Morph 和驱动器保留：

```sh
blender --background --factory-startup --python-exit-code 1 --python tests/python/violet_toon_test.py
```

Linux 环境可额外启用实际像素测试。测试会在临时目录生成预览图和指标；设置
`VIOLET_TOON_PREVIEW_DIR` 可将它们保存到指定目录。没有可用 GPU 的 Windows CI 默认
跳过像素测试，只运行数据验证。像素验证使用独立脚本：

```sh
VIOLET_TOON_PREVIEW_DIR="$PWD/scratch/violet-toon-preview" \
  LIBGL_ALWAYS_SOFTWARE=1 EGL_PLATFORM=surfaceless \
  blender --background --factory-startup --python-exit-code 1 \
  --python tests/python/violet_toon_render_test.py
```
