#!/bin/sh
# WebLogic setDomainEnv.sh — JAVA_OPTIONS is exported before startWebLogic.sh.
JAVA_OPTIONS="${JAVA_OPTIONS:-} -agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=5011"
export JAVA_OPTIONS
