"""Python STIX2 TypeDB Source/Sink"""

import json
from pathlib import Path
from typedb.client import *

from .import_stix_to_typeql import raw_stix2_to_typeql, stix2_to_match_insert
from .delete_stix_to_typeql import delete_stix_object, add_delete_layers
from .import_stix_utilities import get_embedded_match
from .export_intermediate_to_stix import convert_ans_to_stix
from .initialise import setup_database, load_schema, sort_layers, load_markings, check_stix_ids

from stix2 import v21
from stix2.base import _STIXBase
from stix2.datastore import (
    DataSink, DataSource, )
from stix2.datastore.filters import FilterSet
from stix2.parsing import parse

import logging
logger = logging.getLogger(__name__)

marking = ["marking-definition--613f2e26-407d-48c7-9eca-b8e91df99dc9",
           "marking-definition--34098fce-860f-48ae-8e50-ebd3cc5e41da",
           "marking-definition--f88d31f6-486f-44da-b317-01333bde0b82",
           "marking-definition--5e57c739-391a-4eb3-b6be-7d15ca92d5ed"]


class TypeDBSink(DataSink):
    """Interface for adding/pushing STIX objects to TypeDB.

    Can be paired with a TypeDBSource, together as the two
    components of a TypeDBStore.

    Args:
        - connection is a dict, containing:
            - uri (str): URI to TypeDB.
            - port (int): Port to TypeDB.
            - db (str): Name of TypeDB database.
            - user (str): Username for TypeDB, if cluster, otherwise None
            - password (str): Password for TypeDB, if cluster, otherwise None
        - clear (bool): If True, clear the TypeDB before adding objects.
        - import_type (str): It forces the parser to use either the stix2.1, or mitre att&ck

    """

    def __init__(self, connection, clear=False, import_type=None, **kwargs):
        super(TypeDBSink, self).__init__()

        self._stix_connection = connection
        self.uri = connection["uri"]
        self.port = connection["port"]
        self.database = connection["database"]
        self.user = connection["user"]
        self.password = connection["password"]
        self.clear = clear
        self.thisfile = Path(__file__).resolve()
        self.schema_folder = Path.joinpath(self.thisfile.parent.parent, "schema")
        if import_type is None:
            import_type = {"STIX21": True, "CVE": False, "identity": False, "location": False, "rules": False}
            import_type.update({"ATT&CK": False, "ATT&CK_Versions": ["12.0"],
                                "ATT&CK_Domains": ["enterprise-attack", "mobile-attack", "ics-attack"], "CACAO": False})
        self.import_type = import_type
        logger.debug(f'Connection {self._stix_connection}')
        logger.debug(f'Import Type {import_type}')

        try:
            # 1. Setup database
            setup_database(self._stix_connection, clear)

            # 2. Load the Stix schema
            if clear:
                load_schema(connection, self.schema_folder/"cti-schema-v2.tql", "Stix 2.1 Schema ")
                self.loaded = load_markings(connection)
                logger.debug("moving past load Stix schema")
            # 3. Check for Stix Rules
            if clear and import_type["rules"]:
                logger.debug("rules")
                load_schema(connection, self.schema_folder/"cti-rules.tql", "Stix 2.1 Rules")
                logger.debug("moving past load rules")
            # 3. Load the Stix Markings
            if clear and import_type["ATT&CK"]:
                logger.debug("attack")
                load_schema(connection, self.schema_folder/"cti-schema-v2.tql", "Stix 2.1 Schema ")
                logger.debug("moving past load schema")
            # 3. Check for Stix Rules
            if clear and import_type["CACAO"]:
                logger.debug("cacao")
                load_schema(connection, self.schema_folder/"cti-rules.tql", "Stix 2.1 Rules")
                logger.debug("moving past load schema")

        except Exception as e:
            logger.error(f'Initialise TypeDB Error: {e}')
            raise

    @property
    def stix_connection(self):
        return self._stix_connection

    def get_stix_ids(self,tlp_filter=True):
        """ Get all the stix-ids in a database, should be moved to typedb file

        Returns:
            id_list : list of the stix-ids in the database
        """
        get_ids_tql = 'match $ids isa stix-id;'
        g_uri = self.uri + ':' + self.port
        id_list = []
        with TypeDB.core_client(g_uri) as client:
            with client.session(self.database, SessionType.DATA) as session:
                with session.transaction(TransactionType.READ) as read_transaction:
                    answer_iterator = read_transaction.query().match(get_ids_tql)
                    ids = [ans.get("ids") for ans in answer_iterator]
                    for sid_obj in ids:
                        sid = sid_obj.get_value()
                        if sid in marking and tlp_filter:
                            continue
                        else:
                            id_list.append(sid)
        return id_list

    def delete(self, stixid_list):
        """ Delete a list of STIX objects from the typedb server. Must include all related objects and relations

        Args:
            stixid_list (): The list of Stix-id's of the object's to delete
        """
        clean = 'match $a isa attribute; not { $b isa thing; $b has $a;}; delete $a isa attribute;'
        cleandict = {'delete': clean}
        cleanup = [cleandict]

        connection = {'uri': self.uri, 'port': self.port, 'database': self.database, 'user': self.user,
                      'password': self.password}

        try:
            typedb = TypeDBSource(connection, "STIX21")
            layers = []
            indexes = []
            missing = []

            for stixid in stixid_list:
                local_obj = typedb.get(stixid)
                dep_match, dep_insert, indep_ql, core_ql, dep_obj = raw_stix2_to_typeql(local_obj, self.import_type)
                # TODO: Brett check here there is a bug
                del_match, del_tql = delete_stix_object(local_obj, dep_match, dep_insert, indep_ql, core_ql,"STIX21")
                logger.debug(' ---------------------------Delete Object----------------------')
                logger.debug(f'dep_match -> {dep_match}\n dep_insert -> {dep_insert}')
                logger.debug(f'indep_ql -> {indep_ql}\n dep_obj -> {dep_obj}')
                logger.debug("=========================== delete typeql below ====================================")
                logger.debug(f'del_match -> {del_match}\n del_tql -> {del_tql}')
                if del_match == '' and del_tql == '':
                    continue
                dep_obj["delete"] = del_match + '\n' + del_tql
                if len(layers) == 0:
                    missing = dep_obj['dep_list']
                    indexes.append(dep_obj['id'])
                    layers.append(dep_obj)
                else:
                    layers, indexes, missing = add_delete_layers(layers, dep_obj, indexes, missing)
                logger.debug(' ---------------------------Object Delete----------------------')

            logger.debug("=========================== dependency indexes ====================================")
            logger.debug(f'indexes -> {indexes}')
            logger.debug("=========================== dependency indexes ====================================")
            ordered = layers + cleanup + cleanup
            for layer in ordered:
                logger.debug("666666666666666 delete 6666666666666666666666666666666666")
                logger.debug(f'del query -> {layer["delete"]}')
            logger.debug(f'\nordered -> {ordered}')
            with TypeDB.core_client(connection["uri"] + ":" + connection["port"]) as client:
                with client.session(connection["database"], SessionType.DATA) as session:
                    for layer in ordered:
                        with session.transaction(TransactionType.WRITE) as write_transaction:
                            logger.debug("77777777777777777 delete 777777777777777777777777777777777")
                            logger.debug(f'del query -> {layer["delete"]}')
                            query_future = write_transaction.query().delete(layer["delete"])
                            logger.debug(f'typedb delete response ->\n{query_future.get()}')
                            logger.debug("7777777777777777777777777777777777777777777777777777777777")
                            write_transaction.commit()
                    logger.debug(' ---------------------------Object Delete----------------------')

        except Exception as e:
            logger.error(f'Stix Object Deletion Error: {e}')
            if 'dep_match' in locals(): logger.error(f'dep_match -> {dep_match}')
            if 'dep_insert' in locals(): logger.error(f'dep_insert -> {dep_insert}')
            if 'indep_ql' in locals(): logger.error(f'indep_ql -> {indep_ql}')
            if 'core_ql' in locals(): logger.error(f'core_ql -> {core_ql}')
            raise

    def add(self, stix_data=None):
        """Add STIX objects to the typedb server.
            1. Gather objects into a list
            2. For each object
                a. get raw stix to tql
                b. add object to an ordered list
                c. return the ordered list
            3. Add each object in the ordered list
        Args:
            stix_data (STIX object OR Bundle OR dict OR list): valid STIX 2.1 content
                in a STIX object (or list of), dict (or list of), or a STIX 2.1
                json encoded string.
            import_type (dict): It forces the parser to use either the stix2.1,
                or the mitre attack typeql description. Values can be either:
                        - "STIX21"
                        - "mitre"
        Note:
            ``stix_data`` can be a Bundle object, but each object in it will be
            saved separately; you will be able to retrieve any of the objects
            the Bundle contained, but not the Bundle itself.
        """
        layers = []
        indexes = []
        missing = []
        cyclical = []
        try:
            # 1. gather objects into a list
            obj_list = self._gather_objects(stix_data)
            logger.debug(f'\n\n object list is  {obj_list}')
            # 2. for stix ibject in list
            for stix_dict in obj_list:
                # 3. Parse stix objects and get typeql and dependency
                stix_obj = parse(stix_dict)
                dep_match, dep_insert, indep_ql, core_ql, dep_obj = raw_stix2_to_typeql(stix_obj, self.import_type)
                dep_obj["dep_match"] = dep_match
                dep_obj["dep_insert"] = dep_insert
                dep_obj["indep_ql"] = indep_ql
                dep_obj["core_ql"] = core_ql
                # 4. Order the list of stix objects, and collect errors
                logger.debug(f'\ndep object {dep_obj}')
                if len(layers) == 0:
                    # 4a. For the first record to order
                    missing = dep_obj['dep_list']
                    indexes.append(dep_obj['id'])
                    layers.append(dep_obj)
                else:
                    # 4b. Add up and return the layers, indexes, missing and cyclical lists
                    add = 'add'
                    layers, indexes, missing, cyclical = sort_layers(layers, cyclical, indexes, missing, dep_obj, add)
                    logger.debug(f'\npast sort {layers}')

            # 5. If missing then check to see if the records are in the database, or raise an error
            mset = set(missing)
            logger.debug(f'missing stuff {len(missing)} - {len(set(missing))}')
            logger.debug(f'mset {mset}')
            if mset:
                list_in_database = check_stix_ids(list(mset), self._stix_connection)
                real_missing = list(mset.difference(set(list_in_database)))
                logger.debug(f'\nmissing {missing}\n\n loaded {real_missing}')
                if real_missing:
                    raise Exception(f'Error: Missing Stix deopendencies, id={real_missing}')
            # 6. If cyclicla, just raise an error for the moment
            if cyclical:
                raise Exception(f'Error: Cyclical Stix Dependencies, id={cyclical}')
            # 7. Else go ahead and add the records to the database
            url = self.uri + ":" + self.port
            logger.debug(f'url {url}')
            with TypeDB.core_client(url) as client:
                with client.session(self.database, SessionType.DATA) as session:
                    logger.debug(
                        f'------------------------------------ TypeDB Sink Session Start --------------------------------------------')
                    for lay in layers:
                        logger.debug(
                            f'------------------------------------ Load Object --------------------------------------------')
                        logger.debug(f' lay {lay}')
                        self._submit_Stix_object(lay, session)
                    session.close()
                    logger.debug(
                        f'------------------------------------ TypeDB Sink Session Complete ---------------------------------')

        except Exception as e:
            logger.error(f'Stix Add Object Function Error: {e}')

    def _gather_objects(self, stix_data):
        """
          the details for the add details, checking what import_type of data object it is
        """
        logger.debug(f" gethering ...{stix_data}")
        logger.debug('----------------------------------------')
        logger.debug(f'going into separate objects function {stix_data}')
        logger.debug('-----------------------------------------------------')

        if isinstance(stix_data, (v21.Bundle)):
            logger.debug(f'isinstance Bundle')
            # recursively add individual STIX objects
            logger.debug(f'obects are {stix_data["objects"]}')
            return stix_data.get("objects", [])

        elif isinstance(stix_data, _STIXBase):
            logger.debug("base")
            logger.debug(f'isinstance _STIXBase')
            temp_list = []
            return temp_list.append(stix_data)

        elif isinstance(stix_data, (str, dict)):
            if stix_data.get("type", '') == 'bundle':
                return stix_data.get("objects", [])
            else:
                logger.debug("dcit")
                logger.debug(f'isinstance dict')
                temp_list = []
                return temp_list.append(stix_data)

        elif isinstance(stix_data, list):
            logger.debug(f'isinstance list')
            # recursively add individual STIX objects
            return stix_data

        else:
            raise TypeError(
                "stix_data must be a STIX object (or list of), "
                "JSON formatted STIX (or list of), "
                "or a JSON formatted STIX bundle",
            )

    def _submit_Stix_object(self, layer, session):
        """Write the given STIX object to the TypeDB database.
        """
        try:
            dep_match = layer["dep_match"]
            dep_insert = layer["dep_insert"]
            indep_ql = layer["indep_ql"]
            if dep_match == '':
                match_tql = ''
            else:
                match_tql = 'match ' + dep_match
            if indep_ql == '' and dep_insert == '':
                insert_tql = ''
            else:
                insert_tql = 'insert ' + indep_ql + dep_insert
            logger.debug(f'match_tql string?-> {match_tql}')
            logger.debug(f'insert_tql string?-> {insert_tql}')
            logger.debug(f'----------------------------- Get Ready to Load Object -----------------------------')
            typeql_string = match_tql + insert_tql
            if not insert_tql:
                logger.warning(f'Marking Object type {layer["type"]} already exists')
                return
            # logger.debug(typeql_string)
            logger.debug('=============================================================')
            with session.transaction(TransactionType.WRITE) as write_transaction:
                logger.debug(f'inside session and ready to load')
                insert_iterator = write_transaction.query().insert(typeql_string)
                logger.debug(f'insert_iterator response ->\n{insert_iterator}')
                for result in insert_iterator:
                    logger.debug(f'typedb response ->\n{result}')

                write_transaction.commit()
                logger.debug(f'----------------------------- write_transaction.commit -----------------------------')

        except Exception as e:
            logger.error(f'Stix Object Submission Error: {e}')
            logger.error(f'Query: {insert_tql}')
            raise


class TypeDBSource(DataSource):
    """Interface for searching/retrieving STIX objects from a TypeDB Database.

    Can be paired with a TypeDBSink, together as the two
    components of a TypeDBStore.

    Args:
        - connection is a dict, containing:
            - uri (str): URI to TypeDB.
            - port (int): Port to TypeDB.
            - db (str): Name of TypeDB database.
            - user (str): Username for TypeDB, if cluster, otherwise None
            - password (str): Password for TypeDB, if cluster, otherwise None
        - import_type (str): It forces the parser to use either the stix2.1, or mitre att&ck

    """

    def __init__(self, connection, import_type=None, **kwargs):
        super(TypeDBSource, self).__init__()
        logger.debug(f'TypeDBSource: {connection}')
        self._stix_connection = connection
        self.uri = connection["uri"]
        self.port = connection["port"]
        self.database = connection["database"]
        self.user = connection["user"]
        self.password = connection["password"]
        self.import_type = import_type
        if import_type is None:
            import_type = {"STIX21": True, "CVE": False, "identity": False, "location": False, "rules": False}
            import_type.update({"ATT&CK": False, "ATT&CK_Versions": ["12.0"],
                                "ATT&CK_Domains": ["enterprise-attack", "mobile-attack", "ics-attack"], "CACAO": False})
        self.import_type = import_type

    @property
    def stix_connection(self):
        return self._stix_connection

    def get(self, stix_id, _composite_filters=None):
        """Retrieve STIX object from file directory via STIX ID.

        Args:
            stix_id (str): The STIX ID of the STIX object to be retrieved.
            _composite_filters (FilterSet): collection of filters passed from the parent
                CompositeDataSource, not user supplied

        Returns:
            (STIX object): STIX object that has the supplied STIX ID.
                The STIX object is loaded from its json file, parsed into
                a python STIX object and then returned

        """
        try:
            obj_var, type_ql = get_embedded_match(stix_id)
            match = 'match ' + type_ql
            logger.debug(f' typeql -->: {match}')
            g_uri = self.uri + ':' + self.port
            with TypeDB.core_client(g_uri) as client:
                with client.session(self.database, SessionType.DATA) as session:
                    with session.transaction(TransactionType.READ) as read_transaction:
                        answer_iterator = read_transaction.query().match(match)
                        # logger.debug((f'have read the query -> {answer_iterator}'))
                        stix_dict = convert_ans_to_stix(answer_iterator, read_transaction, 'STIX21')
                        stix_obj = parse(stix_dict)
                        logger.debug(f'stix_obj -> {stix_obj}')
                        with open("export_final.json", "w") as outfile:
                            json.dump(stix_dict, outfile)

        except Exception as e:
            logger.error(f'Stix Object Retrieval Error: {e}')
            stix_obj = None

        return stix_obj

    def query(self, query=None, version=None, _composite_filters=None):
        """Search and retrieve STIX objects based on the complete query.

        A "complete query" includes the filters from the query, the filters
        attached to this FileSystemSource, and any filters passed from a
        CompositeDataSource (i.e. _composite_filters).

        Args:
            query (list): list of filters to search on
            _composite_filters (FilterSet): collection of filters passed from
                the CompositeDataSource, not user supplied
            version (str): If present, it forces the parser to use the version
                provided. Otherwise, the library will make the best effort based
                on checking the "spec_version" property.

        Returns:
            (list): list of STIX objects that matches the supplied
                query. The STIX objects are loaded from their json files,
                parsed into a python STIX objects and then returned.

        """
        pass

    def all_versions(self, stix_id, version=None, _composite_filters=None):
        """Retrieve STIX object from file directory via STIX ID, all versions.

        Note: Since FileSystem sources/sinks don't handle multiple versions
        of a STIX object, this operation is unnecessary. Pass call to get().

        Args:
            stix_id (str): The STIX ID of the STIX objects to be retrieved.
            _composite_filters (FilterSet): collection of filters passed from
                the parent CompositeDataSource, not user supplied
            version (str): If present, it forces the parser to use the version
                provided. Otherwise, the library will make the best effort based
                on checking the "spec_version" property.

        Returns:
            (list): of STIX objects that has the supplied STIX ID.
                The STIX objects are loaded from their json files, parsed into
                a python STIX objects and then returned

        """
        pass
