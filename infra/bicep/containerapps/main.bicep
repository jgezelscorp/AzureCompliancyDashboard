// OPTIONAL reference template for running Azure Compliancy Dashboard on Azure Container Apps.
// Not deployed by this repository. Review, parameterise and what-if before any use.
// Postgres is external (e.g. Azure Database for PostgreSQL Flexible Server); pass its URL as a secure parameter.
targetScope = 'resourceGroup'

@description('Prefix for resource names.')
param namePrefix string = 'acd'
param location string = resourceGroup().location

@description('Container image for the API and worker, e.g. <registry>/acd-backend:<tag>.')
param backendImage string
@description('Container image for the web front end.')
param frontendImage string

@secure()
@description('SQLAlchemy URL, e.g. postgresql+psycopg://user:pass@host:5432/acd?sslmode=require. Stored as a Container Apps secret.')
param databaseUrl string

@description('Entra tenant ID hosting the monitored subscriptions.')
param tenantId string = '00000000-0000-0000-0000-000000000000'
@description('Comma-separated subscription IDs the collector may read.')
param subscriptionIds string = '00000000-0000-0000-0000-000000000000'
param authApiClientId string = '00000000-0000-0000-0000-000000000000'
param authSpaClientId string = '00000000-0000-0000-0000-000000000000'
@description('Allowed browser origin for CORS (the front end URL).')
param corsOrigin string

@description('Existing Log Analytics workspace for container logs.')
param logAnalyticsWorkspaceName string

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsWorkspaceName
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${namePrefix}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
  }
}

var commonEnv = [
  { name: 'ACD_ENVIRONMENT', value: 'production' }
  { name: 'ACD_DATABASE_URL', secretRef: 'database-url' }
  { name: 'ACD_TENANT_ID', value: tenantId }
  { name: 'ACD_SUBSCRIPTION_IDS', value: subscriptionIds }
  { name: 'ACD_CORS_ORIGINS', value: corsOrigin }
  { name: 'ACD_AUTH_TENANT_ID', value: tenantId }
  { name: 'ACD_AUTH_API_CLIENT_ID', value: authApiClientId }
  { name: 'ACD_AUTH_SPA_CLIENT_ID', value: authSpaClientId }
  { name: 'ACD_AUTH_COLLECTOR_MODE', value: 'managed_identity' }
]

resource backend 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${namePrefix}-api'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: { external: false, targetPort: 8000, transport: 'http' }
      secrets: [{ name: 'database-url', value: databaseUrl }]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: backendImage
          env: commonEnv
          resources: { cpu: json('0.5'), memory: '1Gi' }
          probes: [
            { type: 'Liveness', httpGet: { path: '/healthz', port: 8000 }, periodSeconds: 15 }
            { type: 'Readiness', httpGet: { path: '/readyz', port: 8000 }, periodSeconds: 10 }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 3 }
    }
  }
}

// One worker replica: collection runs are also serialised by a database advisory lock.
resource worker 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${namePrefix}-worker'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      secrets: [{ name: 'database-url', value: databaseUrl }]
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
}

resource frontend 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${namePrefix}-web'
  location: location
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: { external: true, targetPort: 8080, transport: 'http', allowInsecure: false }
    }
    template: {
      containers: [
        {
          name: 'web'
          image: frontendImage
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 3 }
    }
  }
}

output webFqdn string = frontend.properties.configuration.ingress.fqdn
output apiPrincipalId string = backend.identity.principalId
output workerPrincipalId string = worker.identity.principalId
