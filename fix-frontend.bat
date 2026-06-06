@echo off
setlocal EnableDelayedExpansion

set RG_NAME=rg-sre-swarm-foundry
set SWARM_APP_NAME=ca-swarm-backend

echo Fetching Backend URL...
for /f "tokens=*" %%i in ('az containerapp show --name %SWARM_APP_NAME% --resource-group %RG_NAME% --query properties.configuration.ingress.fqdn -o tsv') do set SWARM_BACKEND_URL=%%i

echo Fetching ACR Name from Frontend Config...
for /f "tokens=*" %%i in ('az containerapp show --name ca-swarm-frontend --resource-group %RG_NAME% --query "properties.configuration.registries[0].username" -o tsv') do set ACR_NAME=%%i

echo Fetching ACR Password...
for /f "tokens=*" %%i in ('az acr credential show --name !ACR_NAME! --query "passwords[0].value" -o tsv') do set ACR_PASSWORD=%%i

echo Logging into ACR...
call az acr login --name !ACR_NAME!

echo Rebuilding Frontend with Build Args...
call docker build --build-arg NEXT_PUBLIC_API_URL=https://!SWARM_BACKEND_URL! --build-arg NEXT_PUBLIC_WS_URL=wss://!SWARM_BACKEND_URL! -t !ACR_NAME!.azurecr.io/swarm-frontend:latest ./frontend

echo Pushing Image...
call docker push !ACR_NAME!.azurecr.io/swarm-frontend:latest

echo Updating Frontend Container App to pull new image...
call az containerapp update --name ca-swarm-frontend --resource-group %RG_NAME% --image !ACR_NAME!.azurecr.io/swarm-frontend:latest --set-env-vars NEXT_PUBLIC_API_URL=https://!SWARM_BACKEND_URL! NEXT_PUBLIC_WS_URL=wss://!SWARM_BACKEND_URL! BASIC_AUTH_USER=admin BASIC_AUTH_PASSWORD=swarm2026

echo Done!
