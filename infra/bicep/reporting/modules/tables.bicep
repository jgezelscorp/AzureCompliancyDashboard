param workspaceName string
param tables array
param retentionDays int

resource workspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' existing = {
  name: workspaceName
}

resource customTables 'Microsoft.OperationalInsights/workspaces/tables@2022-10-01' = [for t in tables: {
  parent: workspace
  name: t.name
  properties: {
    plan: 'Analytics'
    retentionInDays: retentionDays
    totalRetentionInDays: retentionDays
    schema: {
      name: t.name
      description: t.description
      columns: [for c in t.columns: {
        name: c.name
        type: c.type == 'datetime' ? 'dateTime' : c.type
        description: c.description
      }]
    }
  }
}]
