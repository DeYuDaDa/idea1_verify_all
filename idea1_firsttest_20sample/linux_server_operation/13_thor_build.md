# 第 13 步：准备固定版本 CloudRendering build

**当前服务器已完成本步骤：** `20261018T052641Z` 导入日志确认 SHA-256 为 `1fd5f998644a6dd522a4cf6604c05360a75a5c27f450a7486c20e52dc2b67bb9`，构建包已校验并安装；随后第 03 步真实试启动成功。当前直接转到 [六组试生成](08_after_smoke.md)，不重复导入或下载。以下命令保留供新服务器使用。

第 12 步已确认容器可以枚举 NVIDIA Vulkan。此前 smoke 在下载 797 MiB build 时只收到约 13 MiB。本步把下载/校验/缓存与 Unity smoke 分开：脚本不启动 Unity。

当前服务器直连速度约 20 KiB/s，若一直保持该速度，完整包需要十多个小时。建议优先使用下方的浏览器下载并上传方案。也可以先尝试一次有 5 分钟 ZIP 下载上限的服务器准备命令，再单独启动 smoke：

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample && bash linux_server_operation/13_prepare_thor_build.sh
```

本步骤固定 AI2-THOR `5.0.0` 的 CloudRendering commit `f0825767cd50d69f666c7f282e54abfe58f1e917`，官方 ZIP 大小为 `835983275` 字节。下载目录固定在外部 `DATA_ROOT/thor_build_downloads/`，`.part` 跨重跑保留并用 HTTP Range 续传；单次 ZIP 传输最多 300 秒，低于 5 KiB/s 持续 30 秒会停止，方便及时反馈。sidecar 是小文件，单独最多 30 秒。若服务器网络慢或 Range 不受支持，脚本保留 `.part` 并退出；不要等它无限重试。

可改用浏览器从官方 HTTPS 地址下载 ZIP 与 SHA-256 sidecar，然后一并上传到服务器。sidecar URL 把 `.zip` 替换为 `.sha256`（不是 `.zip.sha256`）：

- [CloudRendering ZIP](https://s3-us-west-2.amazonaws.com/ai2-thor-public/builds/thor-CloudRendering-f0825767cd50d69f666c7f282e54abfe58f1e917.zip)
- [官方 SHA-256 sidecar](https://s3-us-west-2.amazonaws.com/ai2-thor-public/builds/thor-CloudRendering-f0825767cd50d69f666c7f282e54abfe58f1e917.sha256)

例如把两个文件分别保存为 `build.zip`、`build.sha256`，上传到服务器的 `/root/will_not_be_push_to_git/idea1_firsttest_20sample/`，然后执行以下完整导入命令。若实际文件名不同，只替换这两条路径：

```bash
cd /root/idea1_verify_all/idea1_firsttest_20sample && \
bash linux_server_operation/13_prepare_thor_build.sh \
  --archive /root/will_not_be_push_to_git/idea1_firsttest_20sample/build.zip \
  --sha256-file /root/will_not_be_push_to_git/idea1_firsttest_20sample/build.sha256
```

脚本检查精确文件大小与官方 SHA-256，安全检查 ZIP 路径和符号链接，在读取解压内容时核对 ZIP CRC，并确认预期 Unity executable 与非空 `_Data` 目录。校验后的 build 先在外部数据目录暂存，再通过同一文件系统的原子目录改名安装到 `DATA_ROOT/unity_cache/releases/thor-CloudRendering-<commit>/`，这是本项目 `runtime.py` 指定的缓存。它不会修改 `runtime.py`、`HOME` 或系统链接，也不会启动 Unity。

已有完整缓存会直接跳过；已有但不完整的目标目录会保留并报错，不会覆盖或删除。旧 smoke 曾在内存中接收、最终失败的约 13 MiB 数据不构成 `.part`，无法续传。通过准备步骤后，再明确运行：

```bash
bash linux_server_operation/03_smoke.sh FloorPlan1
```

可用以下只读检查让主流程在启动前确认固定 build 已缓存（供 `03_smoke.sh` guard 使用）：

```bash
"$CONDA_EXE" run --no-capture-output -n "$CONDA_ENV" python \
  "$PROJECT_DIR/linux_server_operation/13_thor_build.py" \
  --check-cache --data-root "$DATA_ROOT"
```

阶段日志和下载/暂存数据都在 Git 外 `DATA_ROOT` 下。AI2-THOR `5.0.0` 官方实现可参考 [build.py](https://raw.githubusercontent.com/allenai/ai2thor/5.0.0/ai2thor/build.py)、[downloader.py](https://raw.githubusercontent.com/allenai/ai2thor/5.0.0/ai2thor/downloader.py) 与 [controller.py](https://raw.githubusercontent.com/allenai/ai2thor/5.0.0/ai2thor/controller.py)。
