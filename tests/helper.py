# Copyright 2014, 2015 SAP SE.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http: //www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
# either express or implied. See the License for the specific
# language governing permissions and limitations under the License.

import pytest


def exists_table(connection, table):
    """Check whether table exists
    :param table: name of table
    :returns: bool
    """
    cursor = connection.cursor()
    cursor.execute('SELECT 1 FROM "SYS"."TABLES" WHERE "TABLE_NAME" = %s', (table,))
    return cursor.fetchone() is not None


def create_table_fixture(request, connection, table, table_fields, column_table=False):
    """
    Create table fixture for unittests
    :param request: pytest request object
    :param connection: connection object
    :param table: name of table
    :param table_fields: string with comma separated field definitions, e.g. "name VARCHAR(5), fblob blob"
    """
    cursor = connection.cursor()
    if exists_table(connection, table):
        cursor.execute('DROP table "%s"' % table)

    assert not exists_table(connection, table)
    table_type = "COLUMN" if column_table else ""
    cursor.execute('CREATE %s table "%s" (%s)' % (table_type, table, table_fields))
    if not exists_table(connection, table):
        pytest.skip("Couldn't create table %s" % table)
        return

    def _close():
        cursor.execute('DROP table "%s"' % table)
    request.addfinalizer(_close)


def create_procedure_fixture(request, connection, create_proc_sql):
    cursor = connection.cursor()
    procedure_name = create_proc_sql.split(' ')[2].split('(')[0]

    if not procedure_name.upper().startswith("PYHDB_"):
        raise Exception(
            "Unable to create procedure fixture "
            "(The procdure name should start with 'PYHDB_')"
        )

    def _drop_procedure_if_exists():
        proc_exists_sql = """
SELECT 1
FROM SYS.P_PROCEDURES_
WHERE SCHEMA='SYSTEM' AND NAME='%s'""" % procedure_name
        drop_proc_sql = """
DROP PROCEDURE %s""" % procedure_name

        cursor.execute(proc_exists_sql)
        proc_exists = cursor.fetchone() is not None

        if proc_exists:
            if not procedure_name.upper().startswith("PYHDB_"):
                raise Exception(
                    "Unable to drop procedure fixture (It is only safe "
                    "to delete procedures whose name start with 'PYHDB_' "
                    "in schema 'SYSTEM')"
                )
            cursor.execute(drop_proc_sql)

    _drop_procedure_if_exists()
    cursor.execute(create_proc_sql)

    request.addfinalizer(_drop_procedure_if_exists)
