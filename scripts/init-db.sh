#!/bin/sh
set -eu

: "${INVENTORY_DB_PASSWORD:?INVENTORY_DB_PASSWORD is required}"
: "${BOOKING_DB_PASSWORD:?BOOKING_DB_PASSWORD is required}"
: "${PAYMENT_DB_PASSWORD:?PAYMENT_DB_PASSWORD is required}"
: "${NOTIFICATION_DB_PASSWORD:?NOTIFICATION_DB_PASSWORD is required}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=inventory_password="$INVENTORY_DB_PASSWORD" \
  --set=booking_password="$BOOKING_DB_PASSWORD" \
  --set=payment_password="$PAYMENT_DB_PASSWORD" \
  --set=notification_password="$NOTIFICATION_DB_PASSWORD" <<'EOSQL'
CREATE USER inventory_user WITH PASSWORD :'inventory_password';
CREATE USER booking_user WITH PASSWORD :'booking_password';
CREATE USER payment_user WITH PASSWORD :'payment_password';
CREATE USER notification_user WITH PASSWORD :'notification_password';
CREATE DATABASE inventory OWNER inventory_user;
CREATE DATABASE booking OWNER booking_user;
CREATE DATABASE payment OWNER payment_user;
CREATE DATABASE notification OWNER notification_user;
REVOKE CONNECT ON DATABASE inventory FROM PUBLIC;
REVOKE CONNECT ON DATABASE booking FROM PUBLIC;
REVOKE CONNECT ON DATABASE payment FROM PUBLIC;
REVOKE CONNECT ON DATABASE notification FROM PUBLIC;
GRANT CONNECT ON DATABASE inventory TO inventory_user;
GRANT CONNECT ON DATABASE booking TO booking_user;
GRANT CONNECT ON DATABASE payment TO payment_user;
GRANT CONNECT ON DATABASE notification TO notification_user;
EOSQL
