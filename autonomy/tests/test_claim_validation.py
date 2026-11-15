import contextlib
import io
import json
import unittest
from unittest.mock import patch

from autonomy import intake
from autonomy.claim_validation import ClaimValidationError, validate_claims
from autonomy.tests import test_intake


class ClaimTests(unittest.TestCase):
    setUp = test_intake.IntakeTests.setUp
    submit = test_intake.IntakeTests.submit
    answer = test_intake.IntakeTests.answer

    def fixture(self):
        folder, claims = self.answer()
        return intake.load(self.spec['id']), folder, claims, (folder / 'response.md').read_text(encoding='utf-8')

    def errors(self, card, claims, text):
        with self.assertRaises(ClaimValidationError) as exc:
            validate_claims(card, claims, text)
        return exc.exception.diagnostics['errors']

    def test_two_bad_claims(self):
        card, _, claims, text = self.fixture()
        claims[0].update(id='C02', quote='absent')
        claims[1].update(id='C03', source_url='https://missing')
        errors = self.errors(card, claims, text + ' C02 C03 https://missing')
        self.assertEqual([e['claim_id'] for e in errors], ['C02', 'C03'])
        self.assertIn('quote_missing', errors[0]['codes'])
        self.assertIn('url_missing_in_evidence', errors[1]['codes'])

    def test_whitespace(self):
        card, _, claims, text = self.fixture()
        claims[0]['quote'] = 'A\u00a0streaming\nmodel.'
        self.assertEqual(validate_claims(card, claims, text)['supported_claims'], 2)

    def test_url_not_canonicalized(self):
        card, _, claims, text = self.fixture()
        claims[0]['source_url'] += '/'
        self.assertIn('url_missing_in_evidence', self.errors(card, claims, text)[0]['codes'])

    def test_invalid_entry(self):
        card, _, _, text = self.fixture()
        self.assertIn('invalid_claim', self.errors(card, [42], text)[0]['codes'])

    def test_duplicate_unverified(self):
        card, _, claims, text = self.fixture()
        claims[1].update(id='C1', status='unverified', claim='')
        codes = self.errors(card, claims, text)[0]['codes']
        self.assertIn('duplicate_id', codes)
        self.assertIn('invalid_claim', codes)

    def test_unverified_id_used(self):
        card, _, claims, text = self.fixture()
        claims[0].update(id='unused', status='unverified')
        self.assertIn('id_missing_in_response', self.errors(card, claims, text)[0]['codes'])

    def test_evidence_invalid_json(self):
        card, _, claims, text = self.fixture()
        intake.root(self.spec['id']).joinpath('sources-0.md.json').write_text('{')
        self.assertIn('evidence_invalid_json', self.errors(card, claims, text)[0]['codes'])

    def test_evidence_invalid_schema(self):
        card, _, claims, text = self.fixture()
        intake.root(self.spec['id']).joinpath('sources-0.md.json').write_text('{"sources":[{}]}')
        self.assertIn('evidence_invalid_schema', self.errors(card, claims, text)[0]['codes'])

    def test_outside_never_read(self):
        card, _, claims, text = self.fixture()
        claims[0]['evidence_file'] = '.env'
        with patch('pathlib.Path.read_text', side_effect=AssertionError('read forbidden')):
            errors = self.errors(card, [claims[0]], text)
        self.assertIn('evidence_outside_allowed_set', errors[0]['codes'])

    def test_count_and_limitation(self):
        card, _, claims, text = self.fixture()
        claims[1]['status'] = 'unverified'
        self.assertEqual(validate_claims(card, claims, text), {'supported_claims': 1})
        claims[0]['quote'] = 'not present'
        with self.assertRaises(ClaimValidationError) as exc:
            validate_claims(card, claims, text)
        self.assertEqual(exc.exception.diagnostics['limitation'], 'literal evidence only, not semantic support')

    def test_cli_json(self):
        _, folder, claims, _ = self.fixture()
        claims[0]['quote'] = 'not present'
        (folder / 'claims.json').write_text(json.dumps(claims), encoding='utf-8')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = intake.main(['check', self.spec['id']])
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(out.getvalue())['errors'][0]['claim_id'], 'C1')
        self.assertNotIn('Traceback', out.getvalue())

    def test_30_bounded(self):
        card, _, claims, text = self.fixture()
        rows = [dict(claims[0], id=f'C{i:02}', source_url='x' * 20000, evidence_file='y' * 20000)
                for i in range(30)]
        with self.assertRaises(ClaimValidationError) as exc:
            validate_claims(card, rows, text)
        parsed = json.loads(str(exc.exception))
        self.assertLessEqual(len(str(exc.exception)), 40000)
        self.assertEqual(len(parsed['errors']), 30)
        self.assertEqual([e['claim_id'] for e in parsed['errors']], [r['id'] for r in rows])
        self.assertTrue(all(e['metadata_truncated'] for e in parsed['errors']))

    def test_partial_still_fails(self):
        _, folder, claims, _ = self.fixture()
        claims[0]['quote'] = 'not present'
        (folder / 'claims.json').write_text(json.dumps(claims), encoding='utf-8')
        decision = json.loads((folder / 'decision.json').read_text(encoding='utf-8'))
        decision['completion_status'] = 'partial'
        (folder / 'decision.json').write_text(json.dumps(decision), encoding='utf-8')
        with self.assertRaises(ClaimValidationError):
            intake.check_response(self.spec['id'])

    def test_unhashable_fields(self):
        card, _, claims, text = self.fixture()
        claims[0].update(id=[], status=[], evidence_file=[])
        self.assertIn('invalid_claim', self.errors(card, claims, text)[0]['codes'])

    def test_quote_size_and_typed_acceptance(self):
        card, _, claims, text = self.fixture()
        claims[0]['quote'] = 'x' * 4001
        self.assertIn('quote_too_large', self.errors(card, claims, text)[0]['codes'])
        self.assertIn({'mentor_response': self.spec['id']}, intake.build_plan(card)[-1]['acceptance'])
