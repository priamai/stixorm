from stixorm.module.typedb import TypeDBSink,TypeDBSource

import logging

logging.basicConfig(level=logging.INFO)

connection = {'uri':'192.168.2.17','port':"1729","database":"stixorm","user":None,"password":None}

group_json = {
    "type": "grouping",
    "spec_version": "2.1",
    "id": "grouping--6650da68-73d3-45d6-a9ba-f03a51e780ec",
    "created": "2022-09-16T16:35:04.816072Z",
    "modified": "2022-09-16T16:35:04.816072Z",
    "name": "alert",
    "description": "ciao",
    "context": "suspicious-activity",
    "object_refs": [
    ],
    "labels": [
        "WHATEVERMAN!"
    ]
}
# either insert fails or return fails
sink = TypeDBSink(connection=connection,clear=True,import_type='STIX21')
sink.add(group_json)

source = TypeDBSource(connection=connection,import_type='STIX21')

x = source.get("grouping--6650da68-73d3-45d6-a9ba-f03a51e780ec")