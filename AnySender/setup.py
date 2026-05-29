"""
AnySender 一键安装 / 构建

    python setup.py              仅安装依赖
    python setup.py --build      安装依赖 + 打包 exe
    python setup.py --run        安装依赖 + 启动
"""

import os
import subprocess
import sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DEPS_SCRIPT = os.path.join(PROJECT_DIR, "deps", "setup.py")


def check_pyinstaller():
    try:
        import PyInstaller
        return True
    except ImportError:
        return False


def main():
    args = sys.argv[1:]
    do_build = "--build" in args or "-b" in args
    do_run = "--run" in args or "-r" in args

    # 透传未知参数给 deps/setup.py（如 --mirror --all）
    passthrough = [a for a in args if a not in ("--build", "-b", "--run", "-r")]

    # Step 1: 安装依赖
    print("[1/2] Check & install dependencies...")
    result = subprocess.run(
        [sys.executable, DEPS_SCRIPT] + passthrough,
        cwd=PROJECT_DIR,
    )
    if result.returncode != 0:
        print("Done with warnings.")

    # Step 2: 打包（可选）
    if do_build:
        if not check_pyinstaller():
            print("[2/2] Install PyInstaller...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("[2/2] Build exe...")
        spec = os.path.join(PROJECT_DIR, "AnySender.spec")
        subprocess.check_call(["pyinstaller", spec, "--noconfirm"])
        print(f"Done -> {PROJECT_DIR}\\dist\\AnySender.exe")

    # Step 3: 启动（可选）
    if do_run:
        print("[2/2] Starting AnySender...")
        main_py = os.path.join(PROJECT_DIR, "main.py")
        try:
            subprocess.run([sys.executable, main_py])
        except KeyboardInterrupt:
            print()  # 子进程已处理，父进程吞掉信号

    if not do_build and not do_run:
        print("Ready. Usage: python main.py   or   python setup.py --run")


if __name__ == "__main__":
    main()
