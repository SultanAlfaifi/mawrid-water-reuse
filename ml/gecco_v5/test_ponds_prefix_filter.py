"""Synthetic-only tests: reserved measurement suffixes must stay opaque."""
from pathlib import Path
import tempfile
import unittest
import zipfile

from ponds_data import (CHANNELS, IDENTITY, FEATURES_MEMBER, ANNOTATION_MEMBER,
                        read_selected_cohorts)


class PondsPrefixFilterTests(unittest.TestCase):
    def archive(self, raw_lines, clean_lines):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "synthetic.zip"
        header = ("\t".join(IDENTITY + CHANNELS) + "\n").encode()
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(FEATURES_MEMBER, header + b"".join(raw_lines))
            archive.writestr(ANNOTATION_MEMBER, header + b"".join(clean_lines))
        return path

    def row(self, *, pond="2D", sonde="Sonde07", treatment="M", phase="1",
            time="0", conductivity="10", opaque_suffix=None):
        identity = [pond, sonde, treatment, "1", phase, "1", time]
        fields = ["1"] * len(CHANNELS)
        fields[CHANNELS.index("SpCond_uScm")] = conductivity
        suffix = "\t".join(fields).encode() if opaque_suffix is None else opaque_suffix
        return "\t".join(identity).encode() + b"\t" + suffix + b"\n"

    def read(self, path):
        return read_selected_cohorts(path, [("2D", "Sonde07")])[("2D", "Sonde07")]

    def test_unselected_suffixes_are_not_decoded_or_split_into_fields(self):
        # Invalid UTF8 and an invalid sensor-field count must remain opaque for
        # each exclusion route, in BOTH measurement and annotation streams.
        excluded = [self.row(pond="reserved", opaque_suffix=b"\xff"),
                    self.row(treatment="D", opaque_suffix=b"\xff"),
                    self.row(phase="2", opaque_suffix=b"\xff")]
        raw = excluded + [self.row(time=str(2 / 96))]
        clean = excluded + [self.row(time=str(2 / 96), conductivity="NA")]
        frame = self.read(self.archive(raw, clean))
        self.assertEqual(frame.source_row.tolist(), [3])
        self.assertEqual(frame.slot.tolist(), [2])
        self.assertEqual(frame.EVENT.tolist(), [True])

    def test_reserved_identity_alignment_still_required(self):
        raw = [self.row(pond="reserved", opaque_suffix=b"\xff"), self.row()]
        clean = [self.row(pond="reserved", sonde="different", opaque_suffix=b"\xff"), self.row()]
        with self.assertRaisesRegex(ValueError, "identity/order mismatch"):
            self.read(self.archive(raw, clean))

    def test_quoted_identity_is_rejected_before_sensor_decoding(self):
        row = self.row(pond='"reserved"', opaque_suffix=b"\xff")
        with self.assertRaisesRegex(ValueError, "quoted"):
            self.read(self.archive([row], [row]))

    def test_nonfinite_original_target_remains_unavailable(self):
        raw = [self.row(conductivity="inf")]
        clean = [self.row(conductivity="NA")]
        frame = self.read(self.archive(raw, clean))
        self.assertFalse(frame.label_available.iloc[0])
        self.assertFalse(frame.EVENT.iloc[0])
        self.assertTrue(frame.loc[0, CHANNELS].isna().all())


if __name__ == "__main__":
    unittest.main()
