import csv
import io
from pathlib import Path
import tempfile
import unittest
import zipfile
import numpy as np
from ponds_data import CHANNELS,IDENTITY,FEATURES_MEMBER,ANNOTATION_MEMBER,read_selected_cohorts,observed_evaluation_view


class PondsAdapterTests(unittest.TestCase):
    def make_archive(self,raw,clean):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        path=Path(temp.name)/'synthetic.zip'
        with zipfile.ZipFile(path,'w') as z:
            for member,rows in [(FEATURES_MEMBER,raw),(ANNOTATION_MEMBER,clean)]:
                stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=IDENTITY+CHANNELS,delimiter='\t')
                writer.writeheader();writer.writerows(rows);z.writestr(member,stream.getvalue())
        return path

    def row(self,slot,cond='10',pond='2D'):
        return {'Pond':pond,'Sonde':'Sonde07','Treatment':'M','Replicate':'1','Phase':'1','Subphase':'1',
            'Time_seq':str(slot/96),**{key:'1' for key in CHANNELS},'SpCond_uScm':cond}

    def test_only_cleaned_conductivity_missingness_becomes_label(self):
        raw=[self.row(0),self.row(1),self.row(2,'NA')]
        cleaned=[self.row(0),self.row(1,'NA'),self.row(2,'NA')]
        cleaned[0]['pH']='9999'
        frame=read_selected_cohorts(self.make_archive(raw,cleaned),[('2D','Sonde07')])[('2D','Sonde07')]
        self.assertEqual(frame.EVENT.tolist(),[False,True,False])
        self.assertEqual(frame.pH.iloc[0],1)
        self.assertFalse(frame.label_available.iloc[2])
        self.assertTrue(frame.loc[2,CHANNELS].isna().all())

    def test_time_gap_is_unavailable_and_original_event_axis_retained(self):
        raw=[self.row(0),self.row(1),self.row(5)]
        clean=[self.row(0),self.row(1,'NA'),self.row(5,'NA')]
        frame=read_selected_cohorts(self.make_archive(raw,clean),[('2D','Sonde07')])[('2D','Sonde07')]
        self.assertEqual(len(frame),6)
        self.assertTrue(frame.loc[2:4,CHANNELS].isna().all().all())
        y,p,slots=observed_evaluation_view(frame,np.array([0,1,-1,-1,-1,0]))
        self.assertEqual(y.tolist(),[False,True,True])
        self.assertEqual(slots.tolist(),[0,1,5])
        self.assertEqual(p.tolist(),[0,1,0])

    def test_identity_misalignment_rejected_before_label_creation(self):
        raw=[self.row(0)];clean=[self.row(1)]
        with self.assertRaisesRegex(ValueError,'identity/order mismatch'):
            read_selected_cohorts(self.make_archive(raw,clean),[('2D','Sonde07')])

    def test_nonselected_measurements_are_never_parsed(self):
        raw=[self.row(0),self.row(1,'DO_NOT_PARSE',pond='reserved')]
        clean=[self.row(0,'NA'),self.row(1,'DO_NOT_PARSE',pond='reserved')]
        frame=read_selected_cohorts(self.make_archive(raw,clean),[('2D','Sonde07')])[('2D','Sonde07')]
        self.assertEqual(len(frame),1)

    def test_duplicate_time_rejected(self):
        raw=[self.row(0),self.row(0)]
        with self.assertRaisesRegex(ValueError,'Nonmonotonic/duplicate'):
            read_selected_cohorts(self.make_archive(raw,raw),[('2D','Sonde07')])

if __name__=='__main__':unittest.main()
