"""Read-only input checks and an explicit, limited entry gate to section 4."""
import collections
import gzip
import json
import math
import os
import platform
import re
import subprocess
import time
import warnings
from datetime import datetime, timezone

import gemmi

from .checksums import verify_baseline
from .common import read_manifest, relative_path, sha256, utc_now, write_csv, write_json
from .supporting import resource_plan, validate_bytes


def category(block, prefix):
    table = block.find_mmcif_category(prefix)
    return [{tag.removeprefix(prefix): gemmi.cif.as_string(value)
             for tag, value in zip(table.tags, row)} for row in table]


def norm_doi(value):
    return re.sub(r'^https?://(?:dx\.)?doi\.org/', '', value.strip().lower())


def manifest_problems(rows, config):
    errors = []
    ids = [r['PDB_ID'] for r in rows]
    if len(rows) != config['expected_entries']:
        errors.append('UNEXPECTED_MANIFEST_COUNT')
    if len(set(ids)) != len(ids):
        errors.append('DUPLICATE_MANIFEST_ID')
    if any(not re.fullmatch(r'[0-9][A-Z0-9]{3}', pdb) for pdb in ids):
        errors.append('INVALID_MANIFEST_ID')
    if any(not r['paper_family'] or not r['species'] or not r['reported_state'] for r in rows):
        errors.append('EMPTY_REQUIRED_ANNOTATION')
    for scope, count_key, family_key in [('TMD', 'expected_tmd_entries', 'expected_tmd_families'),
                                          ('SPX-only', 'expected_spx_entries', 'expected_spx_families')]:
        selected = [r for r in rows if r['structure_scope'] == scope]
        if len(selected) != config[count_key]:
            errors.append('UNEXPECTED_SCOPE_COUNT:'+scope)
        if len({r['paper_family'] for r in selected}) != config[family_key]:
            errors.append('UNEXPECTED_FAMILY_COUNT:'+scope)
    if any(r['structure_scope'] not in ('TMD', 'SPX-only') for r in rows):
        errors.append('UNKNOWN_STRUCTURE_SCOPE')
    family_dois = collections.defaultdict(set)
    doi_families = collections.defaultdict(set)
    for row in rows:
        doi = norm_doi(row['DOI'])
        if not doi.startswith('10.'):
            errors.append('INVALID_DOI:'+row['PDB_ID'])
        family_dois[row['paper_family']].add(doi)
        doi_families[doi].add(row['paper_family'])
    if any(len(s) != 1 for s in family_dois.values()):
        errors.append('MULTIPLE_PRIMARY_DOIS_IN_ONE_FAMILY')
    if any(len(s) != 1 for s in doi_families.values()):
        errors.append('SAME_PRIMARY_DOI_SPLIT_ACROSS_FAMILIES')
    return errors


def inspect_structure(path, row):
    result = {'PDB_ID': row['PDB_ID'], 'paper_family': row['paper_family'],
              'structure_scope': row['structure_scope'], 'filename': path.name,
              'sha256': sha256(path), 'bytes': path.stat().st_size,
              'errors': [], 'warnings': []}
    metadata = {'PDB_ID': row['PDB_ID'], 'paper_family': row['paper_family'],
                'structure_scope': row['structure_scope'], 'reported_state': row['reported_state'],
                'reclassified_state': 'UNRESOLVED' if row['structure_scope'] == 'TMD' else 'NOT_APPLICABLE',
                'role': 'UNASSIGNED', 'parent_sha256': result['sha256'],
                'source': 'deposited mmCIF metadata; not independently biologically reviewed',
                'canonical_residue_mapping_status': 'NOT_VALIDATED',
                'biological_assembly_selection_status': 'NOT_VALIDATED'}
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            block = gemmi.cif.read_file(str(path)).sole_block()
            result['entry_id'] = gemmi.cif.as_string(block.find_value('_entry.id') or '?').upper()
            if result['entry_id'] != row['PDB_ID'] or path.stem.upper() != row['PDB_ID']:
                result['errors'].append('ENTRY_OR_FILENAME_ID_MISMATCH')
            if block.name.upper() != row['PDB_ID']:
                result['errors'].append('DATA_BLOCK_ID_MISMATCH')
            atom_ids = list(block.find_values('_atom_site.id'))
            result['atom_site_rows'] = len(atom_ids)
            if not atom_ids:
                result['errors'].append('NO_ATOMS')
            if len(set(atom_ids)) != len(atom_ids):
                result['errors'].append('DUPLICATE_ATOM_SITE_ID')
            for axis in 'xyz':
                coords = list(block.find_values('_atom_site.Cartn_'+axis))
                if len(coords) != len(atom_ids) or not all(math.isfinite(float(x)) for x in coords):
                    result['errors'].append('INVALID_COORDINATE_'+axis)
            structure = gemmi.make_structure_from_block(block)
            result['models'] = len(structure)
            result['chains_per_model'] = [len(model) for model in structure]
            result['parsed_atoms'] = sum(1 for model in structure for chain in model for res in chain for atom in res)
            if not result['parsed_atoms'] or result['parsed_atoms'] != len(atom_ids):
                result['errors'].append('ATOM_COUNT_RECONCILIATION_FAILED')
            for prefix in ('_struct.', '_exptl.', '_em_3d_reconstruction.', '_refine.',
                           '_pdbx_audit_revision_history.', '_citation.', '_entity.', '_entity_poly.',
                           '_entity_src_gen.', '_entity_src_nat.', '_pdbx_entity_src_syn.',
                           '_struct_asym.', '_struct_ref.', '_struct_ref_seq.', '_struct_ref_seq_dif.',
                           '_pdbx_struct_assembly.', '_pdbx_struct_assembly_gen.', '_pdbx_struct_oper_list.',
                           '_pdbx_database_related.', '_pdbx_unobs_or_zero_occ_residues.',
                           '_pdbx_unobs_or_zero_occ_atoms.', '_pdbx_entity_nonpoly.',
                           '_pdbx_entity_branch.', '_struct_conn.'):
                metadata[prefix] = category(block, prefix)
            citations = metadata['_citation.']
            primary = [c for c in citations if c.get('id') == 'primary']
            if len(primary) != 1:
                result['warnings'].append('PRIMARY_CITATION_NOT_UNIQUE_OR_MISSING')
            else:
                observed_doi = norm_doi(primary[0].get('pdbx_database_id_DOI', ''))
                result['mmcif_primary_doi'] = observed_doi
                if observed_doi and observed_doi != norm_doi(row['DOI']):
                    result['errors'].append('MANIFEST_MMCIF_PRIMARY_DOI_MISMATCH')
            result['warnings'].extend(str(w.message) for w in caught)
    except Exception as exc:
        result['errors'].append(type(exc).__name__+': '+str(exc))
    result['passed'] = not result['errors']
    return result, metadata


def check_support(root, config):
    errors, outcomes = [], []
    receipt_path = relative_path(root, config['supporting_receipts'])
    if not receipt_path.exists():
        return [], ['MISSING_SUPPORTING_RECEIPTS']
    ledger = json.loads(receipt_path.read_text(encoding='utf-8'))
    receipts = {r['path']: r for r in ledger['resources']}
    if len(receipts) != len(ledger['resources']):
        errors.append('DUPLICATE_SUPPORTING_RECEIPT')
    for item in resource_plan(root, config):
        saved = receipts.get(item['path'], {})
        path = relative_path(root, item['path'])
        outcome = {**item, 'passed': False}
        try:
            if saved.get('status') != 'DOWNLOADED' or not path.is_file():
                raise ValueError('缺少文件或成功下载记录')
            if any(saved.get(k) != item.get(k) for k in ('url', 'kind', 'accession', 'parent_path')):
                raise ValueError('下载记录与资源计划不一致')
            if saved.get('sha256') != sha256(path):
                raise ValueError('下载记录与当前文件SHA-256不一致')
            parent_raw = relative_path(root, item['parent_path']).read_bytes() if item.get('parent_path') else None
            validate_bytes(path.read_bytes(), item['kind'], item['accession'], parent_raw)
            if item['kind'] == 'assembly':
                block = gemmi.cif.read_string(gzip.decompress(path.read_bytes()).decode()).sole_block()
                outcome['embedded_entry_id'] = gemmi.cif.as_string(block.find_value('_entry.id') or '?')
                outcome['identity_check'] = 'official_url_receipt_plus_parent_title_sequences_citations; geometry_not_validated'
            outcome['passed'] = True
        except Exception as exc:
            outcome['error'] = str(exc)
            errors.append('SUPPORTING_INPUT_FAILED:'+item['path'])
        outcomes.append(outcome)
    if not errors:
        fasta_path = relative_path(root, config['supporting_raw']+'/uniprot/Q9UBH6.fasta')
        meta_path = relative_path(root, config['supporting_raw']+'/uniprot/Q9UBH6.json')
        sequence = ''.join(fasta_path.read_text().splitlines()[1:])
        metadata = json.loads(meta_path.read_text())
        if sequence != metadata['sequence']['value']:
            errors.append('UNIPROT_FASTA_JSON_SEQUENCE_MISMATCH')
    return outcomes, errors


def repository_version(root):
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True, stderr=subprocess.DEVNULL).strip())
        return {'base_commit': commit, 'working_tree_dirty': dirty}
    except (OSError, subprocess.CalledProcessError):
        return {'base_commit': 'UNAVAILABLE_NOT_A_GIT_CHECKOUT', 'working_tree_dirty': None}


def assess(root, config):
    root = root.resolve()
    errors, notes = [], []
    if gemmi.__version__ != '0.7.3':
        errors.append('GEMMI_VERSION_MISMATCH_INSTALL_REQUIREMENTS')
    if platform.python_version_tuple()[:2] != ('3', '12'):
        notes.append({'code': 'PYTHON_VERSION_DIFFERS', 'meaning': '本机Python不是已验收的3.12系列；请用固定环境复测后再认定跨环境可复现。'})
    rows = read_manifest(relative_path(root, config['manifest']))
    errors.extend(manifest_problems(rows, config))
    raw = relative_path(root, config['raw_structures'])
    paths = sorted(p for p in raw.rglob('*') if p.is_file())
    cif_paths = [p for p in paths if p.suffix.lower() == '.cif']
    lookup = collections.defaultdict(list)
    for path in cif_paths:
        lookup[path.stem.upper()].append(path)
    expected = {r['PDB_ID'] for r in rows}
    for key in sorted(expected - set(lookup)):
        errors.append('MISSING_STRUCTURE:'+key)
    for key in sorted(set(lookup) - expected):
        errors.append('UNLISTED_STRUCTURE:'+key)
    for key, files in lookup.items():
        if len(files) != 1:
            errors.append('DUPLICATE_STRUCTURE_ID:'+key)
    if len(paths) != len(cif_paths):
        errors.append('UNEXPECTED_NON_CIF_FILE_IN_STRUCTURE_DIR')
    checks, hash_errors = verify_baseline(root, config)
    errors.extend(hash_errors)
    structures, metadata = [], []
    for row in rows:
        files = lookup.get(row['PDB_ID'], [])
        if len(files) == 1:
            result, meta = inspect_structure(files[0], row)
            structures.append(result)
            metadata.append(meta)
            errors.extend(row['PDB_ID']+':'+error for error in result['errors'])
    hashes = collections.defaultdict(list)
    for result in structures:
        hashes[result['sha256']].append(result['PDB_ID'])
    if any(len(group) > 1 for group in hashes.values()):
        errors.append('BYTE_IDENTICAL_STRUCTURES_UNDER_DIFFERENT_IDS')
    support = []
    if config.get('require_supporting_data'):
        try:
            support, support_errors = check_support(root, config)
            errors.extend(support_errors)
        except Exception as exc:
            errors.append('SUPPORTING_CHECK_ERROR:'+type(exc).__name__+': '+str(exc))
    unresolved = [r['PDB_ID'] for r in rows if r['reported_state'] == 'UNRESOLVED']
    notes.append({'code': 'STATE_REVIEW_PENDING', 'entries': unresolved,
                  'meaning': '保留原表未解决标签；允许进入第4节核查，但不是允许进行状态选择性设计。'})
    notes.append({'code': 'ALL_ROLES_UNASSIGNED', 'meaning': '未选设计靶标、反靶标或留出家族。'})
    notes.append({'code': 'ORIGINAL_DOWNLOAD_DATE_NOT_RECORDED', 'meaning': '原始51份CIF沿用上游仓库；本次获取时间不能冒充队员最初下载日期。'})
    notes.append({'code': 'ORIGINAL_CIFS_NOT_COMPARED_TO_CURRENT_RCSB_BYTES', 'meaning': '校验和验证本次冻结快照内的一致性，不证明历史下载来源或当前数据库字节完全相同。'})
    status = 'READY_FOR_SECTION4_INITIAL_QC' if not errors else 'BLOCKED_INPUT_ERRORS'
    return {'schema_version': 1, 'status': status, 'errors': errors, 'notes': notes,
            'manifest_entries': len(rows), 'cif_files': len(cif_paths),
            'structures_passed': sum(r['passed'] for r in structures),
            'tmd_entries': sum(r['structure_scope'] == 'TMD' for r in rows),
            'spx_only_entries': sum(r['structure_scope'] == 'SPX-only' for r in rows),
            'family_counts': dict(collections.Counter(r['paper_family'] for r in rows)),
            'unresolved_reported_state_count': len(unresolved),
            'hash_checks': checks, 'structure_checks': structures,
            'supporting_checks': support, 'initial_metadata': metadata,
            'gates': {'section4_initial_inventory_and_qc': not errors,
                      'canonical_residue_mapping_validated': False,
                      'biological_assembly_selection_validated': False,
                      'state_classification_validated': False, 'family_roles_frozen': False,
                      'epitope_selection_authorized_by_this_check': False,
                      'gpu_environment_validated': False, 'candidate_generation_ready': False}}


def write_report(path, report):
    passed = report['status'] == 'READY_FOR_SECTION4_INITIAL_QC'
    lines = ['# 第3节启动验收报告', '',
             '结论：'+('可以开始第4节的结构清点与质量检查。' if passed else '发现输入错误，修复后重检。'), '',
             '这不是第3节全部长期义务完成，也不是第4节结构/表位关卡通过。', '',
             f"- 检查时间：{report['run']['started_at_utc']}",
             f"- 结构表：{report.get('manifest_entries', 0)}条；CIF：{report.get('cif_files', 0)}份；基础解析通过：{report.get('structures_passed', 0)}份。",
             f"- 校验和匹配：{sum(r['match'] for r in report.get('hash_checks', []))}/{len(report.get('hash_checks', []))}。",
             f"- 补充资源检查通过：{sum(r['passed'] for r in report.get('supporting_checks', []))}/{len(report.get('supporting_checks', []))}。",
             f"- 运行时长：{report['run']['runtime_seconds']:.3f}秒；退出状态：{report['run']['exit_code']}。", '',
             '## 验收边界', '',
             'Gemmi是本地结构文件解析库，不是Gemini。入库检查不调用AI服务、不上传数据。',
             '普通CPU上的文件检查通过，不代表GPU环境、模型权重或生成流程已经验证。',
             '所有结构角色仍为UNASSIGNED，统一构象标签与残基映射待第4节核查。',
             'SPX-only条目保留用于机制背景，不直接用于TMD门控或胞外表位设计。', '',
             '## 错误', '']
    lines.extend('- '+x for x in report['errors'])
    if not report['errors']:
        lines.append('无技术入库错误。')
    lines.extend(['', '## 保留事项', ''])
    for item in report.get('notes', []):
        lines.append('- '+item['meaning'])
    lines.extend(['', '## 下一小步', '',
                  '按论文家族核对组装体、构建体、突变、局部缺失和标准序列映射，再决定纳入与排除。不要现在直接把作者的open/closed名称当成统一状态。', ''])
    path.write_text('\n'.join(lines), encoding='utf-8')


def run_check(root, config, config_name):
    root = root.resolve()
    started, start_clock = utc_now(), time.monotonic()
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = root / 'reports/runs' / run_id
    output.mkdir(parents=True, exist_ok=False)
    try:
        report = assess(root, config)
    except Exception as exc:
        report = {'status': 'BLOCKED_INPUT_ERRORS', 'errors': [type(exc).__name__+': '+str(exc)],
                  'notes': [], 'gates': {'section4_initial_inventory_and_qc': False, 'candidate_generation_ready': False}}
    code_files = [root/'run_pipeline.py', root/'requirements.txt', root/'environment.yml',
                  relative_path(root, config_name), *sorted((root/'src').glob('*.py'))]
    code = 0 if report['status'] == 'READY_FOR_SECTION4_INITIAL_QC' else 1
    report['run'] = {'started_at_utc': started, 'finished_at_utc': utc_now(),
                     'runtime_seconds': time.monotonic()-start_clock, 'exit_code': code,
                     'command': f'python run_pipeline.py check --config {config_name}',
                     'python': platform.python_version(), 'gemmi': gemmi.__version__,
                     'os': platform.system(), 'architecture': platform.machine(),
                     'logical_cpu_count': os.cpu_count(), 'gpu': 'NOT_USED_OR_VALIDATED',
                     'cuda': 'NOT_USED_OR_VALIDATED', 'model_weights': 'NOT_USED',
                     'seed': config['seed'], 'random_algorithms_used': config['random_algorithms_used'],
                     'repository': repository_version(root),
                     'implementation_sha256': {p.relative_to(root).as_posix(): sha256(p) for p in code_files}}
    write_json(output/'report.json', report)
    write_report(output/'report.md', report)
    if report.get('structure_checks'):
        checks = [{k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k,v in r.items()}
                  for r in report['structure_checks']]
        fields = sorted({key for row in checks for key in row})
        write_csv(output/'structure_checks.csv', checks, fields)
    if report.get('initial_metadata'):
        write_json(output/'structure_metadata.json', report['initial_metadata'])
    if code == 0:
        from .provenance import export_provenance
        try:
            export_provenance(root, config, output/'data_provenance.csv')
        except Exception as exc:
            code = 1
            report['status'] = 'BLOCKED_INPUT_ERRORS'
            report['errors'].append('PROVENANCE_EXPORT_FAILED:'+type(exc).__name__+': '+str(exc))
            report['gates']['section4_initial_inventory_and_qc'] = False
            report['run']['exit_code'] = code
            write_json(output/'report.json', report)
            write_report(output/'report.md', report)
    log_dir = root/'logs/runs'
    log_dir.mkdir(parents=True, exist_ok=True)
    write_json(log_dir/(run_id+'.json'), {'status': report['status'], 'run': report['run'], 'errors': report['errors']})
    print(report['status'])
    print('报告：'+(output/'report.md').relative_to(root).as_posix())
    for error in report['errors']:
        print('ERROR: '+error)
    return code
