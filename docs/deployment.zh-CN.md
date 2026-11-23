# 部署 YSudoku

## 快速体验

需要 Git、Python 3.10+ 和 Node.js 20+（含 npm）。首次运行时安装依赖并构建网页。如果已经下载仓库，从仓库根目录执行最后两行。

```bash
git clone https://github.com/CodeInDreams/YSudoku.git
cd YSudoku
npm --prefix web ci && npm --prefix web run build
npm --prefix tools ci && (cd tools && npx playwright install chromium)
```

任选一种启动方式，然后打开 [http://127.0.0.1:8765/](http://127.0.0.1:8765/)，点击「示例」即可体验。

### 本地解析

无需配置 API 密钥。如果当前终端已经配置过密钥，可以在网页设置里关闭 LLM 解析。

```bash
python3 -m ysudoku --web
```

### 启用 LLM

将 `YOUR_DEEPSEEK_API_KEY` 换成自己的 DeepSeek API 密钥。

```bash
SUDOKU_LLM_API_KEY='YOUR_DEEPSEEK_API_KEY' python3 -m ysudoku --web
```

## 公开部署

构建网页并安装 Playwright Chromium 后，运行一份 Python HTTP 服务。全局并发在服务进程内协调，令牌和每 IP 次数存放在数据目录的 SQLite 中。一个公开站点应运行一个服务进程，由反向代理转发到它。Linux 服务会锁定数据目录，避免多个进程各自计算全局配额。

## 安装与更新

把工程目录外的 `install.sh` 和 `update.sh` 放在远程服务器的同一个目录，在 Debian 或 Ubuntu 上以 root 运行。

```bash
bash install.sh
# 编辑 /etc/ysudoku/config.toml 和 /etc/ysudoku/secrets.env 后重新启动
systemctl restart ysudoku
# 日后拉取并部署最新代码
bash update.sh
```

[config.toml.example](config.toml.example) 按服务、限额、LLM、存储、网络、渲染和求解器分组。安装脚本把它写入 `/etc/ysudoku/config.toml`。更新保留配置中的已有值和注释，并为模板里新增的键补上默认值和注释。增加部署配置时，应同时更新模板和后端配置定义。

| 文件 | 用途 |
| --- | --- |
| `/etc/ysudoku/config.toml` | 管理员维护的部署配置，重启后生效 |
| `/etc/ysudoku/secrets.env` | LLM 密钥和管理员令牌。由 systemd 读取，只允许 root 读写 |
| `/etc/ysudoku/banned-ips.txt` | 永久封禁名单，每五分钟加载 |
| `/var/lib/ysudoku/store/settings.json` | 网页保存的共享存储覆盖值。配置了 `storage.store_dir` 时，文件跟随该目录 |

当 `storage.allow_settings = true` 时，网页覆盖值按项优先，其他项使用部署默认值。当它为 `false` 时，服务忽略已保存的覆盖值，并保留文件，重新开启后可继续使用。网页的历史页会标明每项设置的当前来源。把某项改回部署默认值会清掉该项覆盖。缓存目录和求解限额仍由管理员维护。

脚本默认部署 `main`，也可传入分支或标签。它以 `ysudoku-build` 构建，以 `ysudoku` 运行。更新会先构建新版本，启动检查失败时恢复原程序和配置。由旧脚本创建的 `/etc/ysudoku/ysudoku.env` 会在首次迁移时读入新文件，并保留原件。

初始监听地址为 `127.0.0.1:8765`。如果把写入路径移到 `/var/lib/ysudoku` 之外，需要通过 systemd drop-in 开放对应目录的写入权限。可使用 `python3 -m ysudoku --web --config /path/to/config.toml` 手动启动。显式指定的 `--host` 和 `--port` 优先，其他设置以 TOML 中提供的值为准。缺省项仍可使用旧环境变量。

## 运行账号

用独立的系统账号启动 YSudoku。账号须能读取代码和 Chromium，并能写入数据目录。以下是 systemd 配置的核心部分，目录和二进制位置按实际安装填写。

```ini
[Service]
User=ysudoku
Group=ysudoku
WorkingDirectory=/opt/ysudoku/current
EnvironmentFile=/etc/ysudoku/secrets.env
ExecStart=/usr/bin/python3 -m ysudoku --web --config /etc/ysudoku/config.toml
StateDirectory=ysudoku
NoNewPrivileges=true
Restart=on-failure
```

在配置文件中使用 `server.user = "ysudoku"` 可校验账号。由 root 启动时，服务在创建监听端口和浏览器进程前切换用户。未设置时使用启动服务的账号。用独立账号安装 Chromium，或通过 `PLAYWRIGHT_BROWSERS_PATH` 指定账号可读取的安装位置。

如果在同一台主机部署第二个独立站点，给两个站点各自设置 HTTP 端口、`YSUDOKU_LIVE_PORT` 和 `YSUDOKU_DATA_DIR`。同一站点内的用户共享规则、步骤、截图缓存和令牌预算。不同数据目录的预算分别统计，即使两个站点使用同一 API 密钥。

## 旧环境变量部署

已有的纯环境变量部署仍可继续使用。以下是兼容的变量。新安装优先使用 TOML。

| 环境变量 | 含义 | 默认 |
| --- | --- | --- |
| `YSUDOKU_MAX_CONCURRENT` | 服务同时处理的任务数。加载、规则解析、求解、渲染完成或失败都在同一任务内 | `0`，不限 |
| `YSUDOKU_DAILY_SOLVES_PER_IP` | 每 IP 每天可启动的求解次数。所有重新求解或解析入口共用同一额度 | `0`，不限 |
| `YSUDOKU_DAILY_LLM_INPUT_TOKENS` | 所有用户共享的每日 LLM 输入令牌阈值 | `0`，不限 |
| `YSUDOKU_DAILY_LLM_OUTPUT_TOKENS` | 所有用户共享的每日 LLM 输出令牌阈值 | `0`，不限 |
| `YSUDOKU_QUOTA_TIMEZONE` | 每日额度重置的时区，使用 IANA 名称 | `Asia/Shanghai` |
| `YSUDOKU_DATA_DIR` | 持久数据目录 | 项目下的 `.cache` |
| `YSUDOKU_RUN_USER` | 专用系统账号 | 启动服务的账号 |
| `YSUDOKU_LIVE_PORT` | 本机截图进程端口 | `8791` |
| `YSUDOKU_ALLOW_STORAGE_SETTINGS` | 允许通过网页修改共享存储设置 | `1` |
| `YSUDOKU_ALLOW_DELETE` | 允许删除共享历史、谜题及缓存层 | `1` |
| `YSUDOKU_ADMIN_TOKEN` | 配置后，受开关允许的管理接口仍须提供 Bearer 令牌 | 空 |
| `YSUDOKU_BANNED_IPS` | 永久封禁的 IP 或 CIDR，以逗号、空格分隔 | 空 |
| `YSUDOKU_BAN_FILE` | 可热更新的封禁名单，支持每行一个 IP 或 CIDR 和 `#` 注释 | 空 |
| `YSUDOKU_TRUSTED_PROXIES` | 允许代报客户端 IP 的直连代理 CIDR | 空 |
| `YSUDOKU_PROXY_IP_HEADER` | 可信代理提供的单值 IP 请求头 | `CF-Connecting-IP`，也可设 `X-Real-IP` |

如果继续使用旧的纯环境变量部署，可以在原来的环境文件中填入以下配置。

```ini
YSUDOKU_RUN_USER=ysudoku
YSUDOKU_DATA_DIR=/var/lib/ysudoku
YSUDOKU_LIVE_PORT=8792
YSUDOKU_MAX_CONCURRENT=2
YSUDOKU_DAILY_SOLVES_PER_IP=10
YSUDOKU_DAILY_LLM_INPUT_TOKENS=200000
YSUDOKU_DAILY_LLM_OUTPUT_TOKENS=40000
YSUDOKU_ALLOW_STORAGE_SETTINGS=0
YSUDOKU_ALLOW_DELETE=0
YSUDOKU_BAN_FILE=/etc/ysudoku/banned-ips.txt
```

完整缓存可以直接播放。只补截图会占用并发，但不扣每日求解次数。并发满时，新任务会被拒绝，弹窗只列在途题目和已用时间。任务一经受理即计一次，后续失败仍计入。关闭浏览器不会取消已提交的任务。当前截图进程按顺序渲染，多道题可同时解析或求解并等待渲染。

自定义规则补充与解析提示合计最多 1000 字符。LLM 令牌按服务商的 `prompt_tokens` 与 `completion_tokens` 统计，编译重试和规则修复也计入。用量到达任一阈值后，后续请求转为本地解析。配置阈值时模型调用串行核账，单次请求可能跨过阈值，尤其是只能在请求结束后准确得知的输入令牌。如服务商未返回用量或请求失败，已配置的令牌项会保守地按额度耗尽处理。

## 客户端 IP 和封禁

直连模式保持 TOML 的 `network.trusted_proxies = []`，以 TCP 对端地址为准。Cloudflare 直连源站时，填入 Cloudflare 对外发布的 IPv4 和 IPv6 网段，使用默认的 `CF-Connecting-IP`。如果应用连接的是本机反向代理，填写该代理的地址，并在代理配置中先验证上游来源，再覆盖转发的客户端 IP。代理应清理客户端自带的同名头。 [Cloudflare 原始访客 IP 文档](https://developers.cloudflare.com/support/troubleshooting/restoring-visitor-ips/restoring-original-visitor-ips/) · [Cloudflare IP 网段](https://www.cloudflare.com/ips/)

普通反向代理可将 `network.client_ip_header` 设为 `X-Real-IP`，由代理用实际连接对端覆盖该头。转发链中的任意 `X-Forwarded-For` 不会用于计费。Cloudflare 的 Pseudo IPv4 设为 Off 或 Add Header 可保留访客的 IPv6 地址。 [Cloudflare 请求头文档](https://developers.cloudflare.com/fundamentals/reference/http-headers/)

配置随进程启动读取。想不重启修改名单，编辑 `network.ban_file` 指向的文件。服务每五分钟检查一次，文件中列出的封禁没有到期时间。文件读取或格式校验失败会继续使用上次有效名单。

## 日志与共享缓存

服务向标准输出写 JSON 日志。写接口记录时间、IP 和题目，LLM 调用另记题目及输入、输出令牌。日志不写 API 密钥和提示正文。用 systemd 时可通过 `journalctl -u ysudoku` 查询。日志与用量数据库只供服务运营使用。

公开页面可浏览和重新生成共享结果。两个管理开关默认开启。在公开站点若保留默认且未配置管理员令牌，任意访客都可以调高容量上限或删除缓存。公开站点可在 TOML 中设置 `storage.allow_settings = false` 和 `storage.allow_delete = false`。自动缓存淘汰仍按容量设置运行。删除关闭时，网页不能调低数量上限，防止通过修改设置触发批量删除。

默认保留 1000 份规则、1000 份步骤、100 份截图，总上限 500 MiB。原题数据也计入总量，历史页会显示其大小。某层数目超限时，先清理该层中最早打开的题目。清理后若总量仍达到上限，已有完整缓存可播放，新增求解、重新求解和补渲染会收到存储已满提示，且不扣求解次数。已受理任务仍会完成，因此总量可暂时跨过阈值。

网页任务只接受支持的谜题链接或 ID。本地 JSON 可用于命令行。截图动作从保存的步骤生成，网页客户端无需提交原始浏览器动作。
