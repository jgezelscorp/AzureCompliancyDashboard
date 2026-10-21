// Azure Compliancy Dashboard on Azure Container Apps (consumption). Resource-group scope.
// Review with `az deployment group what-if` before every create. Nothing here contains IDs or secrets.
//
// Two-phase deployment (see docs/operations.md):
//   1. deployApps = false: identities, VNet, Key Vault, ACR, private PostgreSQL, Container Apps environment.
//      Then build images with `az acr build` and set the Key Vault secret `api-client-secret`.
//   2. deployApps = true: migration job, API (internal), worker, web (public, TLS).
// Postgres is reachable only through the VNet (private access); only the web app has public ingress.
targetScope = 'resourceGroup'

@description('Prefix for resource names (lowercase letters and digits).')
@minLength(2)
@maxLength(8)
param namePrefix string = 'acd'
param location string = resourceGroup().location

@description('Deploy the container apps and migration job (phase 2). Requires images in the registry and the Key Vault secret api-client-secret.')
param deployApps bool = false

@description('Backend image, e.g. <registry>.azurecr.io/acd-backend:<tag>. Required when deployApps is true.')
param backendImage string = ''
@description('Frontend image, e.g. <registry>.azurecr.io/acd-frontend:<tag>. Required when deployApps is true.')
param frontendImage string = ''

@description('Entra tenant ID hosting the monitored subscriptions.')
param tenantId string = '00000000-0000-0000-0000-000000000000'
@description('Comma-separated subscription IDs the collector may read.')
param subscriptionIds string = '00000000-0000-0000-0000-000000000000'
param authApiClientId string = '00000000-0000-0000-0000-000000000000'
param authSpaClientId string = '00000000-0000-0000-0000-000000000000'

@description('Existing Log Analytics workspace (same resource group) for container logs.')
param logAnalyticsWorkspaceName string

@description('Optional Logs Ingestion endpoint (ACD_LOGS_INGESTION_ENDPOINT). Empty leaves the history sink disabled.')
param logsIngestionEndpoint string = ''
@description('Optional DCR immutable id (ACD_LOGS_DCR_IMMUTABLE_ID).')
param logsDcrImmutableId string = ''

@description('PostgreSQL administrator login.')
param pgAdminLogin string = 'acdadmin'
@secure()
@description('PostgreSQL administrator password (letters and digits only, so it can be embedded in the URL). Stored only in Key Vault.')
param pgAdminPassword string
@description('PostgreSQL compute SKU (Burstable).')
param pgSkuName string = 'Standard_B1ms'
param pgStorageGb int = 32

@description('Optional CIDR allow-list for the public web ingress. Empty allows all (the API still requires Entra sign-in).')
param webAllowedCidrs array = []

var uniq = uniqueString(resourceGroup().id)
var acrName = '${namePrefix}acr${uniq}'
var kvName = '${namePrefix}-kv-${take(uniq, 6)}'
var pgName = '${namePrefix}-pg-${uniq}'
var pgDnsZone = '${namePrefix}-${take(uniq, 6)}.private.postgres.database.azure.com'
var dbName = 'acd'

var acrPullRole = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var kvSecretsUserRole = '4633458b-17de-408a-b874-0445c86b69e6'

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsWorkspaceName
}

resource apiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-api-id'
  location: location
}

// Collector identity: used by the worker (and migration job). Receives Reader on the monitored
// subscriptions via rbac-subscription.bicep and Monitoring Metrics Publisher on the DCR.
resource collectorIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-collector-id'
  location: location
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  properties: {
    tenantId: tenant().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
}

resource acrPullApi 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, apiIdentity.id, acrPullRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRole)
    principalId: apiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource acrPullCollector 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, collectorIdentity.id, acrPullRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRole)
    principalId: collectorIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource kvUserApi 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, apiIdentity.id, kvSecretsUserRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsUserRole)
    principalId: apiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource kvUserCollector 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, collectorIdentity.id, kvSecretsUserRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsUserRole)
    principalId: collectorIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: '${namePrefix}-vnet'
  location: location
  properties: {
    addressSpace: { addressPrefixes: ['10.20.0.0/16'] }
    subnets: [
      {
        name: 'aca'
        properties: {
          addressPrefix: '10.20.0.0/26'
          delegations: [
            { name: 'aca', properties: { serviceName: 'Microsoft.App/environments' } }
          ]
        }
      }
      {
        name: 'pg'
        properties: {
          addressPrefix: '10.20.1.0/28'
          delegations: [
            { name: 'pg', properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' } }
          ]
        }
      }
    ]
  }
}

resource pgZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: pgDnsZone
  location: 'global'
}

resource pgZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: pgZone
  name: '${namePrefix}-vnet-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2023-12-01-preview' = {
  name: pgName
  location: location
  sku: { name: pgSkuName, tier: 'Burstable' }
  properties: {
    version: '16'
    administratorLogin: pgAdminLogin
    administratorLoginPassword: pgAdminPassword
    storage: { storageSizeGB: pgStorageGb }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: {
      delegatedSubnetResourceId: '${vnet.id}/subnets/pg'
      privateDnsZoneArmResourceId: pgZone.id
      publicNetworkAccess: 'Disabled'
    }
  }
  dependsOn: [pgZoneLink]
}

resource pgDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-12-01-preview' = {
  parent: pg
  name: dbName
}

resource databaseUrlSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'database-url'
  properties: {
    value: 'postgresql+psycopg://${pgAdminLogin}:${pgAdminPassword}@${pg.properties.fullyQualifiedDomainName}:5432/${dbName}?sslmode=require'
  }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${namePrefix}-env'
  location: location
  properties: {
    vnetConfiguration: {
      infrastructureSubnetId: '${vnet.id}/subnets/aca'
      internal: false
    }
    workloadProfiles: [
      { name: 'Consumption', workloadProfileType: 'Consumption' }
    ]
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
  }
}

var webOrigin = 'https://${namePrefix}-web.${env.properties.defaultDomain}'
var logsSinkEnabled = !empty(logsIngestionEndpoint) && !empty(logsDcrImmutableId)

var commonEnv = concat(
  [
    { name: 'ACD_ENVIRONMENT', value: 'production' }
    { name: 'ACD_DATABASE_URL', secretRef: 'database-url' }
    { name: 'ACD_TENANT_ID', value: tenantId }
    { name: 'ACD_SUBSCRIPTION_IDS', value: subscriptionIds }
    { name: 'ACD_CORS_ORIGINS', value: webOrigin }
    { name: 'ACD_AUTH_TENANT_ID', value: tenantId }
    { name: 'ACD_AUTH_API_CLIENT_ID', value: authApiClientId }
    { name: 'ACD_AUTH_SPA_CLIENT_ID', value: authSpaClientId }
    { name: 'ACD_AUTH_COLLECTOR_MODE', value: 'managed_identity' }
    { name: 'ACD_AUTH_COLLECTOR_CLIENT_ID', value: collectorIdentity.properties.clientId }
    { name: 'ACD_AUTH_COLLECTOR_TENANT_ID', value: tenantId }
    { name: 'AZURE_CLIENT_ID', value: collectorIdentity.properties.clientId }
  ],
  logsSinkEnabled
    ? [
        { name: 'ACD_LOGS_SINK_ENABLED', value: 'true' }
        { name: 'ACD_LOGS_INGESTION_ENDPOINT', value: logsIngestionEndpoint }
        { name: 'ACD_LOGS_DCR_IMMUTABLE_ID', value: logsDcrImmutableId }
      ]
    : []
)

var apiEnv = concat(
  filter(commonEnv, e => e.name != 'AZURE_CLIENT_ID'),
  [{ name: 'ACD_AUTH_API_CLIENT_SECRET', secretRef: 'api-client-secret' }]
)

var kvSecretsApi = [
  { name: 'database-url', keyVaultUrl: '${kv.properties.vaultUri}secrets/database-url', identity: apiIdentity.id }
  { name: 'api-client-secret', keyVaultUrl: '${kv.properties.vaultUri}secrets/api-client-secret', identity: apiIdentity.id }
]
var kvSecretsCollector = [
  { name: 'database-url', keyVaultUrl: '${kv.properties.vaultUri}secrets/database-url', identity: collectorIdentity.id }
]

resource migrate 'Microsoft.App/jobs@2024-03-01' = if (deployApps) {
  name: '${namePrefix}-migrate'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${collectorIdentity.id}': {} }
  }
  properties: {
    environmentId: env.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 600
      replicaRetryLimit: 1
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      secrets: kvSecretsCollector
      registries: [{ server: acr.properties.loginServer, identity: collectorIdentity.id }]
    }
    template: {
      containers: [
        {
          name: 'migrate'
          image: backendImage
          command: ['alembic', 'upgrade', 'head']
          env: commonEnv
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
        }
      ]
    }
  }
  dependsOn: [acrPullCollector, kvUserCollector, databaseUrlSecret, pgDatabase]
}

resource backend 'Microsoft.App/containerApps@2024-03-01' = if (deployApps) {
  name: '${namePrefix}-api'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${apiIdentity.id}': {} }
  }
  properties: {
    managedEnvironmentId: env.id
    workloadProfileName: 'Consumption'
    configuration: {
      // Internal only: reached by the web app inside the environment over plain HTTP, never exposed publicly.
      ingress: { external: false, targetPort: 8000, transport: 'http', allowInsecure: true }
      secrets: kvSecretsApi
      registries: [{ server: acr.properties.loginServer, identity: apiIdentity.id }]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: backendImage
          env: apiEnv
          resources: { cpu: json('0.5'), memory: '1Gi' }
          probes: [
            { type: 'Liveness', httpGet: { path: '/healthz', port: 8000 }, periodSeconds: 15 }
            { type: 'Readiness', httpGet: { path: '/readyz', port: 8000 }, periodSeconds: 10 }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 2 }
    }
  }
  dependsOn: [acrPullApi, kvUserApi, databaseUrlSecret]
}

// One worker replica: collection runs are also serialised by a database advisory lock.
resource worker 'Microsoft.App/containerApps@2024-03-01' = if (deployApps) {
  name: '${namePrefix}-worker'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${collectorIdentity.id}': {} }
  }
  properties: {
    managedEnvironmentId: env.id
    workloadProfileName: 'Consumption'
    configuration: {
      secrets: kvSecretsCollector
      registries: [{ server: acr.properties.loginServer, identity: collectorIdentity.id }]
    }
    template: {
      containers: [
        {
          name: 'worker'
          image: backendImage
          command: ['python', '-m', 'app.collectors']
          env: commonEnv
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
  dependsOn: [acrPullCollector, kvUserCollector, databaseUrlSecret]
}

resource frontend 'Microsoft.App/containerApps@2024-03-01' = if (deployApps) {
  name: '${namePrefix}-web'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${apiIdentity.id}': {} }
  }
  properties: {
    managedEnvironmentId: env.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: {
        external: true
        targetPort: 8080
        transport: 'http'
        allowInsecure: false
        ipSecurityRestrictions: [
          for (cidr, i) in webAllowedCidrs: {
            name: 'allow-${i}'
            action: 'Allow'
            ipAddressRange: cidr
          }
        ]
      }
      registries: [{ server: acr.properties.loginServer, identity: apiIdentity.id }]
    }
    template: {
      containers: [
        {
          name: 'web'
          image: frontendImage
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          probes: [
            { type: 'Liveness', httpGet: { path: '/', port: 8080 }, periodSeconds: 30 }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 2 }
    }
  }
  dependsOn: [acrPullApi, backend]
}

output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output keyVaultName string = kv.name
output postgresServerName string = pg.name
output environmentDefaultDomain string = env.properties.defaultDomain
output webFqdn string = '${namePrefix}-web.${env.properties.defaultDomain}'
output collectorPrincipalId string = collectorIdentity.properties.principalId
output collectorClientId string = collectorIdentity.properties.clientId
output apiPrincipalId string = apiIdentity.properties.principalId
output migrateJobName string = deployApps ? migrate.name : ''
