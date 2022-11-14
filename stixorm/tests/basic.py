import unittest
import logging

from stixorm.module.typedb import TypeDBSink

from config import connection,import_type


class TestDB(unittest.TestCase):
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

    @classmethod
    def tearDownClass(cls):
        stix_ids = cls._typedb.get_stix_ids()
        cls.logger.info(f'Total objects {len(stix_ids)}')
        cls._typedb.delete(stix_ids)

if __name__ == '__main__':
    unittest.main()