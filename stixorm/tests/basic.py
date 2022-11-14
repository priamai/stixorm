import unittest
import logging

from stixorm.module.typedb import TypeDBSink
from stix2 import Indicator
from config import connection,import_type


class TestDB(unittest.TestCase):
    '''
    This unit test is very simple, we have another repository for full OASIS testing
    '''
    logger = logging.getLogger(__name__)
    logging.basicConfig(format='%(asctime)s %(module)s %(levelname)s: %(message)s',
                        datefmt='%m/%d/%Y %I:%M:%S %p', level=logging.INFO)
    @classmethod
    def setUpClass(cls):
        cls.logger.info(f'Connecting and resetting DB')
        cls._typedb = TypeDBSink(connection,clear=True,import_type=import_type)

    def test_db_connection(self):
        """
            Test the database initialisation function
        """
        markings = self._typedb.get_stix_ids(tlp_filter=False)

        self.assertEqual(len(markings), 4, "TLP markings should be loaded")
        self.logger.info(f'Total markings {len(markings)}')

    def test_malware_ioc(self):


        indicator = Indicator(name="File hash for malware variant",
                              pattern="[file:hashes.md5 = 'd41d8cd98f00b204e9800998ecf8427e']",
                              pattern_type="stix")

        self.logger.info(indicator.serialize(pretty=True))

        self._typedb.add([indicator])

        stix_ids = self._typedb.get_stix_ids()

        self.assertTrue(indicator.id in stix_ids,"Indicator was not inserted")

    @classmethod
    def tearDownClass(cls):
        stix_ids = cls._typedb.get_stix_ids()
        cls.logger.info(f'Total objects {len(stix_ids)}')
        cls._typedb.delete(stix_ids)

if __name__ == '__main__':
    unittest.main()