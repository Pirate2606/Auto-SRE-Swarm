@echo off
setlocal EnableDelayedExpansion

:: Configuration
set RG_NAME=rg-sre-swarm-foundry
set LOCATION=eastus2
set WORKSPACE_NAME=law-autosre-swarm
set APPINSIGHTS_NAME=appi-autosre-swarm
set ACA_ENV=cae-autosre-swarm
set CHAOS_APP_NAME=ca-chaos-target
set SWARM_APP_NAME=ca-swarm-backend
set ACR_NAME=acrautosre%RANDOM%

echo =================================================
echo  Deploying Auto-SRE Swarm Infrastructure to Azure 
echo =================================================

echo [0/7] Registering Azure Providers (may take a minute)...
call az provider register -n Microsoft.App --wait
call az provider register -n Microsoft.ContainerRegistry --wait

echo [1/7] Ensuring Resource Group exists: %RG_NAME%...
call az group create --name %RG_NAME% --location %LOCATION% --output none

echo [2/7] Creating Log Analytics Workspace: %WORKSPACE_NAME%...
call az monitor log-analytics workspace create --resource-group %RG_NAME% --workspace-name %WORKSPACE_NAME% --output none
for /f "tokens=*" %%i in ('az monitor log-analytics workspace show --resource-group %RG_NAME% --workspace-name %WORKSPACE_NAME% --query id -o tsv') do set WORKSPACE_ID=%%i
for /f "tokens=*" %%i in ('az monitor log-analytics workspace show --resource-group %RG_NAME% --workspace-name %WORKSPACE_NAME% --query customerId -o tsv') do set WORKSPACE_CUSTOMER_ID=%%i
for /f "tokens=*" %%i in ('az monitor log-analytics workspace get-shared-keys --resource-group %RG_NAME% --workspace-name %WORKSPACE_NAME% --query primarySharedKey -o tsv') do set WORKSPACE_KEY=%%i

echo [3/7] Creating Application Insights...
call az monitor app-insights component create --app %APPINSIGHTS_NAME% --location %LOCATION% --kind web --resource-group %RG_NAME% --workspace !WORKSPACE_ID! --output none
for /f "tokens=*" %%i in ('az monitor app-insights component show --app %APPINSIGHTS_NAME% --resource-group %RG_NAME% --query instrumentationKey -o tsv') do set APPINSIGHTS_INSTRUMENTATION_KEY=%%i

echo [4/7] Creating Azure Container Registry ^& ACA Environment...
call az acr create --name %ACR_NAME% --resource-group %RG_NAME% --sku Basic --admin-enabled true --output none
for /f "tokens=*" %%i in ('az acr credential show --name %ACR_NAME% --query "passwords[0].value" -o tsv') do set ACR_PASSWORD=%%i

call az containerapp env create --name %ACA_ENV% --resource-group %RG_NAME% --location %LOCATION% --logs-workspace-id !WORKSPACE_CUSTOMER_ID! --logs-workspace-key !WORKSPACE_KEY! --output none

echo Logging into ACR via local Docker...
call az acr login --name %ACR_NAME%

echo [5/7] Building and Deploying Chaos App from source...
call docker build -t %ACR_NAME%.azurecr.io/chaos-app:latest ./chaos-app
call docker push %ACR_NAME%.azurecr.io/chaos-app:latest
call az containerapp create --name %CHAOS_APP_NAME% --resource-group %RG_NAME% --environment %ACA_ENV% --image %ACR_NAME%.azurecr.io/chaos-app:latest --target-port 8000 --ingress external --registry-server %ACR_NAME%.azurecr.io --registry-username %ACR_NAME% --registry-password !ACR_PASSWORD! --env-vars APPINSIGHTS_INSTRUMENTATIONKEY=!APPINSIGHTS_INSTRUMENTATION_KEY!
for /f "tokens=*" %%i in ('az containerapp show --name %CHAOS_APP_NAME% --resource-group %RG_NAME% --query properties.configuration.ingress.fqdn -o tsv') do set CHAOS_APP_URL=%%i

echo [6/7] Configuring Azure Monitor Alerts (Action Group ^& Rule)...
set ACTION_GROUP_NAME=ag-autosre-webhook
set PLACEHOLDER_WEBHOOK=https://httpbin.org/post

call az monitor action-group create --name !ACTION_GROUP_NAME! --resource-group %RG_NAME% --short-name "SRE-Swarm" --action webhook MyWebhook !PLACEHOLDER_WEBHOOK! useaadi=false --output none
for /f "tokens=*" %%i in ('az monitor action-group show --name !ACTION_GROUP_NAME! --resource-group %RG_NAME% --query id -o tsv') do set AG_ID=%%i
for /f "tokens=*" %%i in ('az containerapp show --name %CHAOS_APP_NAME% --resource-group %RG_NAME% --query id -o tsv') do set CHAOS_APP_ID=%%i

echo Creating High CPU Alert...
call az monitor metrics alert create --name "Alert-Chaos-HighCPU" --resource-group %RG_NAME% --scopes !CHAOS_APP_ID! --condition "avg UsageNanoCores > 800000000" --window-size 5m --evaluation-frequency 1m --action !AG_ID! --description "CPU exceeded 80%% on Chaos App" --output none

echo Creating High Memory Alert...
call az monitor metrics alert create --name "Alert-Chaos-HighMemory" --resource-group %RG_NAME% --scopes !CHAOS_APP_ID! --condition "avg WorkingSetBytes > 100000000" --window-size 5m --evaluation-frequency 1m --action !AG_ID! --description "Memory exceeded 100MB on Chaos App" --output none

echo =================================================
echo  Phase 1 Complete!
echo  Chaos App is running at: https://!CHAOS_APP_URL!
echo  Webhook placeholder is set. Next step: Deploy Swarm backend.
echo =================================================

echo =================================================
echo  Phase 3: Deploying Swarm Backend ^& Frontend 
echo =================================================

echo Building and deploying Backend...
call docker build -t %ACR_NAME%.azurecr.io/swarm-backend:latest ./backend
call docker push %ACR_NAME%.azurecr.io/swarm-backend:latest
call az containerapp create --name %SWARM_APP_NAME% --resource-group %RG_NAME% --environment %ACA_ENV% --image %ACR_NAME%.azurecr.io/swarm-backend:latest --target-port 8000 --ingress external --registry-server %ACR_NAME%.azurecr.io --registry-username %ACR_NAME% --registry-password !ACR_PASSWORD! --env-vars AZURE_WORKSPACE_ID=!WORKSPACE_ID! --system-assigned
for /f "tokens=*" %%i in ('az containerapp show --name %SWARM_APP_NAME% --resource-group %RG_NAME% --query properties.configuration.ingress.fqdn -o tsv') do set SWARM_BACKEND_URL=%%i

echo Granting Backend Managed Identity access to Log Analytics...
for /f "tokens=*" %%i in ('az containerapp identity show --name %SWARM_APP_NAME% --resource-group %RG_NAME% --query principalId -o tsv') do set BACKEND_PRINCIPAL_ID=%%i
call az role assignment create --assignee !BACKEND_PRINCIPAL_ID! --role "Log Analytics Reader" --scope !WORKSPACE_ID! --output none

echo Building and deploying Frontend...
call docker build -t %ACR_NAME%.azurecr.io/swarm-frontend:latest ./frontend
call docker push %ACR_NAME%.azurecr.io/swarm-frontend:latest
call az containerapp create --name ca-swarm-frontend --resource-group %RG_NAME% --environment %ACA_ENV% --image %ACR_NAME%.azurecr.io/swarm-frontend:latest --target-port 3000 --ingress external --registry-server %ACR_NAME%.azurecr.io --registry-username %ACR_NAME% --registry-password !ACR_PASSWORD! --env-vars NEXT_PUBLIC_API_URL=https://!SWARM_BACKEND_URL! NEXT_PUBLIC_WS_URL=wss://!SWARM_BACKEND_URL! BASIC_AUTH_USER=admin BASIC_AUTH_PASSWORD=swarm2026
for /f "tokens=*" %%i in ('az containerapp show --name ca-swarm-frontend --resource-group %RG_NAME% --query properties.configuration.ingress.fqdn -o tsv') do set SWARM_FRONTEND_URL=%%i

echo Updating Azure Monitor Webhook to point to Backend...
call az monitor action-group update --name !ACTION_GROUP_NAME! --resource-group %RG_NAME% --set webhook_receivers[0].serviceUri=https://!SWARM_BACKEND_URL!/api/webhook/azure-monitor --output none

echo =================================================
echo  DEPLOYMENT COMPLETE! 
echo  Swarm UI: https://!SWARM_FRONTEND_URL! (Login: admin / swarm2026)
echo  Chaos App: https://!CHAOS_APP_URL!
echo =================================================
