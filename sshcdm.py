#!/usr/bin/env python3
"""
部署脚本一键安装与使用说明：

一键安装命令（终端粘贴）：

sudo curl -fsSL \
  https://raw.githubusercontent.com/mhxy13867806343/pysshcmd/main/sshcdm.py \
  -o /usr/local/bin/sshcdm
sudo chmod +x /usr/local/bin/sshcdm

# 检查是否安装成功
ls -l /usr/local/bin | grep sshcdm

echo $PATH    # 确保 /usr/local/bin 在 PATH 里

# 运行
sshcdm --help

脚本要求：
- 第一行必须是 #!/usr/bin/env python3
- 赋予可执行权限后可直接作为命令行工具使用

常见问题：
- 若提示 zsh: unknown file attribute: h，说明复制了带 markdown 方括号的链接，去掉方括号即可。
- 若提示找不到命令，检查 /usr/local/bin 是否在 PATH 中。

"""
import os
import time
import shutil
import webbrowser
import paramiko
import json
from getpass import getpass

CONFIG_FILE = "deploy_dist_config.json"

# 默认 dist 目录
DEFAULT_DIST = "dist"

# 配置结构示例：
# {
#   "name": "测试环境",
#   "host": "...",
#   "port": 22,
#   "username": "...",
#   "password": "...",
#   "remote_path": "...",
#   "local_dist": "dist",
#   "test_url": "..."
# }

def load_configs():
    if not os.path.exists(CONFIG_FILE):
        return []
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_configs(configs):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(configs, f, indent=2, ensure_ascii=False)

def input_config():
    name = input("配置名称: ")
    host = input("服务器IP: ")
    port = input("端口 (默认22): ") or "22"
    username = input("用户名: ")
    password = getpass("密码: ")
    remote_path = input("服务器目标目录: ")
    local_dist = input(f"本地dist目录 (默认{DEFAULT_DIST}): ") or DEFAULT_DIST
    test_url = input("测试URL: ")
    return {
        "name": name,
        "host": host,
        "port": int(port),
        "username": username,
        "password": password,
        "remote_path": remote_path,
        "local_dist": local_dist,
        "test_url": test_url
    }

def select_config(configs):
    if not configs:
        print("没有可用配置，请先新增配置！")
        return None
    print("请选择要使用的配置：")
    for i, c in enumerate(configs):
        print(f"{i+1}. {c['name']} [{c['host']}] ({c['remote_path']})")
    idx = input("输入序号: ")
    try:
        idx = int(idx) - 1
        if 0 <= idx < len(configs):
            return configs[idx]
    except Exception:
        pass
    print("无效选择！")
    return None

def wait_for_dist(path, timeout=600):
    if not os.path.exists(path):
        print(f"当前本地 dist 目录({path})不存在，请先执行打包命令。")
        return False
    print("等待 dist 目录生成...")
    for _ in range(timeout):
        if os.path.isdir(path):
            print("dist 目录已生成。")
            return True
        time.sleep(1)
    print("等待 dist 超时！")
    return False

def get_total_files(local_dir):
    total = 0
    for _, _, files in os.walk(local_dir):
        total += len(files)
    return total

def sftp_upload(local_dir, remote_dir, ssh):
    print(f"开始上传 {local_dir} 到 {remote_dir} ...")
    sftp = ssh.open_sftp()
    total_files = get_total_files(local_dir)
    uploaded = 0
    for root, dirs, files in os.walk(local_dir):
        rel_path = os.path.relpath(root, local_dir)
        remote_path = os.path.join(remote_dir, rel_path).replace("\\", "/")
        try:
            sftp.stat(remote_path)
        except IOError:
            sftp.mkdir(remote_path)
        for file in files:
            local_file = os.path.join(root, file)
            remote_file = os.path.join(remote_path, file).replace("\\", "/")
            sftp.put(local_file, remote_file)
            uploaded += 1
            percent = int(uploaded * 100 / total_files)
            print(f"\r上传进度: {percent}%", end="")
    sftp.close()
    print("\n上传完成。")

def main_menu():
    configs = load_configs()
    while True:
        print("\n==== 自动化部署工具菜单 ====")
        print("1. 新增必要配置")
        print("2. 查看所有配置")
        print("3. 修改指定配置")
        print("4. 删除配置")
        print("5. 添加配置")
        print("6. 部署/上传")
        print("7. 退出")
        choice = input("请选择操作: ")
        if choice == '1' or choice == '5':
            config = input_config()
            configs.append(config)
            save_configs(configs)
            print("配置已新增。")
        elif choice == '2':
            if not configs:
                print("无配置。")
            for i, c in enumerate(configs):
                print(f"{i+1}. {c}")
        elif choice == '3':
            if not configs:
                print("无配置。")
                continue
            idx = input("输入要修改的配置序号: ")
            try:
                idx = int(idx) - 1
                if 0 <= idx < len(configs):
                    print("原配置:", configs[idx])
                    configs[idx] = input_config()
                    save_configs(configs)
                    print("配置已修改。")
                else:
                    print("无效序号！")
            except Exception:
                print("输入有误！")
        elif choice == '4':
            if not configs:
                print("无配置。")
                continue
            idx = input("输入要删除的配置序号: ")
            try:
                idx = int(idx) - 1
                if 0 <= idx < len(configs):
                    configs.pop(idx)
                    save_configs(configs)
                    print("配置已删除。")
                else:
                    print("无效序号！")
            except Exception:
                print("输入有误！")
        elif choice == '6':
            config = select_config(configs)
            if not config:
                continue
            if not wait_for_dist(config['local_dist']):
                continue
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            print("连接服务器...")
            ssh.connect(config['host'], config['port'], config['username'], config['password'])
            sftp_upload(config['local_dist'], config['remote_path'], ssh)
            ssh.close()
            print("删除本地 dist 目录...")
            shutil.rmtree(config['local_dist'])
            print("dist 目录已删除。")
            print("打开浏览器测试页面...")
            webbrowser.open(config['test_url'])
        elif choice == '7':
            print("退出。"); break
        else:
            print("无效选择，请重新输入！")

if __name__ == "__main__":
    main_menu()
