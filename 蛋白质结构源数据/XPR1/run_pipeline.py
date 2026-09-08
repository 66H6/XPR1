"""项目主入口：当前仅实现数据入库与第4节启动检查。"""
import argparse
import json
import sys
from pathlib import Path

from src.common import relative_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'fetch-supporting', 'snapshot'])
    parser.add_argument('--config', default='config/smoke.json')
    parser.add_argument('--output', help='仅供snapshot使用，创建新的校验和文件（不能覆盖旧文件）')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    try:
        config = json.loads(relative_path(root, args.config).read_text(encoding='utf-8'))
        if config.get('stage') != 'intake' or config.get('generation_enabled') is not False:
            raise ValueError('本入口只接受intake配置；pilot/scale尚未实现，不能运行模型生成')
        if args.output and args.command != 'snapshot':
            raise ValueError('--output只用于snapshot')
        if args.command == 'fetch-supporting':
            from src.supporting import fetch_all
            return fetch_all(root, config)
        if args.command == 'snapshot':
            from src.checksums import create_baseline
            count = create_baseline(root, config, args.output)
            print(f'已创建{count}个输入文件的校验和基准。创建基准不等于验证过往下载来源。')
            return 0
        from src.intake import run_check
        return run_check(root, config, args.config)
    except Exception as exc:
        print(f'ERROR: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
