"""Download supplementary public inputs, without overwriting existing raw files."""
import concurrent.futures
import gzip
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET

import gemmi

from .common import read_manifest, relative_path, sha256, utc_now, write_json


def cif_strings(block, tag):
    return [gemmi.cif.as_string(v) for v in block.find_values(tag)]


def resource_plan(root, config):
    root = root.resolve()
    resources = {}
    base = config['supporting_raw']
    structures = {p.stem.upper(): p for p in relative_path(root, config['raw_structures']).glob('*.cif')}
    def add(path, url, kind, accession, parent_path=None):
        resources[path] = {'path': path, 'url': url, 'kind': kind, 'accession': accession}
        if parent_path:
            resources[path]['parent_path'] = parent_path
    for row in read_manifest(relative_path(root, config['manifest'])):
        pdb = row['PDB_ID']
        if not re.fullmatch(r'[0-9][A-Z0-9]{3}', pdb):
            raise ValueError('非法PDB编号: '+pdb)
        b = gemmi.cif.read_file(str(structures[pdb])).sole_block()
        for assembly in cif_strings(b, '_pdbx_struct_assembly.id'):
            if not assembly.isdigit():
                raise ValueError('非法组装体编号')
            add(f'{base}/assemblies/{pdb}-assembly{assembly}.cif.gz',
                f'https://files.rcsb.org/download/{pdb}-assembly{assembly}.cif.gz', 'assembly', pdb,
                structures[pdb].relative_to(root).as_posix())
        low = pdb.lower()
        add(f'{base}/validation/{pdb}_validation.xml.gz',
            f'https://files.rcsb.org/pub/pdb/validation_reports/{low[1:3]}/{low}/{low}_validation.xml.gz', 'validation', pdb)
        for dbid, dbname in zip(cif_strings(b, '_pdbx_database_related.db_id'), cif_strings(b, '_pdbx_database_related.db_name')):
            if dbname.upper() == 'EMDB' and re.fullmatch(r'EMD-[0-9]+', dbid):
                add(f'{base}/emdb/{dbid}.json', f'https://www.ebi.ac.uk/emdb/api/entry/{dbid}', 'emdb_metadata', dbid)
    add(f'{base}/uniprot/Q9UBH6.fasta', 'https://rest.uniprot.org/uniprotkb/Q9UBH6.fasta', 'reference_fasta', 'Q9UBH6')
    add(f'{base}/uniprot/Q9UBH6.json', 'https://rest.uniprot.org/uniprotkb/Q9UBH6.json', 'reference_metadata', 'Q9UBH6')
    return sorted(resources.values(), key=lambda r: r['path'])


def validate_bytes(raw, kind, accession, parent_raw=None):
    if kind == 'assembly':
        block = gemmi.cif.read_string(gzip.decompress(raw).decode('utf-8')).sole_block()
        entry = gemmi.cif.as_string(block.find_value('_entry.id') or '?').upper()
        if entry not in (accession.upper(), 'XXXX') or not list(block.find_values('_atom_site.id')):
            raise ValueError('组装体编号错误或无原子坐标')
        # RCSB's generated assembly files can use data_XXXX / _entry.id XXXX.
        # Never pretend this is an independently matching accession: require
        # the official URL receipt AND matching parent identity metadata.
        if parent_raw is None:
            raise ValueError('组装体必须与原始条目的标题、聚合物序列和主文献交叉核对')
        parent = gemmi.cif.read_string(parent_raw.decode('utf-8')).sole_block()
        for tag in ('_struct.title', '_entity_poly.pdbx_seq_one_letter_code_can'):
            observed = sorted(re.sub(r'\s+', '', s) for s in cif_strings(block, tag))
            expected = sorted(re.sub(r'\s+', '', s) for s in cif_strings(parent, tag))
            if not expected or observed != expected:
                raise ValueError('组装体与原条目不对应: '+tag)
        observed_dois = sorted(s.lower() for s in cif_strings(block, '_citation.pdbx_database_id_DOI') if s)
        parent_dois = sorted(s.lower() for s in cif_strings(parent, '_citation.pdbx_database_id_DOI') if s)
        if not parent_dois or observed_dois != parent_dois:
            raise ValueError('组装体与原条目文献不对应')
        structure = gemmi.make_structure_from_block(block)
        if not len(structure):
            raise ValueError('组装体不能读为结构')
    elif kind == 'validation':
        root = ET.fromstring(gzip.decompress(raw))
        if not root.findall('.//Entry'):
            raise ValueError('不是包含Entry的wwPDB验证报告')
        ids = {e.attrib.get('pdbid', '').upper() for e in root.findall('.//Entry')}
        if accession.upper() not in ids:
            raise ValueError('验证报告PDB编号不对应')
    elif kind in ('emdb_metadata', 'reference_metadata'):
        data = json.loads(raw)
        if not isinstance(data, dict) or not data:
            raise ValueError('元数据为空或不是JSON对象')
        if kind == 'reference_metadata' and data.get('primaryAccession') != accession:
            raise ValueError('UniProt编号不对应')
        if kind == 'emdb_metadata' and accession not in json.dumps(data):
            raise ValueError('EMDB编号不对应')
    elif kind == 'reference_fasta':
        lines = raw.decode('utf-8').splitlines()
        if not lines or not lines[0].startswith('>sp|Q9UBH6|') or not re.fullmatch('[A-Z]+', ''.join(lines[1:])):
            raise ValueError('不是Q9UBH6 FASTA序列')


def fetch_one(root, item, old):
    path = relative_path(root, item['path'])
    parent_raw = relative_path(root, item['parent_path']).read_bytes() if item.get('parent_path') else None
    if path.exists():
        if not old or old.get('status') != 'DOWNLOADED' or old.get('sha256') != sha256(path):
            return {**item, 'status': 'ERROR', 'error': '已有文件无可信下载记录或校验和已变化；未覆盖'}
        try:
            validate_bytes(path.read_bytes(), item['kind'], item['accession'], parent_raw)
            return old
        except Exception as exc:
            return {**item, 'status': 'ERROR', 'error': str(exc)}
    error = ''
    for attempt in range(2):
        try:
            request = urllib.request.Request(item['url'], headers={'User-Agent': 'XPR1-reproducible-intake/1.0'})
            with urllib.request.urlopen(request, timeout=40) as response:
                raw = response.read(25 * 1024 * 1024 + 1)
                if len(raw) > 25 * 1024 * 1024:
                    raise ValueError('单个补充文件超过25MiB限制；本脚本不下载密度图体数据')
                meta = {'final_url': response.url, 'last_modified': response.headers.get('Last-Modified', 'NOT_PROVIDED')}
            validate_bytes(raw, item['kind'], item['accession'], parent_raw)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as handle:
                handle.write(raw)
            return {**item, **meta, 'status': 'DOWNLOADED', 'downloaded_at_utc': utc_now(),
                    'bytes': len(raw), 'sha256': sha256(path)}
        except Exception as exc:
            error = type(exc).__name__ + ': ' + str(exc)
            if attempt == 0:
                time.sleep(1)
    return {**item, 'status': 'ERROR', 'error': error, 'attempted_at_utc': utc_now()}


def fetch_all(root, config):
    root = root.resolve()
    ledger = relative_path(root, config['supporting_receipts'])
    old = json.loads(ledger.read_text()) if ledger.exists() else {'resources': []}
    saved = {r['path']: r for r in old['resources']}
    plan = resource_plan(root, config)
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch_one, root, item, saved.get(item['path'])) for item in plan]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results[result['path']] = result
            saved[result['path']] = result
            write_json(ledger, {'updated_at_utc': utc_now(), 'resources': sorted(saved.values(), key=lambda r: r['path'])})
            print(f"[{len(results)}/{len(plan)}] {result['status']} {result['path']}", flush=True)
    errors = [r for r in results.values() if r['status'] != 'DOWNLOADED']
    print(json.dumps({'planned': len(plan), 'downloaded': len(plan)-len(errors), 'errors': errors}, ensure_ascii=False))
    return 1 if errors else 0
