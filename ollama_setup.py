import subprocess
import sys
import webbrowser

MODEL_NAME = 'qwen3.5:4b'
if sys.platform == 'win32':
    DOWNLOAD_URL = 'https://ollama.com/download/windows'
elif sys.platform == 'darwin':
    DOWNLOAD_URL = 'https://ollama.com/download/mac'


def check_ollama_installed():
    """检测本机是否已安装 ollama 命令行工具"""
    try:
        subprocess.run(
            ['ollama', '--version'],
            capture_output=True,
            check=True,
            timeout=5
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def check_model_installed(model_name=MODEL_NAME):
    """检测目标模型是否已经下载到本机"""
    try:
        result = subprocess.run(
            ['ollama', 'list'],
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        return model_name in result.stdout
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def pull_model(model_name=MODEL_NAME):
    """下载模型，实时打印 ollama 的下载进度"""
    print(f'正在下载模型 {model_name}（约3.4GB，请保持网络畅通）...')
    try:
        # 不用 capture_output，让 ollama 自己的进度条直接打印到终端
        subprocess.run(['ollama', 'pull', model_name], check=True)
        return True
    except subprocess.CalledProcessError:
        print('模型下载失败，请检查网络后重试，或手动运行: ollama pull ' + model_name)
        return False


def ensure_ollama_ready(model_name=MODEL_NAME, download_url=DOWNLOAD_URL):
    """
    程序启动时调用这个函数做前置检查。
    如果环境没准备好，会引导用户安装/下载，并在必要时退出程序。
    """
    if not check_ollama_installed():
        print('=' * 50)
        print('检测到本机尚未安装 Ollama（本程序依赖它运行本地语言模型）。')
        print('=' * 50)
        answer = input('是否现在打开官网下载页？(y/n): ').strip().lower()
        if answer == 'y':
            webbrowser.open(download_url)
        print('请安装完成后，重新启动本程序。')
        sys.exit(0)

    if not check_model_installed(model_name):
        print('=' * 50)
        print(f'检测到尚未下载所需模型：{model_name}')
        print('=' * 50)
        answer = input('是否现在下载？(y/n): ').strip().lower()
        if answer == 'y':
            success = pull_model(model_name)
            if not success:
                sys.exit(1)
        else:
            print('未下载模型，程序无法继续运行。')
            sys.exit(0)

    print('Ollama 环境检测通过。')