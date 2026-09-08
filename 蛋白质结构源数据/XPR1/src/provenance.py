"""Produce a provenance view from frozen source receipts; no fabricated dates."""
import json
import gemmi
from .common import read_manifest, relative_path, sha256, write_csv


def provenance_rows(root, config):
    snapshot = json.loads(relative_path(root, config['source_receipt']).read_text(encoding='utf-8'))
    rows = []
    for item in read_manifest(relative_path(root, config['manifest'])):
        pdb = item['PDB_ID']
        candidates = [p for p in relative_path(root, config['raw_structures']).glob('*.cif') if p.stem.upper() == pdb]
        if len(candidates) != 1:
            raise ValueError('原始结构路径不唯一: '+pdb)
        path = candidates[0]
        block = gemmi.cif.read_file(str(path)).sole_block()
        dates = list(block.find_values('_pdbx_audit_revision_history.revision_date'))
        rows.append({'accession': pdb, 'kind': 'original_mmcif', 'path': path.relative_to(root).as_posix(),
                     'sha256': sha256(path), 'source_url': f"https://raw.githubusercontent.com/66H6/XPR1/{snapshot['base_commit']}/{path.relative_to(root).as_posix()}",
                     'database_lookup_url': f'https://www.rcsb.org/structure/{pdb}',
                     'downloaded_at_utc': 'NOT_RECORDED', 'source_version': 'git:'+snapshot['base_commit'],
                     'embedded_revision_date': max(dates) if dates else 'NOT_RECORDED',
                     'license_or_terms_url': 'https://www.wwpdb.org/about/usage-policies',
                     'use': '第4节结构QC的原始输入；尚未批准用于生成或评分'})
    ledger = json.loads(relative_path(root, config['supporting_receipts']).read_text(encoding='utf-8'))
    for item in ledger['resources']:
        if item['status'] != 'DOWNLOADED':
            continue
        rows.append({'accession': item['accession'], 'kind': item['kind'], 'path': item['path'],
                     'sha256': item['sha256'], 'source_url': item['url'], 'database_lookup_url': item['url'],
                     'downloaded_at_utc': item['downloaded_at_utc'], 'source_version': 'sha256:'+item['sha256'],
                     'embedded_revision_date': 'SEE_RAW_METADATA',
                     'license_or_terms_url': 'https://www.uniprot.org/help/license' if item['kind'].startswith('reference_') else 'https://www.wwpdb.org/about/usage-policies',
                     'use': '第4节初步QC参考；保存不代表完成科学审阅'})
    return rows


def export_provenance(root, config, output):
    rows = provenance_rows(root, config)
    write_csv(output, rows, list(rows[0]))
