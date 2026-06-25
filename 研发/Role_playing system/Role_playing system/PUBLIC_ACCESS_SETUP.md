# 固定公网访问配置

这个项目统一使用 `Python 3.10` 环境，已经支持两种公网访问方式：

1. 临时分享：`python run.py share`
2. 固定域名：配置 Cloudflare Tunnel Token 和固定域名

## 零、先准备 Python 3.10 环境

```powershell
conda activate python_3_10
python --version
```

期望输出为 `Python 3.10.x`。

如果环境还没建好，可以在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_python310.ps1
```

## 一、项目内配置

在服务器的 `.env` 里至少补上下面这些值：

```env
DATABASE_BACKEND=sqlite
SQLITE_DATABASE_URL=sqlite:///./roleplay_system.db

PUBLIC_BASE_URL=https://chat.example.com
CLOUDFLARE_TUNNEL_TOKEN=eyJxxxxxxxx

APP_TRUSTED_HOSTS=localhost,127.0.0.1,chat.example.com
APP_CORS_ORIGINS=https://chat.example.com
APP_HOST=0.0.0.0
APP_PORT=8000
APP_RELOAD=false
```

说明：

- `PUBLIC_BASE_URL`：你的固定公网地址
- `CLOUDFLARE_TUNNEL_TOKEN`：Cloudflare 命名隧道 token
- `APP_TRUSTED_HOSTS`：限制合法 Host，避免直接乱打 Host 头
- `APP_CORS_ORIGINS`：如果未来前后端分离或跨域调用，需要填公网域名

## 二、Cloudflare 侧需要做的事

固定公网地址不是代码自己生成的，必须在 Cloudflare 后台先建好：

1. 把你的域名接入 Cloudflare
2. 创建一个 Cloudflare Tunnel
3. 给这个 Tunnel 绑定一个公网主机名，比如 `chat.example.com`
4. 复制 Tunnel Token

这个项目代码已经支持直接读取该 Token 并启动固定域名隧道。

## 三、服务器启动方式

### 方式 A：先直接跑通

```powershell
conda activate python_3_10
python run.py share
```

如果配置了 `CLOUDFLARE_TUNNEL_TOKEN`，项目会按固定域名模式启动隧道。

### 方式 B：做成长期运行

建议把 API 做成 `systemd` 服务，再把 `cloudflared` 做成系统服务。

API 服务模板见：

- [deploy/roleplay-api.service.example](/E:/Role_playing system/Role_playing system/deploy/roleplay-api.service.example)

Cloudflare Tunnel 官方推荐直接装成系统服务。

Linux 上常见做法：

```bash
sudo cloudflared service install <TUNNEL_TOKEN>
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
```

然后再把 API 服务也启起来：

```bash
sudo systemctl enable roleplay-api
sudo systemctl start roleplay-api
```

## 四、验证

先看 API：

```powershell
conda activate python_3_10
curl http://127.0.0.1:8000/
```

再看 tunnel 服务：

```bash
systemctl status cloudflared
```

最后在浏览器访问：

```text
https://chat.example.com
```

## 五、官方文档

- Cloudflare Tunnel 概览：https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
- Tunnel Token：https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/configure-tunnels/remote-tunnel-permissions/
- Tunnel DNS 绑定：https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/routing-to-tunnel/dns/
- Tunnel 快速/固定发布：https://developers.cloudflare.com/tunnel/setup/
- Linux 作为服务运行：https://developers.cloudflare.com/tunnel/advanced/local-management/as-a-service/linux/
