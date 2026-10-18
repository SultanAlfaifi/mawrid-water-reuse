import tempfile
import unittest
from pathlib import Path
from provenance import declare_protocol,check_protocol,begin_first_access


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.code = self.root/'model.py';self.code.write_text('model=1\n')
        self.data = self.root/'sealed.csv';self.data.write_text('Time,x,EVENT\n0,1,0\n')
        self.output = self.root/'evaluation'

    def freeze(self):
        return declare_protocol(self.root,self.output,{'recipe':'fixed'},[self.code],[self.data])

    def test_access_requires_prior_declaration(self):
        with self.assertRaises(FileNotFoundError):begin_first_access(self.root,self.output)
        self.freeze();record = begin_first_access(self.root,self.output)
        self.assertIn('protocol_sha256',record)

    def test_cannot_replace_a_frozen_recipe_or_repeat_first_access(self):
        self.freeze()
        with self.assertRaises(FileExistsError):self.freeze()
        begin_first_access(self.root,self.output)
        with self.assertRaises(FileExistsError):begin_first_access(self.root,self.output)

    def test_code_change_before_access_is_rejected(self):
        self.freeze();self.code.write_text('model=2\n')
        with self.assertRaisesRegex(ValueError,'code changed'):begin_first_access(self.root,self.output)
        self.assertFalse((self.output/'source_access_started.json').exists())

    def test_source_change_is_rejected(self):
        self.freeze();self.data.write_text('Time,x,EVENT\n0,1,1\n')
        with self.assertRaisesRegex(ValueError,'raw_sources changed'):check_protocol(self.root,self.output)

    def test_unchanged_inputs_validate(self):
        frozen = self.freeze()
        self.assertEqual(check_protocol(self.root,self.output),frozen)

if __name__=='__main__':unittest.main()
