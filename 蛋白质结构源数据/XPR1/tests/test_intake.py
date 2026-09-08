import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from src.checksums import create_baseline, verify_baseline
from src.common import read_manifest, relative_path, write_csv
from src.intake import assess, inspect_structure, manifest_problems, norm_doi
from src.supporting import validate_bytes


CIF = """data_1ABC
_entry.id 1ABC
_struct.title 'test protein'
_citation.id primary
_citation.pdbx_database_id_DOI 10.1234/example
loop_
_entity_poly.entity_id
_entity_poly.type
_entity_poly.pdbx_seq_one_letter_code_can
1 'polypeptide(L)' A
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_entity_id
_atom_site.label_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.occupancy
_atom_site.B_iso_or_equiv
_atom_site.auth_seq_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.auth_atom_id
_atom_site.pdbx_PDB_model_num
ATOM 1 C CA . ALA A 1 1 ? 1.0 2.0 3.0 1.0 10.0 1 ALA A CA 1
"""
ROW = dict(PDB_ID='1ABC', paper_family='T1', structure_scope='TMD', primary_citation='test',
           PMID='1', DOI='https://doi.org/10.1234/example', species='Homo sapiens',
           reported_state='UNRESOLVED', curation_notes='')


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = dict(manifest='data/structure_manifest.csv', raw_structures='data/raw/structures',
                           supporting_raw='data/raw/supporting', supporting_receipts='data/supporting.json',
                           source_receipt='data/source.json', checksums='data/checksums.sha256',
                           expected_entries=1, expected_tmd_entries=1, expected_spx_entries=0,
                           expected_tmd_families=1, expected_spx_families=0,
                           seed=0, random_algorithms_used=False, require_supporting_data=False)
        self.path = self.root/'data/raw/structures/1ABC.cif'
        self.path.parent.mkdir(parents=True)
        self.path.write_text(CIF)
        write_csv(self.root/self.config['manifest'], [ROW], list(ROW))
        (self.root/'data/supporting.json').write_text('{"resources":[]}')
        (self.root/'data/source.json').write_text('{}')

    def test_valid_cif_and_unassigned_state(self):
        result, meta = inspect_structure(self.path, ROW)
        self.assertTrue(result['passed'], result)
        self.assertEqual(result['parsed_atoms'], 1)
        self.assertEqual(meta['reclassified_state'], 'UNRESOLVED')
        self.assertEqual(meta['role'], 'UNASSIGNED')

    def test_filename_and_entry_disagree(self):
        self.path.write_text(CIF.replace('_entry.id 1ABC', '_entry.id 2DEF'))
        result, _ = inspect_structure(self.path, ROW)
        self.assertFalse(result['passed'])

    def test_invalid_syntax_is_failure(self):
        self.path.write_text('<html>not a CIF</html>')
        self.assertFalse(inspect_structure(self.path, ROW)[0]['passed'])

    def test_nonfinite_coordinate_is_failure(self):
        self.path.write_text(CIF.replace('? 1.0 2.0 3.0', '? nan 2.0 3.0'))
        self.assertFalse(inspect_structure(self.path, ROW)[0]['passed'])

    def test_zero_atoms_is_failure(self):
        self.path.write_text('data_1ABC\n_entry.id 1ABC\n')
        self.assertFalse(inspect_structure(self.path, ROW)[0]['passed'])

    def test_wrong_primary_doi_is_failure(self):
        self.path.write_text(CIF.replace('10.1234/example', '10.9999/other'))
        self.assertIn('MANIFEST_MMCIF_PRIMARY_DOI_MISMATCH', inspect_structure(self.path, ROW)[0]['errors'])

    def test_manifest_blank_note_preserved(self):
        rows = read_manifest(self.root/self.config['manifest'])
        self.assertEqual(rows[0]['curation_notes'], '')
        self.assertFalse(manifest_problems(rows, self.config))

    def test_duplicate_manifest_id(self):
        self.assertIn('DUPLICATE_MANIFEST_ID', manifest_problems([ROW, ROW], self.config))

    def test_same_paper_cannot_split_families(self):
        second = {**ROW, 'PDB_ID': '2DEF', 'paper_family': 'T2'}
        self.assertIn('SAME_PRIMARY_DOI_SPLIT_ACROSS_FAMILIES', manifest_problems([ROW, second], self.config))

    def test_family_cannot_combine_different_primary_dois(self):
        second = {**ROW, 'PDB_ID': '2DEF', 'DOI': '10.9999/other'}
        self.assertIn('MULTIPLE_PRIMARY_DOIS_IN_ONE_FAMILY', manifest_problems([ROW, second], self.config))

    def test_baseline_roundtrip(self):
        create_baseline(self.root, self.config)
        checks, errors = verify_baseline(self.root, self.config)
        self.assertFalse(errors)
        self.assertTrue(all(r['match'] for r in checks))

    def test_modified_file_detected_without_rebaseline(self):
        create_baseline(self.root, self.config)
        baseline = (self.root/self.config['checksums']).read_bytes()
        self.path.write_text(CIF+'# changed\n')
        self.assertTrue(verify_baseline(self.root, self.config)[1])
        self.assertEqual(baseline, (self.root/self.config['checksums']).read_bytes())

    def test_baseline_overwrite_refused(self):
        create_baseline(self.root, self.config)
        with self.assertRaises(FileExistsError):
            create_baseline(self.root, self.config)

    def test_new_unlisted_input_detected(self):
        create_baseline(self.root, self.config)
        (self.path.parent/'2DEF.cif').write_text(CIF)
        self.assertTrue(any('UNBASELINED_INPUT' in s for s in verify_baseline(self.root, self.config)[1]))

    def test_missing_input_detected(self):
        create_baseline(self.root, self.config)
        self.path.unlink()
        self.assertTrue(verify_baseline(self.root, self.config)[1])

    def test_duplicate_baseline_line_detected(self):
        create_baseline(self.root, self.config)
        baseline = self.root/self.config['checksums']
        baseline.write_text(baseline.read_text()*2)
        self.assertTrue(any('DUPLICATE_CHECKSUM_PATH' in s for s in verify_baseline(self.root, self.config)[1]))

    def test_path_traversal_and_absolute_path_rejected(self):
        for value in ('../escape', '/tmp/escape'):
            with self.assertRaises(ValueError):
                relative_path(self.root, value)

    def test_reference_fasta_rejects_wrong_accession(self):
        with self.assertRaises(ValueError):
            validate_bytes(b'>sp|BAD|other\nAAA\n', 'reference_fasta', 'Q9UBH6')

    def test_assembly_xxxx_requires_parent_identity(self):
        generated = CIF.replace('1ABC', 'XXXX').encode()
        validate_bytes(gzip.compress(generated), 'assembly', '1ABC', CIF.encode())
        with self.assertRaises(ValueError):
            validate_bytes(gzip.compress(generated), 'assembly', '1ABC')
        with self.assertRaises(ValueError):
            validate_bytes(gzip.compress(generated), 'assembly', '1ABC', CIF.replace('test protein', 'wrong protein').encode())

    def test_validation_report_wrong_entry_rejected(self):
        wrong = b'<ValidationReport><Entry pdbid="2DEF"/></ValidationReport>'
        with self.assertRaises(ValueError):
            validate_bytes(gzip.compress(wrong), 'validation', '1ABC')

    def test_manifest_rejects_missing_column(self):
        (self.root/self.config['manifest']).write_text('PDB_ID\n1ABC\n')
        with self.assertRaises(ValueError):
            read_manifest(self.root/self.config['manifest'])

    def test_doi_normalization(self):
        self.assertEqual(norm_doi('HTTPS://doi.org/10.1234/ABC'), '10.1234/abc')

    def test_initial_gate_never_authorizes_generation(self):
        create_baseline(self.root, self.config)
        report = assess(self.root, self.config)
        self.assertEqual(report['status'], 'READY_FOR_SECTION4_INITIAL_QC', report['errors'])
        self.assertFalse(report['gates']['candidate_generation_ready'])
        self.assertFalse(report['gates']['family_roles_frozen'])

    def test_missing_structure_blocks_gate(self):
        create_baseline(self.root, self.config)
        self.path.unlink()
        self.assertEqual(assess(self.root, self.config)['status'], 'BLOCKED_INPUT_ERRORS')

    def test_unlisted_structure_blocks_gate(self):
        (self.path.parent/'2DEF.cif').write_text(CIF)
        create_baseline(self.root, self.config)
        self.assertEqual(assess(self.root, self.config)['status'], 'BLOCKED_INPUT_ERRORS')

    def test_empty_dataset_cannot_pass(self):
        self.path.unlink()
        create_baseline(self.root, self.config)
        self.assertFalse(assess(self.root, self.config)['gates']['section4_initial_inventory_and_qc'])


if __name__ == '__main__':
    unittest.main()
