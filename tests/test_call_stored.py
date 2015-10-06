# -*- coding: utf-8 -*-

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
from random import randint

import tests.helper as helper

# #############################################################################################################
#                         Fixtures
# #############################################################################################################


@pytest.fixture
def procedure_in_table_fixture(request, connection):
    """Fixture to create table for testing, and dropping it after test run"""
    table_name = 'PYHDB_PROC_IN_TABLE'
    table_fields = 'COL INTEGER'
    helper.create_table_fixture(request, connection, table_name, table_fields)
    cursor = connection.cursor()
    cursor.execute("INSERT INTO PYHDB_PROC_IN_TABLE VALUES(0)")


@pytest.fixture
def procedure_in_fixture(request, connection):
    sql = """
CREATE PROCEDURE PYHDB_PROC_IN (IN a INT)
LANGUAGE SQLSCRIPT AS
BEGIN
    UPDATE PYHDB_PROC_IN_TABLE
    SET col = a;
END"""
    helper.create_procedure_fixture(request, connection, sql)


@pytest.fixture
def procedure_inout_fixture(request, connection):
    sql = """
CREATE PROCEDURE PYHDB_PROC_INOUT (INOUT a INT)
LANGUAGE SQLSCRIPT
READS SQL DATA AS
BEGIN
    a := :a * 2;
END"""
    helper.create_procedure_fixture(request, connection, sql)


@pytest.fixture
def procedure_out_fixture(request, connection):
    sql = """
CREATE PROCEDURE PYHDB_PROC_OUT (OUT OUTVAR INTEGER)
LANGUAGE SQLSCRIPT
READS SQL DATA AS
BEGIN
    outvar := 2015;
END"""
    helper.create_procedure_fixture(request, connection, sql)


@pytest.fixture
def procedure_in_out_fixture(request, connection):
    sql = """
CREATE PROCEDURE PYHDB_PROC_IN_OUT (in a int, in b int, out c int)
LANGUAGE SQLSCRIPT
READS SQL DATA AS
BEGIN
    c := :a + :b;
END"""
    helper.create_procedure_fixture(request, connection, sql)


@pytest.fixture
def procedure_table_fixture(request, connection):
    sql = """
CREATE PROCEDURE PYHDB_PROC_TABLE (out b TABLE(c int, d int))
LANGUAGE SQLSCRIPT
READS SQL DATA AS
BEGIN
    b = SELECT 1 as c, 2 as d FROM dummy;
END"""
    helper.create_procedure_fixture(request, connection, sql)


@pytest.fixture
def procedure_2_tables_fixture(request, connection):
    sql = """
CREATE PROCEDURE PYHDB_PROC_2_TABLES (out a TABLE(b int, c int), out d TABLE(e int, f int))
LANGUAGE SQLSCRIPT
READS SQL DATA AS
BEGIN
    a = SELECT 1 as b, 2 as c FROM dummy;
    d = SELECT 3 as e, 4 as f FROM dummy;
END"""
    helper.create_procedure_fixture(request, connection, sql)


@pytest.fixture
def procedure_3_tables_fixture(request, connection):
    sql = """
CREATE PROCEDURE PYHDB_PROC_3_TABLES (out a TABLE(b int, c int),
                                      out d TABLE(e int, f int),
                                      out g TABLE(h int, i int))
LANGUAGE SQLSCRIPT
READS SQL DATA AS
BEGIN
    a = SELECT 1 as b, 2 as c FROM dummy;
    d = SELECT 3 as e, 4 as f FROM dummy;
    g = SELECT 5 as h, 6 as i FROM dummy;
END"""
    helper.create_procedure_fixture(request, connection, sql)


@pytest.fixture
def procedure_out_table_fixture(request, connection):
    sql = """
CREATE PROCEDURE PYHDB_PROC_OUT_TABLE (out a int, out b TABLE(c int, d int))
LANGUAGE SQLSCRIPT
READS SQL DATA AS
BEGIN
    a := 5;
    b = SELECT 1 as c, 2 as d FROM dummy;
END"""
    helper.create_procedure_fixture(request, connection, sql)

# #############################################################################################################
#                         Basic Stored Procedure test
# #############################################################################################################


@pytest.mark.hanatest
def test_proc_in(connection, procedure_in_table_fixture, procedure_in_fixture):
    cursor = connection.cursor()
    # prepare call
    psid = cursor.prepare("CALL PYHDB_PROC_IN (?)")
    ps = cursor.get_prepared_statement(psid)
    # execute prepared statement
    value = randint(0, 1000)
    params = {'A': value}
    cursor.execute_prepared(ps, [params])
    # check updated table
    cursor.execute("SELECT TOP 1 col FROM PYHDB_PROC_IN_TABLE")
    # verify result
    result = cursor.fetchone()
    assert result[0] == value
    assert cursor.nextset() is None
    cursor.close()


@pytest.mark.hanatest
def test_proc_in_out(connection, procedure_inout_fixture):
    cursor = connection.cursor()
    # prepare call
    psid = cursor.prepare("CALL PYHDB_PROC_INOUT (?)")
    ps = cursor.get_prepared_statement(psid)
    # execute prepared statement
    value = randint(0, 1000)
    params = {'A': value}
    cursor.execute_prepared(ps, [params])
    # verify result
    result = cursor.fetchone()
    assert result[0] == value*2
    assert cursor.nextset() is None
    cursor.close()


@pytest.mark.hanatest
def test_proc_out(connection, procedure_out_fixture):
    cursor = connection.cursor()
    # prepare call
    psid = cursor.prepare("CALL PYHDB_PROC_OUT (?)")
    ps = cursor.get_prepared_statement(psid)
    # execute prepared statement
    cursor.execute_prepared(ps)
    # verify result
    result = cursor.fetchone()
    assert result[0] == 2015
    assert cursor.nextset() is None
    cursor.close()


@pytest.mark.hanatest
def test_proc_in_and_out(connection, procedure_in_out_fixture):
    cursor = connection.cursor()
    # prepare call
    sql_to_prepare = 'CALL PYHDB_PROC_IN_OUT (?, ?, ?)'
    a, b = randint(0, 1000), randint(0, 1000)
    params = {'A': a, 'B': b}
    psid = cursor.prepare(sql_to_prepare)
    # execute prepared statement
    ps = cursor.get_prepared_statement(psid)
    cursor.execute_prepared(ps, [params])
    # verify result
    result = cursor.fetchone()
    assert result[0] == a+b

    assert cursor.nextset() is None


@pytest.mark.hanatest
def test_proc_table(connection, procedure_table_fixture):
    cursor = connection.cursor()
    # prepare call
    sql_to_prepare = 'CALL PYHDB_PROC_TABLE (?)'
    psid = cursor.prepare(sql_to_prepare)
    # execute prepared statement
    ps = cursor.get_prepared_statement(psid)
    cursor.execute_prepared(ps)
    # verify result
    result = cursor.fetchone()
    assert result == (1, 2)

    assert cursor.nextset() is None


@pytest.mark.hanatest
def test_proc_out_table(connection, procedure_out_table_fixture):
    cursor = connection.cursor()
    # prepare call
    sql_to_prepare = 'CALL PYHDB_PROC_OUT_TABLE (?, ?)'
    psid = cursor.prepare(sql_to_prepare)
    # execute prepared statement
    ps = cursor.get_prepared_statement(psid)
    cursor.execute_prepared(ps)
    # verify result
    result = cursor.fetchone()
    assert result == (5,)

    assert cursor.nextset() == True
    # verify result
    result = cursor.fetchone()
    assert result == (1, 2)

    assert cursor.nextset() is None


@pytest.mark.hanatest
def test_proc_2_tables(connection, procedure_2_tables_fixture):
    cursor = connection.cursor()
    # prepare call
    sql_to_prepare = 'CALL PYHDB_PROC_2_TABLES (?,?)'
    psid = cursor.prepare(sql_to_prepare)
    # execute prepared statement
    ps = cursor.get_prepared_statement(psid)
    cursor.execute_prepared(ps)
    # verify result
    result = cursor.fetchone()
    assert result == (1, 2)

    assert cursor.nextset() == True
    # verify result
    result = cursor.fetchone()
    assert result == (3, 4)

    assert cursor.nextset() is None


@pytest.mark.hanatest
def test_proc_3_tables(connection, procedure_3_tables_fixture):
    cursor = connection.cursor()
    # prepare call
    sql_to_prepare = 'CALL PYHDB_PROC_3_TABLES (?,?,?)'
    psid = cursor.prepare(sql_to_prepare)
    # execute prepared statement
    ps = cursor.get_prepared_statement(psid)
    cursor.execute_prepared(ps)
    # verify result
    result = cursor.fetchone()
    assert result == (1, 2)

    assert cursor.nextset() == True
     # verify result
    result = cursor.fetchone()
    assert result == (3, 4)

    assert cursor.nextset() == True
    # verify result
    result = cursor.fetchone()
    assert result == (5, 6)

    assert cursor.nextset() is None


@pytest.mark.hanatest
def test_proc_skip_output_params(connection, procedure_out_table_fixture):
    cursor = connection.cursor()
    # prepare call
    sql_to_prepare = 'CALL PYHDB_PROC_OUT_TABLE (?, ?)'
    psid = cursor.prepare(sql_to_prepare)
    # execute prepared statement
    ps = cursor.get_prepared_statement(psid)
    cursor.execute_prepared(ps)
    assert cursor.nextset() == True
    # verify result
    result = cursor.fetchone()
    assert result == (1, 2)

    assert cursor.nextset() is None


@pytest.mark.hanatest
def test_proc_3_tables_skip_first(connection, procedure_3_tables_fixture):
    cursor = connection.cursor()
    # prepare call
    sql_to_prepare = 'CALL PYHDB_PROC_3_TABLES (?,?,?)'
    psid = cursor.prepare(sql_to_prepare)
    # execute prepared statement
    ps = cursor.get_prepared_statement(psid)
    cursor.execute_prepared(ps)

    assert cursor.nextset() == True
     # verify result
    result = cursor.fetchone()
    assert result == (3, 4)

    assert cursor.nextset() == True
     # verify result
    result = cursor.fetchone()
    assert result == (5, 6)

    assert cursor.nextset() is None


@pytest.mark.hanatest
def test_proc_3_tables_skip_middle(connection, procedure_3_tables_fixture):
    cursor = connection.cursor()
    # prepare call
    sql_to_prepare = 'CALL PYHDB_PROC_3_TABLES (?,?,?)'
    psid = cursor.prepare(sql_to_prepare)
    # execute prepared statement
    ps = cursor.get_prepared_statement(psid)
    cursor.execute_prepared(ps)
    # verify result
    result = cursor.fetchone()
    assert result == (1, 2)

    assert cursor.nextset() == True
    assert cursor.nextset() == True
    # verify result
    result = cursor.fetchone()
    assert result == (5, 6)

    assert cursor.nextset() is None


@pytest.mark.hanatest
def test_proc_3_tables_skip_last(connection, procedure_3_tables_fixture):
    cursor = connection.cursor()
    # prepare call
    sql_to_prepare = 'CALL PYHDB_PROC_3_TABLES (?,?,?)'
    psid = cursor.prepare(sql_to_prepare)
    # execute prepared statement
    ps = cursor.get_prepared_statement(psid)
    cursor.execute_prepared(ps)
    # verify result
    result = cursor.fetchone()
    assert result == (1, 2)

    assert cursor.nextset() == True
    # verify result
    result = cursor.fetchone()
    assert result == (3, 4)

    assert cursor.nextset() == True
    assert cursor.nextset() is None
