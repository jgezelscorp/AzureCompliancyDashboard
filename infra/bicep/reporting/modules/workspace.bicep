param create bool
param workspaceName string
param existingResourceGroup string
param location string
param retentionDays int

resource created 'Microsoft.OperationalInsights/workspaces@2022-10-01' = if (create) {
  name: workspaceName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: retentionDays
  }
}

resource existing 'Microsoft.OperationalInsights/workspaces@2022-10-01' existing = if (!create) {
  name: workspaceName
  scope: resourceGroup(existingResourceGroup)
}

output workspaceId string = create ? created.id : existing.id
