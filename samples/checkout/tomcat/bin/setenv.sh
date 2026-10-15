#!/bin/sh
# Tomcat setenv.sh — CATALINA_OPTS is appended by catalina.sh for the whole JVM.
CATALINA_OPTS="${CATALINA_OPTS:-} -agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=5010"
JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:-} -agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=5010"
