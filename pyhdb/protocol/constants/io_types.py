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

# IO Types

INPUT = 1
IN_OUT = 2
OUTPUT = 4


def isInputParameter(param):
    return param.iotype in (INPUT, IN_OUT)


def isOutputParameter(param):
    return param.iotype in (OUTPUT, IN_OUT)
