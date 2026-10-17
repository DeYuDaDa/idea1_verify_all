# Linux simulation environment notes

The intended runtime is Linux with Python 3.10, AI2-THOR 5.0.0, NumPy 1.23.5, and OpenCV 4.8.1, as pinned in this project's `requirements.txt`.

`CloudRendering` is the default THOR platform for the server scripts. It requires a working NVIDIA driver and Vulkan support in the server/container environment. The intended launch has `headless=False` with RGB rendering enabled; the smoke probe checks the actual launch and RGB frame path. If CloudRendering cannot initialize, inspect the preflight report and smoke-stage log before changing drivers or system packages.

Ubuntu 22.04 is a recommended starting point for a compatible Linux host, but it has not been verified on the target server. The preflight stage only reports visible system information; it does not claim that an untested host configuration is supported.

The first AI2-THOR launch may fetch runtime assets that are separate from Python package installation. Plan for network access and sufficient disk space before the smoke stage. Preflight/setup do not install operating-system packages or configure drivers. The separately invoked `09_fix_vulkan.sh` repairs the missing userspace Vulkan loader using `libvulkan1` and `vulkan-tools`; it does not install NVIDIA kernel drivers.

Uploaded server evidence on 2026-10-18 confirms environment installation and 18 passing unit tests. The first CloudRendering smoke failed because the Vulkan loader was missing. Follow `09_vulkan_repair.md`; a loadable Vulkan library and a CUDA-visible GPU do not by themselves establish Vulkan graphics access inside a container.
