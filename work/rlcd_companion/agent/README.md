# 实验室 Windows 安装

1. 安装 Python 3.11 或更新版本。将完整 ZIP 解压到固定目录；不要放在共享目录，config.json 包含专用令牌。
2. 保持 ZeroTier 在线，双击 install.cmd。安装器只合并自己的 Hooks，保留已有权限设置，并保存旧 Hooks 的备份。
3. 重启 Qoder IDE。Codex 中用 `/hooks` 审核并信任 RLCD Hooks；如果桌面版没有该入口，在共享相同用户配置的 Codex CLI 中审核，然后重启桌面版。不会自动绕过审核。
4. 分别执行一次任务，触发需要确认、继续、本轮完成、中断，观察屏幕和网页。旧版本缺少事件时显示未知，不凭进程忙闲推测完成。
5. diagnose.cmd 检查网络、客户端状态和待发送队列。start.cmd / stop.cmd 手动启动和停止；安装后随 Windows 用户登录启动。
6. 如需在实验室读取 GLM/Qoder 额度，运行 setup-accounts.cmd，本机输入凭据。在看板上使用相同账户标识，并关闭该账户“在本机采集”，避免两个位置重复轮询。

Codex 会只读增量扫描近期会话日志，恢复任务状态；不上传提示词、回复和工具参数。Qoder 使用 IDE Hooks，上线前的旧会话不会凭空恢复；首次启用后再提交一轮任务即可建立状态。

停止采集不影响 AI 客户端。若永久移除：删除用户 Startup 中 RLCD-Lab-Agent.cmd，以及 ~/.codex/hooks.json、~/.qoder/settings.json 里 command 指向本目录 agent.py 的 Hooks；请保留其他 Hooks。
