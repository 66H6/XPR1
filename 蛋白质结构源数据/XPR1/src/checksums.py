"""Creation is explicit and exclusive; checking never rewrites a baseline."""
import re
from .common import relative_path, sha256


def input_files(root, config):
    files = []
    for key in ('raw_structures', 'supporting_raw'):
        directory = relative_path(root, config[key])
        if directory.exists():
            files.extend(p for p in directory.rglob('*') if p.is_file())
    files.extend(relative_path(root, config[k]) for k in ('manifest', 'supporting_receipts', 'source_receipt'))
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('输入不可使用符号链接或越界路径')
    return sorted(set(files))


def create_baseline(root, config, output=None):
    root = root.resolve()
    path = relative_path(root, output or config['checksums'])
    rows = [(sha256(p), p.relative_to(root).as_posix()) for p in input_files(root, config)]
    if path in input_files(root, config):
        raise ValueError('校验和清单不能放在被校验的输入目录中')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        handle.writelines(f'{digest}  {name}\n' for digest, name in rows)
    return len(rows)


def verify_baseline(root, config):
    root = root.resolve()
    baseline = relative_path(root, config['checksums'])
    if not baseline.is_file():
        return [], ['NO_CHECKSUM_BASELINE']
    expected = {}
    errors = []
    for number, line in enumerate(baseline.read_text(encoding='utf-8').splitlines(), 1):
        if not line:
            continue
        if not re.fullmatch(r'[0-9a-f]{64}  .+', line):
            errors.append(f'BAD_CHECKSUM_LINE:{number}')
            continue
        digest, name = line.split('  ', 1)
        try:
            relative_path(root, name)
        except ValueError:
            errors.append(f'UNSAFE_CHECKSUM_PATH:{number}')
            continue
        if name in expected:
            errors.append(f'DUPLICATE_CHECKSUM_PATH:{name}')
        expected[name] = digest
    actual = {p.relative_to(root).as_posix(): p for p in input_files(root, config)}
    for name in sorted(set(actual) - set(expected)):
        errors.append('UNBASELINED_INPUT:'+name)
    for name in sorted(set(expected) - set(actual)):
        errors.append('BASELINE_SCOPE_OR_FILE_MISSING:'+name)
    checks = []
    for name, digest in sorted(expected.items()):
        path = relative_path(root, name)
        current = sha256(path) if path.is_file() else None
        match = current == digest
        checks.append({'path': name, 'expected_sha256': digest, 'actual_sha256': current, 'match': match})
        if not match:
            errors.append('HASH_MISMATCH_OR_MISSING:'+name)
    return checks, errors
