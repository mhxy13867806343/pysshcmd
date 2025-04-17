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
__version__ = "2025.04.17"
from tqdm import tqdm
import os
import time
import shutil
import webbrowser
import paramiko
import json
from getpass import getpass
import sys
import glob
from datetime import datetime
import socket
import platform
import urllib.request

# 统一配置文件路径，支持 macOS/Linux/Windows
from pathlib import Path
if sys.platform == 'win32':
    CONFIG_FILE = str(Path.home() / 'deploy_dist_config.json')
else:
    CONFIG_FILE = str(Path.home() / '.deploy_dist_config.json')

# 默认 dist 目录
DEFAULT_DIST = "dist"

# 历史记录目录
HISTORY_DIR = str(Path.home() / '.deploy_dist_history')
os.makedirs(HISTORY_DIR, exist_ok=True)

# 菜单操作历史记录文件
MENU_HISTORY_FILE = str(Path.home() / '.deploy_dist_menu_history.json')

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

def input_config(default=None):
    # default: dict, 用于回显和默认值
    if default is None:
        default = {}
    def get_input(prompt, key, hide=False, default_val=None):
        if hide:
            val = getpass(f"{prompt} (留空默认[{default.get(key, default_val) or ''}]): ")
        else:
            val = input(f"{prompt} (留空默认[{default.get(key, default_val) or ''}]): ")
        if val.strip() == '':
            return default.get(key, default_val) or ''
        return val
    name = get_input("配置名称", "name")
    host = get_input("服务器IP", "host")
    port = get_input("端口", "port", default_val="22") or "22"
    username = get_input("用户名", "username")
    password = get_input("密码", "password", hide=True)
    remote_path = get_input("服务器目标目录", "remote_path")
    local_dist = get_input(f"本地dist目录", "local_dist", default_val=DEFAULT_DIST) or DEFAULT_DIST
    test_url = get_input("测试URL", "test_url")
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

def menu_copy_config():
    print("\n==== 复制配置到本地工具菜单 ====")
    print("请粘贴一份单条配置（格式如 {\"name\":\"xx\",...}），按回车结束：")
    user_input = input().strip()
    try:
        cfg = json.loads(user_input)
        if not isinstance(cfg, dict):
            raise ValueError
        # 检查必须包含 name、host、username、remote_path 字段（可根据实际需求调整）
        must_keys = ["name", "host", "username", "remote_path"]
        if not all(k in cfg for k in must_keys):
            print("❌ 格式不正确，缺少必要字段！\n")
            return
        configs = load_configs()
        configs.append(cfg)
        save_configs(configs)
        print("✅ 配置已保存！\n")
    except Exception as e:
        print("❌ 粘贴内容不是有效的 JSON 对象，或格式错误！\n")

def save_history_record(record):
    date_str = datetime.now().strftime('%Y-%m-%d')
    base_path = os.path.join(HISTORY_DIR, f'{date_str}.json')
    if not os.path.exists(base_path):
        path = base_path
    else:
        # 查找已有同日文件，自动编号
        i = 1
        while True:
            suffix = f'({i:03d}a)'
            path = os.path.join(HISTORY_DIR, f'{date_str}{suffix}.json')
            if not os.path.exists(path):
                break
            i += 1
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    print(f'历史记录已保存: {path}')

def list_history_records():
    files = glob.glob(os.path.join(HISTORY_DIR, '*.json'))
    files.sort()
    if not files:
        print('无历史记录')
    else:
        for idx, f in enumerate(files):
            print(f'{idx+1}. {os.path.basename(f)}')
    return files

def delete_history_record():
    files = list_history_records()
    if not files:
        return
    idx = input('输入要删除的历史记录序号: ').strip()
    try:
        idx = int(idx) - 1
        if 0 <= idx < len(files):
            os.remove(files[idx])
            print('已删除:', os.path.basename(files[idx]))
        else:
            print('无效序号!')
    except Exception:
        print('输入有误!')

def export_configs():
    configs = load_configs()
    if not configs:
        print('无配置可导出。')
        return
    print('\n可导出的配置列表:')
    for i, c in enumerate(configs):
        print(f'{i+1}. {c.get("name", "无名配置")} ({c.get("host", "无host")})')
    idxs = input('输入要导出的配置序号（多个用英文逗号分隔, 如1,3,4）: ').strip()
    try:
        idx_list = [int(x)-1 for x in idxs.split(',') if x.strip().isdigit()]
        selected = [configs[i] for i in idx_list if 0 <= i < len(configs)]
        if not selected:
            print('未选择任何有效配置。')
            return
        out = json.dumps(selected, ensure_ascii=False, indent=2)
        print('\n===== 导出内容如下（可复制保存） =====\n')
        print(out)
        print('\n===== 复制结束 =====\n')
    except Exception as e:
        print('输入有误，导出失败！')

def log_menu_usage(menu_name):
    try:
        if os.path.exists(MENU_HISTORY_FILE):
            with open(MENU_HISTORY_FILE, 'r', encoding='utf-8') as f:
                history = json.load(f)
        else:
            history = []
        history.append({'menu': menu_name, 'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
        with open(MENU_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        pass

def show_menu_history():
    if not os.path.exists(MENU_HISTORY_FILE):
        print('暂无菜单使用历史。')
        return
    with open(MENU_HISTORY_FILE, 'r', encoding='utf-8') as f:
        history = json.load(f)
    if not history:
        print('暂无菜单使用历史。')
        return
    print('\n==== 菜单使用历史（最近20条） ====' )
    for i, item in enumerate(history[-20:]):
        print(f'{i+1}. {item["timestamp"]} - {item["menu"]}')
    print('==============================\n')

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '未知IP'

def get_os_info():
    return f"{platform.system()} {platform.release()}"

def get_greeting(now):
    hour = now.hour
    minute = now.minute
    if hour < 12:
        return "上午好"
    elif 12 <= hour < 14:
        return "中午好"
    elif 14 <= hour < 18:
        return "下午好"
    elif 18 <= hour < 21:
        return "晚上好"
    elif hour == 21 and minute < 30:
        return "晚上好"
    else:
        return "现在已是21:30以后，建议早点休息！"

def get_python_version():
    return f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

def get_remote_version():
    url = "https://raw.githubusercontent.com/mhxy13867806343/pysshcmd/main/sshcdm.py"
    try:
        with urllib.request.urlopen(url, timeout=3) as f:
            for line in f:
                line = line.decode('utf-8').strip()
                if line.startswith("__version__"):
                    return line.split('=')[1].strip().strip('"')
        return None
    except Exception:
        return None

def self_update():
    import sys
    import time
    import urllib.request
    import tempfile
    import shutil

    url = "[https://raw.githubusercontent.com/mhxy13867806343/pysshcmd/main/sshcdm.py"](https://raw.githubusercontent.com/mhxy13867806343/pysshcmd/main/sshcdm.py")
    target = sys.argv[0]
    print("正在下载最新版...")

    try:
        try:
            from tqdm import tqdm
            use_tqdm = True
        except ImportError:
            use_tqdm = False

        with urllib.request.urlopen(url) as response:
            total = int(response.getheader('Content-Length', 0))
            downloaded = 0
            chunk_size = 8192
            with tempfile.NamedTemporaryFile('wb', delete=False) as tmp_file:
                tmp_path = tmp_file.name
                if use_tqdm:
                    bar = tqdm(total=total, unit='B', unit_scale=True, desc='下载进度')
                start = time.time()
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    tmp_file.write(chunk)
                    downloaded += len(chunk)
                    if use_tqdm:
                        bar.update(len(chunk))
                    else:
                        percent = downloaded * 100 // total if total else 0
                        speed = downloaded / (time.time() - start + 0.1)
                        print(f"\r进度: {percent}%  {downloaded//1024}KB/{total//1024}KB  速度: {speed/1024:.2f}KB/s", end='', flush=True)
                if use_tqdm:
                    bar.close()
        print("\n下载完成，准备覆盖本地脚本...")

        try:
            shutil.move(tmp_path, target)
            print("升级成功，请重新运行命令。")
            sys.exit(0)
        except PermissionError:
            print(f"\n覆盖失败：没有权限写入 {target}，请用 sudo 重新运行升级。")
        except Exception as e:
            print(f"\n覆盖失败：{e}")
    except Exception as e:
        print(f"升级失败，请检查网络或权限。错误: {e}")

def main_menu():
    while True:
        now_dt = datetime.now()
        now = now_dt.strftime('%Y-%m-%d %H:%M:%S')
        greeting = get_greeting(now_dt)
        ip = get_local_ip()
        os_info = get_os_info()
        py_ver = get_python_version()
        remote_ver = get_remote_version()
        print(f"\n==== 自动化部署工具菜单 ====")
        print(f"当前时间: {now}  {greeting}")
        print(f"本机IP: {ip}")
        print(f"操作系统: {os_info}")
        print(f"Python版本: {py_ver}")
        print(f"当前脚本版本: {__version__}")
        if remote_ver and remote_ver != __version__:
            print(f"⚠️ 检测到新版本 {remote_ver}，请使用菜单12升级！")
        print("请选择下面的菜单：")
        print("1. 新增必要配置")
        print("2. 查看所有配置")
        print("3. 修改指定配置")
        print("4. 删除配置")
        print("5. 添加配置（复制粘贴）")
        print("6. 部署/上传")
        print("7. 查看历史记录")
        print("8. 删除历史记录")
        print("9. 导出配置")
        print("10. 查看菜单使用历史")
        print("11. 退出")
        print("12. 升级到最新版")
        choice = input("请选择操作: ")
        if choice == '12':
            self_update()
        if choice == '10':
            show_menu_history()
            continue
        menu_map = {
            '1': '新增必要配置', '2': '查看所有配置', '3': '修改指定配置',
            '4': '删除配置', '5': '添加配置（复制粘贴）', '6': '部署/上传',
            '7': '查看历史记录', '8': '删除历史记录', '9': '导出配置',
        }
        if choice in menu_map:
            log_menu_usage(menu_map[choice])
        if choice == '1' or choice == '5':
            config = input_config()
            configs = load_configs()
            configs.append(config)
            save_configs(configs)
            print("配置已新增。")
        elif choice == '2':
            if not load_configs():
                print("无配置。")
            for i, c in enumerate(load_configs()):
                print(f"{i+1}. {c}")
        elif choice == '3':
            if not load_configs():
                print("无配置。")
                continue
            idx = input("输入要修改的配置序号: ")
            try:
                idx = int(idx) - 1
                configs = load_configs()
                if 0 <= idx < len(configs):
                    print("原配置:", configs[idx])
                    # 传递原配置给 input_config，只有用户输入才覆盖，否则用原值
                    config = input_config(default=configs[idx])
                    configs[idx] = config
                    save_configs(configs)
                    print("配置已修改。")
                else:
                    print("无效序号！")
            except Exception:
                print("输入有误！")
        elif choice == '4':
            if not load_configs():
                print("无配置。")
                continue
            idx = input("输入要删除的配置序号: ")
            try:
                idx = int(idx) - 1
                if 0 <= idx < len(load_configs()):
                    configs = load_configs()
                    configs.pop(idx)
                    save_configs(configs)
                    print("配置已删除。")
                else:
                    print("无效序号！")
            except Exception:
                print("输入有误！")
        elif choice == '5':
            menu_copy_config()
        elif choice == '6':
            config = select_config(load_configs())
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
            save_history_record(config)
        elif choice == '7':
            list_history_records()
        elif choice == '8':
            delete_history_record()
        elif choice == '9':
            export_configs()
        elif choice == '11':
            print("退出。"); break
        else:
            print("无效选择，请重新输入！")

if __name__ == "__main__":
    main_menu()
