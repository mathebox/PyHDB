#!/bin/bash
EXTRACT_DIR="helper"
NEO_VERSION=3.2.14
NEO=./${EXTRACT_DIR}/tools/neo.sh
PYTEST="py.test -v --cov=pyhdb"

if [[ -z "$CLOUD_HOST" ]] || [[ -z "$CLOUD_USER" ]] || [[ -z "$CLOUD_ACCOUNT" ]] || [[ -z "$CLOUD_PASSWORD" ]]
then
    # start pytest without database
    $PYTEST
else
    # get Neo web SDK
    echo "Download Neo web SDK"
    wget http://central.maven.org/maven2/com/sap/cloud/neo-java-web-sdk/${NEO_VERSION}/neo-java-web-sdk-${NEO_VERSION}.zip
    unzip neo-java-web-sdk-${NEO_VERSION}.zip -d ./${EXTRACT_DIR}/

    # open tunnel to database
    echo "Open tunnel to database"
    open_tunnel_output=`$NEO open-db-tunnel -h $CLOUD_HOST -u $CLOUD_USER -a $CLOUD_ACCOUNT -i $CLOUD_ID -p $CLOUD_PASSWORD --background`
    close_tunnel_cmd=`echo "$open_tunnel_output" | tail -n 1 | xargs | cut -d' ' -f2-`
    HANA_HOST=`echo "$open_tunnel_output" | grep "Host name" | rev | cut -d' ' -f1 | rev`
    HANA_PORT=`echo 3$(echo "$open_tunnel_output" | grep "Instance number" | rev | cut -d' ' -f1 | rev)15`
    HANA_USER=`echo "$open_tunnel_output" | grep "User" | rev | cut -d' ' -f1 | rev`
    HANA_PASSWORD=`echo "$open_tunnel_output" | grep "Password" | rev | cut -d' ' -f1 | rev`

    # start pytest with databse
    $PYTEST --hana-host=$HANA_HOST --hana-port=$HANA_PORT --hana-user=$HANA_USER --hana-password=$HANA_PASSWORD

    # close tunnel
    echo "Close tunnel to database"
    close_tunnel_output=`$NEO $close_tunnel_cmd`
fi
