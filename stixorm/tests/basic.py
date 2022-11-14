import unittest
from stixorm.module.typedb import TypeDBSink

from config import connection,import_type


class TestDB(unittest.TestCase):

    def test_db_connection(self):
        """
            Test the database initialisation function
        """

        typedb = TypeDBSink(connection, True, import_type)

if __name__ == '__main__':
    unittest.main()