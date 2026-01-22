#!/bin/bash
cd /opt/plattargus-web
docker compose up -d
echo "PlattArgus Laravel iniciado!"
docker ps | grep plattargus
