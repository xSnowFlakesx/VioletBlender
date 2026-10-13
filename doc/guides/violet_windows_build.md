# VioletBlender Windows 编译与运行

当前源码以 Blender **5.2 Alpha** 为基础。请使用包含完整源码的 `mmd-main`
分支；仓库的 `main` 分支目前只有初始化文件。

## 准备环境

- Windows 10/11 x64。
- Git for Windows，包含 Git LFS，`git lfs version` 能正常运行。
- CMake 3.30 或更新版本，安装时加入 PATH。
- Visual Studio 2022 **17.14.14 或更新的 17.x 版本**，或对应的 Build Tools。
  安装“使用 C++ 的桌面开发”工作负载，并包含 MSVC x64/x86 编译工具和 Windows SDK。
- 为源码、预编译依赖和构建文件留出数十 GB 空间。首次下载及编译可能较久。

## 编译

在 PowerShell 中运行：

```powershell
$env:GIT_LFS_SKIP_SMUDGE = '1'
git clone --branch mmd-main --single-branch https://github.com/xSnowFlakesx/VioletBlender.git
Remove-Item Env:GIT_LFS_SKIP_SMUDGE
cd VioletBlender
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_files\windows\build_violet.ps1
```

`ExecutionPolicy Bypass` 仅用于当前 PowerShell 进程。该脚本自动选择 VS 2022 IDE
或 Build Tools，无需先打开 Developer Command Prompt。默认使用两个并行构建任务；
有足够内存时可用 `-Jobs 4`。构建路径可以包含空格。

脚本从 Blender 官方 LFS 服务取得源码资源，并下载当前提交固定的
`lib/windows_x64` 依赖，不会把源码或依赖切换到最新分支。默认跳过上游测试数据。
如果以后新增了自定义 LFS 资源，可通过 `-SourceLfsUrl` 指定承载全部所需资源的服务。

默认产物在源码目录旁的 `build_violet_windows_Release\install\blender.exe`。
该目录包含 Python、依赖 DLL 和 C 运行库；复制或分发时应保留整个 `install` 目录。
默认不编译 CUDA/HIP/oneAPI 离线内核，先验证桌面程序与 Cycles CPU 的基础运行。

每次构建完成后，脚本会启动**刚编译并安装的程序**，检查版本、Python、NumPy、
`.blend` 保存/重新加载，以及 32×32 的 Cycles CPU 渲染。任何阶段失败都会停止。

也可以分别运行 `-Phase Prepare`、`-Phase Build`、`-Phase Test`，定位问题或只重跑
启动测试。三个阶段应使用相同的 `-BuildDirectory` 和 `-InstallDirectory`；默认
`-Phase All` 仍按顺序完成整个流程。单独运行 `Test` 不需要编译工具。

## 打开界面

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_files\windows\build_violet.ps1 -Launch
```

也可以直接双击产物目录中的 `blender.exe`。检查默认场景是否显示、视口能否旋转、
保存与打开文件是否正常。图形界面需要符合 Blender 要求的显卡及驱动；后台 CPU
测试通过不能代替本机的视口和 GPU 渲染验证。

## CI 与排错

GitHub Actions 的 **Windows build and startup** 在 `mmd-main` 和当前开发分支推送时
运行相同脚本。成功后可下载完整 Windows 构建目录；编译日志也会作为 artifact 保留
7 天。手动触发需要先将 workflow 合入仓库默认分支。

CI 将依赖下载、编译安装、后台测试列为独立步骤，可以直接看到当前进行到哪一步。
对应日志为 `windows-prepare.log`、`windows-build.log` 和 `windows-test.log`。

- 本机日志：`build_violet_windows_Release\windows-build.log`。
- 提示 MSVC 版本不支持：更新 VS 2022，不能只安装旧版 C++ 工作负载。
- 提示缺少 `startup.blend`：检查网络能否访问 `projects.blender.org`；不能使用 LFS
  指针替代真实资源。
- 依赖下载失败：修复网络后重跑同一命令，会继续使用固定版本的依赖。
- 更换编译器、配置或安装路径时，请指定新的 `-BuildDirectory`，避免混用 CMake 缓存。
