"""Synthetic-only contract checks; no publisher archive is opened."""
import tempfile
import unittest
from pathlib import Path
import zipfile

from ponds_data import ANNOTATION_MEMBER, CHANNELS, FEATURES_MEMBER, IDENTITY
from ponds_reserved_data import read_reserved_cohorts


KEY = ('1A', 'Sonde01', 'D', '1', '2')


def row(key=KEY, slot=26016, tail=None, subphase='9'):
    prefix = list(key) + [subphase, f'{slot / 96:.7f}']
    return '\t'.join(prefix).encode() + b'\t' + (tail if tail is not None else b'1\t2\t3\t4\t5\t6\t7\t8') + b'\n'


class ReservedAdapterTests(unittest.TestCase):
    def read(self, original, cleaned=None, keys=None):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / 'synthetic.zip'
            header = ('\t'.join(IDENTITY + CHANNELS) + '\n').encode()
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr(FEATURES_MEMBER, header + b''.join(original))
                z.writestr(ANNOTATION_MEMBER, header + b''.join(original if cleaned is None else cleaned))
            return read_reserved_cohorts(archive, [KEY] if keys is None else keys)

    def test_nonzero_phase_grid_and_original_source_row(self):
        omitted = row(key=('2D', 'Sonde07', 'M', '1', '1'), tail=b'\xff')
        result = self.read([omitted, row(), row(slot=26018)])[KEY]
        self.assertEqual(result.slot.tolist(), [26016, 26017, 26018])
        self.assertEqual(result.source_row.tolist(), [1, -1, 2])
        self.assertEqual(result.row_observed.tolist(), [True, False, True])
        self.assertTrue(result.loc[1, CHANNELS].isna().all())
        self.assertEqual(result.Time_seq.tolist(), [s / 96 for s in [26016, 26017, 26018]])

    def test_each_of_five_identity_fields_filters_before_suffix_decode(self):
        wrong = []
        for index in range(5):
            key = list(KEY)
            key[index] += 'other'
            wrong.append(row(key=tuple(key), tail=b'\xff'))
        result = self.read(wrong + [row()])[KEY]
        self.assertEqual(result.source_row.tolist(), [5])

    def test_only_selected_cleaned_conductivity_supplies_annotation(self):
        cleaned = row(tail=b'bad\tbad\tbad\tbad\tbad\tbad\tNA\tbad')
        result = self.read([row()], [cleaned])[KEY]
        self.assertEqual(result.EVENT.tolist(), [True])
        self.assertEqual(result.loc[0, CHANNELS].tolist(), [1, 2, 3, 4, 5, 6, 7, 8])

    def test_unknown_target_makes_all_features_unavailable(self):
        for value in [b'NA', b'inf', b'-inf']:
            original = row(tail=b'1\t2\t3\t4\t5\t6\t' + value + b'\t8')
            result = self.read([original])[KEY]
            self.assertFalse(result.label_available.iloc[0])
            self.assertFalse(result.EVENT.iloc[0])
            self.assertTrue(result[CHANNELS].isna().all().all())

    def test_consumed_primary_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Consumed'):
            self.read([row()], keys=[('2D', 'Sonde07', 'M', '1', '1')])

    def test_unselected_identity_alignment_still_checked(self):
        a = row(key=('9A', 'Sonde99', 'C', '1', '3'), tail=b'\xff')
        b = row(key=('9B', 'Sonde99', 'C', '1', '3'), tail=b'\xff')
        with self.assertRaisesRegex(ValueError, 'identity/order mismatch'):
            self.read([a, row()], [b, row()])

    def test_phases_are_separate_and_declared_order_is_preserved(self):
        other = ('1A', 'Sonde01', 'D', '1', '3')
        result = self.read([row(), row(key=other, slot=44640)], keys=[other, KEY])
        self.assertEqual(list(result), [other, KEY])
        self.assertEqual(result[other].slot.tolist(), [44640])
        self.assertEqual(result[KEY].slot.tolist(), [26016])

    def test_duplicate_and_reversed_time_fail(self):
        for slots in [(26016, 26016), (26017, 26016)]:
            with self.assertRaisesRegex(ValueError, 'Nonmonotonic/duplicate'):
                self.read([row(slot=s) for s in slots])

    def test_missing_extra_or_misaligned_annotations_fail(self):
        for cleaned in [[], [row(), row(slot=26017)], [row(subphase='10')]]:
            with self.assertRaises(ValueError):
                self.read([row()], cleaned)

    def test_invalid_cohort_requests_fail(self):
        for keys in [[], [KEY, KEY], [('1A',)], [('1A', 'Sonde01', 'D', 1, '2')]]:
            with self.assertRaises(ValueError):
                self.read([row()], keys=keys)


if __name__ == '__main__':
    unittest.main()
