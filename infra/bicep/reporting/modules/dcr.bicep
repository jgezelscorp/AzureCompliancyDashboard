param dcrName string
param location string
param workspaceResourceId string
param tables array
param streamPrefix string
param deployDataCollectionEndpoint bool
param dceName string
param ingestionPrincipalObjectId string

var monitoringMetricsPublisher = '3913510d-42f4-4e42-8a64-420c390055eb'

resource dce 'Microsoft.Insights/dataCollectionEndpoints@2023-03-11' = if (deployDataCollectionEndpoint) {
  name: dceName
  location: location
  properties: {
    networkAcls: { publicNetworkAccess: 'Enabled' }
  }
}

resource dcr 'Microsoft.Insights/dataCollectionRules@2023-03-11' = {
  name: dcrName
  location: location
  kind: 'Direct'
  properties: {
    dataCollectionEndpointId: deployDataCollectionEndpoint ? dce.id : null
    streamDeclarations: toObject(tables, t => '${streamPrefix}${t.name}', t => {
      columns: map(t.columns, c => {
        name: c.name
        type: c.type
      })
    })
    destinations: {
      logAnalytics: [
        {
          name: 'reportingWorkspace'
          workspaceResourceId: workspaceResourceId
        }
      ]
    }
    dataFlows: [for t in tables: {
      streams: ['${streamPrefix}${t.name}']
      destinations: ['reportingWorkspace']
      transformKql: 'source'
      outputStream: '${streamPrefix}${t.name}'
    }]
  }
}

resource publisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(ingestionPrincipalObjectId)) {
  name: guid(dcr.id, ingestionPrincipalObjectId, monitoringMetricsPublisher)
  scope: dcr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringMetricsPublisher)
    principalId: ingestionPrincipalObjectId
    principalType: 'ServicePrincipal'
  }
}

output immutableId string = dcr.properties.immutableId
output ingestionEndpoint string = deployDataCollectionEndpoint ? dce!.properties.logsIngestion.endpoint : dcr.properties.endpoints.logsIngestion
