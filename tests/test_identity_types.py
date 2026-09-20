import copy
import tempfile
import unittest
from pathlib import Path
from shardlab.core import Store, commit_args

class IdentityTypes(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'db.sqlite',clock=lambda:1000.)
        self.store.submit('1',[{'text':'a valid training sample'}])

    def test_boolean_or_float_fencing_identity_is_rejected_without_writing(self):
        args=commit_args(self.store.claim('1','worker')['task'])
        for key,value in [('token',True),('token',1.),('shard',False),('shard',0.)]:
            with self.subTest(key=key,value=value):
                bad=copy.deepcopy(args);bad[key]=value
                with self.assertRaises(ValueError):self.store.commit(**bad)
                self.assertEqual(self.store.status('1')['states'],{'leased':1})
        self.assertFalse(self.store.commit(**args)['replayed'])

    def test_invalid_identity_never_reaches_sqlite(self):
        for value in [1,True,[],{},None,'','x'*101]:
            for method in (self.store.status,self.store.publish):
                with self.subTest(value=value,method=method.__name__):
                    with self.assertRaises(ValueError):method(value)
        for value in [True,1.,-1,2**80]:
            with self.subTest(shard=value):
                with self.assertRaises(ValueError):self.store.renew('1',value,1,'worker')

    def test_boolean_lease_is_not_a_duration(self):
        with self.assertRaises(ValueError):self.store.claim('1','worker',True)
