"""安全接入本次补丁：默认检查；--apply才改文件；不提交、不推送。"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

BASE = 'c1b1b7d967f125eb10f2927f0800ab384782c1b1'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repository', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = args.repository.resolve()
    patch = Path(__file__).resolve().parent/'XPR1_section3_update.patch'
    def git(*parts):
        return subprocess.check_output(['git', '-C', str(root), *parts], text=True, stderr=subprocess.STDOUT).strip()
    try:
        if Path(git('rev-parse', '--show-toplevel')).resolve() != root:
            raise ValueError('请输入现有仓库根目录，不是其子目录。')
        url = git('remote', 'get-url', 'origin')
        if not re.fullmatch(r'(?:https://github\.com/66H6/XPR1(?:\.git)?|git@github\.com:66H6/XPR1\.git)/?', url):
            raise ValueError('origin不是66H6/XPR1，拒绝自动接入。')
        if git('status', '--porcelain'):
            raise ValueError('工作区有已有修改或未跟踪文件，请先妥善保存；工具不会覆盖。')
        if git('rev-parse', 'HEAD') != BASE:
            raise ValueError('基础提交已变化，请先重新合并；不要强行覆盖。')
        if not patch.is_file():
            raise ValueError('缺少与此工具同目录的补丁。')
        git('apply', '--check', str(patch))
        print('检查通过：仓库、基础版本、干净工作区与补丁均匹配。')
        if args.apply:
            git('apply', str(patch))
            print('补丁已应用到本地，未提交、未推送。请按说明运行检查，复核后再提交。')
        else:
            print('这是只读检查。确认后加--apply执行。')
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print('停止：'+str(exc), file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError):
            print(exc.output, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
