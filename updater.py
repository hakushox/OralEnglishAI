"""
updater.py —— 独立的更新执行器，只在Windows平台使用

设计原则：
1. 这个脚本必须打包成一个独立的exe（updater.exe），跟主程序 SpeakNatural.exe 分开打包
2. 运行时必须放在 app_dir 之外（比如相邻的隐藏文件夹），
   否则删除 app_dir 时会把自己也删掉
3. 主程序调用它的方式：
   subprocess.Popen([str(updater_path), str(app_dir), str(zip_path), exe_name])
   传三个参数：app_dir（主程序所在文件夹）、zip_path（下载好的更新包）、exe_name（可执行文件名）
4. 无论更新成功还是失败，最后都要把主程序重新拉起来，
   不能让用户打开电脑发现程序"消失了"却不知道为什么

文件替换机制说明（这次改动的核心）：
之前用 Python 自己的 shutil.rmtree + Path.replace 做文件替换，
遇到文件被其他进程（索引服务/杀毒软件/残留进程）占用时容易失败，
且重试机制是自己拼的，可靠性有限。
现在改用业界验证过的组合：
- taskkill /F 强制确保主程序进程彻底死透，不再被动等待锁释放
- robocopy /MIR 做文件替换，这是微软自带、久经考验的工具，
  自带重试机制，处理"文件被占用"这类场景比自己写重试循环更可靠
"""

import sys
import time
import shutil
import zipfile
import subprocess
from pathlib import Path


LOG_PREFIX = '[Updater]'


def log(msg):
    print(f'{LOG_PREFIX} {msg}')


def force_kill_main_process(exe_name):
    """
    确保主程序进程彻底死透，不管它是不是已经'看起来'退出了。
    taskkill如果目标进程本来就不存在会返回非0，这里不需要处理这种情况，
    因为我们的目的就是'确保它不在了'，不存在本身就已经达到目的。
    """
    log(f'确保 {exe_name} 已完全退出...')
    subprocess.run(
        ['taskkill', '/F', '/IM', exe_name],
        capture_output=True, timeout=10
    )
    # 给系统一点时间彻底释放文件锁，这个短暂等待作为额外保险保留
    time.sleep(1)


def extract_update(zip_path, temp_extract_dir):
    """解压更新包到临时目录，返回是否成功"""
    log('正在解压新版本...')
    try:
        if temp_extract_dir.exists():
            shutil.rmtree(temp_extract_dir, ignore_errors=True)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(temp_extract_dir)
        return True
    except Exception as e:
        log(f'解压失败: {e}')
        return False


def find_new_app_dir(temp_extract_dir, app_dir_name):
    """
    在解压出来的临时目录里，定位真正的新版本文件夹。
    优先找跟旧目录同名的文件夹；找不到就退而求其次，
    如果解压出来只有一个文件夹，直接用那个（兼容zip内层结构变化的情况）。
    """
    exact_match = temp_extract_dir / app_dir_name
    if exact_match.exists() and exact_match.is_dir():
        return exact_match

    subdirs = [d for d in temp_extract_dir.iterdir() if d.is_dir()]
    if len(subdirs) == 1:
        log(f'未找到名为{app_dir_name}的文件夹，使用解压出的唯一子文件夹: {subdirs[0].name}')
        return subdirs[0]

    return None


def robocopy_replace(new_app_dir, app_dir):
    """
    用robocopy /MIR把new_app_dir的内容镜像到app_dir，
    最终app_dir会跟new_app_dir一模一样（新增/覆盖/删除多余文件）。
    /R:5 /W:2 表示每个文件最多重试5次，每次间隔2秒，
    不用robocopy默认的一百万次重试、30秒间隔那个夸张的默认值。

    robocopy的返回码不是"0=成功、非0=失败"这种简单规则，
    它是按位组合的：0-7都代表不同程度的成功
    （比如"复制了文件"、"有些文件被跳过因为已经相同"等都算成功范畴），
    只有>=8才代表真正出了问题（比如有文件复制失败、参数错误等）。
    """
    log('使用robocopy替换文件...')
    result = subprocess.run(
        ['robocopy', str(new_app_dir), str(app_dir), '/MIR', '/R:5', '/W:2'],
        capture_output=True, text=True
    )
    if result.returncode >= 8:
        log(f'robocopy报告替换失败，返回码: {result.returncode}')
        log(result.stdout[-2000:])  # 只打印末尾一部分，避免刷屏
        return False

    log(f'robocopy执行完成，返回码: {result.returncode}（0-7均属正常范畴）')
    return True


def cleanup(zip_path, temp_extract_dir):
    """清理下载和解压过程中产生的临时文件，失败不影响主流程"""
    try:
        if zip_path.exists():
            zip_path.unlink()
    except Exception as e:
        log(f'清理zip文件失败（不影响更新结果）: {e}')

    try:
        if temp_extract_dir.exists():
            shutil.rmtree(temp_extract_dir, ignore_errors=True)
    except Exception as e:
        log(f'清理临时解压目录失败（不影响更新结果）: {e}')


def relaunch(app_dir, exe_name):
    """重新拉起主程序，不管更新成功与否都要执行这一步"""
    exe_file = app_dir / exe_name
    if not exe_file.exists():
        log(f'未找到可执行文件 {exe_file}，无法自动重启，请手动打开程序')
        return
    try:
        subprocess.Popen([str(exe_file)], cwd=str(app_dir))
        log('主程序已重新启动')
    except Exception as e:
        log(f'重启主程序失败: {e}')


def main():
    if len(sys.argv) < 4:
        log('参数不足，用法: updater.exe <app_dir> <zip_path> <exe_name>')
        input('按回车退出...')
        return

    app_dir = Path(sys.argv[1])
    zip_path = Path(sys.argv[2])
    exe_name = sys.argv[3]
    app_dir_name = app_dir.name

    log(f'目标程序目录: {app_dir}')
    log(f'更新包: {zip_path}')

    if not zip_path.exists():
        log('更新包不存在，无法继续，将直接重启旧版本')
        relaunch(app_dir, exe_name)
        return

    # 第一步：强制确保主程序进程彻底退出，不再被动等待锁释放
    force_kill_main_process(exe_name)

    # 第二步：解压
    temp_extract_dir = app_dir.parent / f'{app_dir_name}_update_temp'
    if not extract_update(zip_path, temp_extract_dir):
        log('解压失败，放弃本次更新，重启旧版本')
        cleanup(zip_path, temp_extract_dir)
        relaunch(app_dir, exe_name)
        return

    # 第三步：定位解压出来的新版本文件夹
    new_app_dir = find_new_app_dir(temp_extract_dir, app_dir_name)
    if new_app_dir is None:
        log('无法在解压结果中定位新版本文件夹，放弃本次更新')
        cleanup(zip_path, temp_extract_dir)
        relaunch(app_dir, exe_name)
        return

    # 第四步：用robocopy替换文件（自带重试，比手写重试更可靠）
    success = robocopy_replace(new_app_dir, app_dir)

    # 第五步：清理临时文件
    cleanup(zip_path, temp_extract_dir)

    if success:
        log('更新成功')
    else:
        log('更新失败，将尝试启动现有版本（可能仍是旧版本，也可能目录已损坏）')

    # 第六步：无论成败，都尝试重新拉起主程序
    relaunch(app_dir, exe_name)


if __name__ == '__main__':
    main()