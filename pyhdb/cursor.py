# Copyright 2014, 2015 SAP SE
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import collections
###
from pyhdb.protocol.message import RequestMessage
from pyhdb.protocol.segments import RequestSegment
from pyhdb.protocol.types import escape_values, by_type_code
from pyhdb.protocol.parts import Command, FetchSize, ResultSetId, StatementId, Parameters, WriteLobRequest
from pyhdb.protocol.constants import message_types, function_codes, part_kinds, io_types, part_attributes
from pyhdb.exceptions import ProgrammingError, InterfaceError, DatabaseError
from pyhdb.compat import izip

FORMAT_OPERATION_ERRORS = [
    'not enough arguments for format string',
    'not all arguments converted during string formatting'
]


def format_operation(operation, parameters=None):
    if parameters is not None:
        e_values = escape_values(parameters)
        try:
            operation = operation % e_values
        except TypeError as msg:
            if str(msg) in FORMAT_OPERATION_ERRORS:
                # Python DBAPI expects a ProgrammingError in this case
                raise ProgrammingError(str(msg))
            else:
                # some other error message appeared, so just reraise exception:
                raise
    return operation


class PreparedStatement(object):
    """Reference object to a prepared statement including parameter (meta) data"""

    ParamTuple = collections.namedtuple('Parameter', 'id type_code length value')

    def __init__(self, connection, statement_id, params_metadata, result_metadata_part):
        """Initialize PreparedStatement part object
        :param connection: connection object
        :param statement_id: 8-byte statement identifier
        :param params_metadata: A tuple of named-tuple instances containing parameter meta data:
               Example: (ParameterMetadata(options=2, datatype=26, mode=1, id=0, length=24, fraction=0),)
        :param result_metadata_part: can be None
        """
        self._connection = connection
        self.statement_id = statement_id
        self._params_metadata = params_metadata
        self.result_metadata_part = result_metadata_part
        self._multi_row_parameters = None
        self._num_rows = None
        self._iter_row_count = None

    def prepare_parameters(self, multi_row_parameters):
        """ Attribute sql parameters with meta data for a prepared statement.
        Make some basic checks that at least the number of parameters is correct.
        :param multi_row_parameters: A list/tuple containing list/tuples of parameters (for multiple rows)
        :returns: A generator producing parameters attributed with meta data for one sql statement (a row) at a time
        """
        self._multi_row_parameters = multi_row_parameters
        self._num_rows = len(multi_row_parameters)
        self._iter_row_count = 0
        return self

    def __repr__(self):
        return '<PreparedStatement id=%r>' % self.statement_id

    def __iter__(self):
        return self

    def __nonzero__(self):
        return self._iter_row_count < self._num_rows

    def next(self):
        if self._iter_row_count == self._num_rows:
            raise StopIteration()

        parameters = self._multi_row_parameters[self._iter_row_count]
        if not isinstance(parameters, (list, tuple, dict)):
            raise ProgrammingError("Prepared statement parameters supplied as %s, shall be list, tuple or dict." %
                                   type(parameters).__name__)

        input_params_metadata = filter(io_types.is_input_parameter, self._params_metadata)
        if isinstance(parameters, dict):
            ids_contained = [meta.id in parameters for meta in input_params_metadata]
            if not all(ids_contained):
                missing_ids = [meta.id for meta in input_params_metadata if meta.id not in parameters ]
                raise ProgrammingError("Prepared statement parameters misses values for: %s" %
                                       ', '.join(missing_ids))
        else:
            if len(parameters) != len(input_params_metadata):
                raise ProgrammingError("Prepared statement parameters expected %d supplied %d." %
                                       (len(input_params_metadata), len(parameters)))
        row_params = [self.ParamTuple(p.id, p.datatype, p.length, parameters[p.id]) for p in input_params_metadata]
        self._iter_row_count += 1
        return row_params

    def back(self):
        assert self._iter_row_count > 0, 'already stepped back to beginning of iterator data'
        self._iter_row_count -= 1


class Cursor(object):
    """Database cursor class"""
    def __init__(self, connection):
        self.connection = connection
        self.rowcount = -1
        self.rownumber = None
        self.arraysize = 1
        self._prepared_statements = {}
        self._reset()

    def _reset(self):
        self._output_param_buffer = None
        self._buffer = {}
        self._resultset_closed = False
        self._executed = None

        self._resultset_ids = []
        self._column_types = {}
        self.descriptions = {}

        self._cached_resultset_metadata = None
        self._cached_resultset_id = None
        self._last_resultset_id = None
        self._current_resultset_id = None

    @property
    def prepared_statement_ids(self):
        return self._prepared_statements.keys()

    def get_prepared_statement(self, statement_id):
        return self._prepared_statements[statement_id]

    def prepare(self, statement):
        """Prepare SQL statement in HANA and cache it
        :param statement; a valid SQL statement
        :returns: statement_id (of prepared and cached statement)
        """
        self._check_closed()
        statement_id = params_metadata = result_metadata_part = None

        request = RequestMessage.new(
            self.connection,
            RequestSegment(
                message_types.PREPARE,
                Command(statement)
            )
        )
        response = self.connection.send_request(request)

        for part in response.segments[0].parts:
            if part.kind == part_kinds.STATEMENTID:
                statement_id = part.statement_id
            elif part.kind == part_kinds.PARAMETERMETADATA:
                params_metadata = part.values
            elif part.kind == part_kinds.RESULTSETMETADATA:
                result_metadata_part = part

        # Check that both variables have been set in previous loop, we need them:
        assert statement_id is not None
        assert params_metadata is not None
        # cache statement:
        self._prepared_statements[statement_id] = PreparedStatement(self.connection, statement_id,
                                                                    params_metadata, result_metadata_part)
        return statement_id

    def execute_prepared(self, prepared_statement, multi_row_parameters=None):
        """
        :param prepared_statement: A PreparedStatement instance
        :param multi_row_parameters: A list/tuple containing list/tuples of parameters (for multiple rows)
        """
        self._check_closed()
        self._reset()

        if multi_row_parameters is None:
            multi_row_parameters = [[]]

        # Convert parameters into a generator producing lists with parameters as named tuples (incl. some meta data):
        parameters = prepared_statement.prepare_parameters(multi_row_parameters)

        while parameters:
            parameters_part = Parameters(parameters)
            request = RequestMessage.new(
                self.connection,
                RequestSegment(
                    message_types.EXECUTE,
                    (StatementId(prepared_statement.statement_id),
                     parameters_part)
                )
            )
            reply = self.connection.send_request(request)
            self._handle_reply(reply, prepared_statement, parameters_part.unwritten_lobs)

    def _execute_direct(self, operation):
        """Execute statements which are not going through 'prepare_statement' (aka 'direct execution').
        Either their have no parameters, or Python's string expansion has been applied to the SQL statement.
        :param operation:
        """
        self._reset()

        request = RequestMessage.new(
            self.connection,
            RequestSegment(
                message_types.EXECUTEDIRECT,
                Command(operation)
            )
        )
        reply = self.connection.send_request(request)
        self._handle_reply(reply)

    def execute(self, statement, parameters=None):
        """Execute statement on database
        :param statement: a valid SQL statement
        :param parameters: a list/tuple of parameters
        :returns: this cursor

        In order to be compatible with Python's DBAPI five parameter styles
        must be supported.

        paramstyle	Meaning
        ---------------------------------------------------------
        1) qmark       Question mark style, e.g. ...WHERE name=?
        2) numeric     Numeric, positional style, e.g. ...WHERE name=:1
        3) named       Named style, e.g. ...WHERE name=:name
        4) format      ANSI C printf format codes, e.g. ...WHERE name=%s
        5) pyformat    Python extended format codes, e.g. ...WHERE name=%(name)s

        Hana's 'prepare statement' feature supports 1) and 2), while 4 and 5
        are handle by Python's own string expansion mechanism.
        Note that case 3 is not yet supported by this method!
        """
        self._check_closed()

        if not parameters:
            # Directly execute the statement, nothing else to prepare:
            self._execute_direct(statement)
        else:
            self.executemany(statement, parameters=[parameters])
        return self

    def executemany(self, statement, parameters):
        """Execute statement on database with multiple rows to be inserted/updated
        :param statement: a valid SQL statement
        :param parameters: a nested list/tuple of parameters for multiple rows
        :returns: this cursor
        """
        # First try safer hana-style parameter expansion:
        try:
            statement_id = self.prepare(statement)
        except DatabaseError as msg:
            # Hana expansion failed, check message to be sure of reason:
            if 'incorrect syntax near "%"' not in str(msg):
                # Probably some other error than related to string expansion -> raise an error
                raise
            # Statement contained percentage char, so perform Python style parameter expansion:
            for row_params in parameters:
                operation = format_operation(statement, row_params)
                self._execute_direct(operation)
        else:
            # Continue with Hana style statement execution:
            prepared_statement = self.get_prepared_statement(statement_id)
            self.execute_prepared(prepared_statement, parameters)
        # Return cursor object:
        return self

    def callproc(self, procedure_name, parameters=None):
        if parameters is None:
            parameters = {}

        procedure_name_parts = procedure_name.split('.')
        if len(procedure_name_parts) == 1:
            schema_name_part = 'current_schema'
            procedure_name_part = procedure_name
        elif len(procedure_name_parts) == 2:
            schema_name_part = "'%s'" % procedure_name_parts[0]
            procedure_name_part = procedure_name_parts[1]
        else:
            raise ProgrammingError("Invalid name for stored procedure: '%s'" %
                                   procedure_name)

        param_count_sql = """
SELECT num_input_params, num_inout_params, num_output_params
FROM SYS.P_PROCEDURES_
WHERE schema=%s and name='%s'
        """
        self.execute(param_count_sql % (schema_name_part, procedure_name_part))
        param_count_result = self.fetchone()
        if param_count_result is None:
            raise DatabaseError("Stored procedure '%s' does not exist" %
                                procedure_name)
        param_count = sum(param_count_result)

        placeholders = '(%s)' % ','.join(['?']*param_count)
        sql_to_prepare = 'CALL %s %s' % (procedure_name, placeholders)
        psid = self.prepare(sql_to_prepare)
        ps = self.get_prepared_statement(psid)
        params_metadata = ps._params_metadata
        self.execute_prepared(ps, [parameters])

        output_parameters = parameters.copy()
        if self._output_param_buffer is not None:
            output = self.fetchone()
            output_parameter = filter(io_types.is_output_parameter, params_metadata)
            for i, param_id in enumerate([p.id for p in output_parameter]):
                output_parameters[param_id] = output[i]
            self.nextset()
        return output_parameters

    def _handle_reply(self, reply, prepared_statement=None, unwritten_lobs=None):
        if unwritten_lobs is None:
            unwritten_lobs = ()
        for segment in reply.segments:
            if segment.function_code == function_codes.SELECT:
                metadata = prepared_statement.result_metadata_part if prepared_statement is not None else None
                self._handle_select(segment.parts, metadata)
            elif segment.function_code in function_codes.DML:
                self._handle_upsert(segment.parts, unwritten_lobs)
            elif segment.function_code == function_codes.DDL:
                # No additional handling is required
                pass
            elif segment.function_code in (function_codes.DBPROCEDURECALL, function_codes.DBPROCEDURECALLWITHRESULT):
                metadata = prepared_statement._params_metadata if prepared_statement is not None else None
                self._handle_dbproc_call(segment.parts, metadata)
            else:
                raise InterfaceError("Invalid or unsupported function code received: %d" % segment.function_code)

    def _handle_upsert(self, parts, unwritten_lobs):
        """Handle reply messages from INSERT or UPDATE statements"""
        for part in parts:
            if part.kind == part_kinds.ROWSAFFECTED:
                self.rowcount = part.values[0]
            elif part.kind in (part_kinds.TRANSACTIONFLAGS, part_kinds.STATEMENTCONTEXT):
                pass
            elif part.kind == part_kinds.WRITELOBREPLY:
                # This part occurrs after lobs have been submitted not at all or only partially during an insert.
                # In this case the parameter part of the Request message contains a list called 'unwritten_lobs'
                # with LobBuffer instances.
                # Those instances are in the same order as 'locator_ids' received in the reply message. These IDs
                # are then used to deliver the missing LOB data to the server via WRITE_LOB_REQUESTs.
                for lob_buffer, lob_locator_id in izip(unwritten_lobs, part.locator_ids):
                    # store locator_id in every lob buffer instance for later reference:
                    lob_buffer.locator_id = lob_locator_id
                self._perform_lob_write_requests(unwritten_lobs)
            else:
                raise InterfaceError("Prepared insert statement response, unexpected part kind %d." % part.kind)
        self._executed = True

    def _perform_lob_write_requests(self, unwritten_lobs):
        """After sending incomplete LOB data during an INSERT or UPDATE this method will be called.
        It sends missing LOB data possibly in multiple LOBWRITE requests for all LOBs.
        :param unwritten_lobs: A deque list of LobBuffer instances containing LOB data.
               Those buffers have been assembled in the parts.Parameter.pack_lob_data() method.
        """
        while unwritten_lobs:
            request = RequestMessage.new(
                self.connection,
                RequestSegment(
                    message_types.WRITELOB,
                    WriteLobRequest(unwritten_lobs)
                )
            )
            self.connection.send_request(request)

    def _stored_resultset_id_metadata_if_possible(self):
        if self._cached_resultset_metadata is None or self._cached_resultset_id is None:
            return

        self._resultset_ids.append(self._cached_resultset_id)
        if self._current_resultset_id is None:
            self._current_resultset_id = self._cached_resultset_id
        description, column_types = self._handle_result_metadata(self._cached_resultset_metadata)
        self.descriptions[self._cached_resultset_id] = description
        self._column_types[self._cached_resultset_id] = column_types
        # reset
        self._cached_resultset_metadata = None
        self._cached_resultset_id = None

    def _handle_select(self, parts, result_metadata=None):
        """Handle reply messages from SELECT statements"""
        self.rowcount = -1
        if result_metadata is not None:
            # Select was prepared and we can use the already received metadata
            self._cached_resultset_metadata = result_metadata
            self._stored_resultset_id_metadata_if_possible()
        for part in parts:
            if part.kind == part_kinds.RESULTSETID:
                self._last_resultset_id = part.value
                self._cached_resultset_id = part.value
                self._stored_resultset_id_metadata_if_possible()
            elif part.kind == part_kinds.RESULTSETMETADATA:
                description, column_types = self._handle_result_metadata(part)
                self._cached_resultset_metadata = part
                self._stored_resultset_id_metadata_if_possible()
            elif part.kind == part_kinds.RESULTSET:
                self._buffer[self._last_resultset_id] = part.unpack_rows(self._column_types[self._last_resultset_id], self.connection)
                self._resultset_closed = part_attributes.is_resultset_closed(part.attribute)
            elif part.kind in (part_kinds.STATEMENTCONTEXT, part_kinds.TRANSACTIONFLAGS):
                pass
            else:
                raise InterfaceError("Prepared select statement response, unexpected part kind %d." % part.kind)
        self._executed = True

    def _handle_dbproc_call(self, parts, parameters_metadata):
        """Handle reply messages from STORED PROCEDURE statements"""

        for part in parts:
            if part.kind == part_kinds.ROWSAFFECTED:
                self.rowcount = part.values[0]
            elif part.kind == part_kinds.TRANSACTIONFLAGS:
                pass
            elif part.kind == part_kinds.STATEMENTCONTEXT:
                pass
            elif part.kind == part_kinds.OUTPUTPARAMETERS:
                self._output_param_buffer = part.unpack_rows(parameters_metadata, self.connection)
            elif part.kind == part_kinds.RESULTSETMETADATA:
                self._cached_resultset_metadata = part
                self._stored_resultset_id_metadata_if_possible()
            elif part.kind == part_kinds.RESULTSETID:
                self._last_resultset_id = part.value
                self._cached_resultset_id = part.value
                self._stored_resultset_id_metadata_if_possible()
            elif part.kind == part_kinds.RESULTSET:
                self._buffer[self._last_resultset_id] = part.unpack_rows(self._column_types[self._last_resultset_id], self.connection)
                self._resultset_closed = part_attributes.is_resultset_closed(part.attribute)
            else:
                raise InterfaceError("Stored procedure call, unexpected part kind %d." % part.kind)
        self._executed = True

    def _handle_result_metadata(self, result_metadata):
        description = []
        column_types = []
        for column in result_metadata.columns:
            description.append((column[8], column[1], None, column[3], column[2], None, column[0] & 0b10))

            if column[1] not in by_type_code:
                raise InterfaceError("Unknown column data type: %s" % column[1])
            column_types.append(by_type_code[column[1]])

        return tuple(description), tuple(column_types)

    def nextset(self):
        if self._output_param_buffer is not None:
            self._output_param_buffer = None
            if self._current_resultset_id is None:
                return None
            else:
                return True
        else:
            if self._current_resultset_id is None:
                return None
            next_resultset_idx = self._resultset_ids.index(self._current_resultset_id)+1
            if next_resultset_idx < len(self._resultset_ids):
                self._current_resultset_id = self._resultset_ids[next_resultset_idx]
                return True
            else:
                return None

    def _current_buffer(self, fetch_next, fetch_size):
        # output parameters exist
        if self._output_param_buffer is not None:
            return self._output_param_buffer, True
        # use existing buffer
        if fetch_next or self._current_resultset_id not in self._buffer:
            request = RequestMessage.new(
                self.connection,
                RequestSegment(
                    message_types.FETCHNEXT,
                    (ResultSetId(self._current_resultset_id), FetchSize(fetch_size))
                )
            )
            response = self.connection.send_request(request)
            # use _handle_select or _handle_dbproc here
            resultset_part = response.segments[0].parts[1]
            self._resultset_closed = part_attributes.is_resultset_closed(resultset_part.attribute)
            self._buffer[self._current_resultset_id] = resultset_part.unpack_rows(self._column_types[self._current_resultset_id], self.connection)
        return self._buffer[self._current_resultset_id], False

    def fetchmany(self, size=None):
        """Fetch many rows from select result set.
        :param size: Number of rows to return.
        :returns: list of row records (tuples)
        """
        self._check_closed()
        if not self._executed:
            raise ProgrammingError("Require execute() first")
        if size is None:
            size = self.arraysize

        result = []
        cnt = 0
        cnt_round = None

        while cnt < size:
            fetch_next = (cnt_round == 0)
            cnt_round = 0
            buffer, is_output_params = self._current_buffer(fetch_next, size-cnt)
            for row in buffer:
                if cnt >= size:
                    break
                result.append(row)
                cnt += 1
                cnt_round += 1
            if is_output_params or cnt == size or self._resultset_closed:
                break
        return result

    def fetchone(self):
        """Fetch one row from select result set.
        :returns: a single row tuple
        """
        result = self.fetchmany(size=1)
        if result:
            return result[0]
        return None

    FETCHALL_BLOCKSIZE = 1024

    def fetchall(self):
        """Fetch all available rows from select result set.
        :returns: list of row tuples
        """
        result = r = self.fetchmany(size=self.FETCHALL_BLOCKSIZE)
        while not self._resultset_closed:
            r = self.fetchmany(size=self.FETCHALL_BLOCKSIZE)
            result.extend(r)
        return result

    def close(self):
        self.connection = None

    def _check_closed(self):
        if self.connection is None or self.connection.closed:
            raise ProgrammingError("Cursor closed")
