from stixorm.module.typedb import TypeDBSink,TypeDBSource

connection = {'uri':'192.168.2.17','port':"1729","database":"stixorm","user":None,"password":None}
sink = TypeDBSink(connection=connection,clear=True,import_type='STIX21')
sink