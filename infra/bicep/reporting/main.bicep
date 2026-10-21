// Optional enhanced/history mode: custom Log Analytics tables + Direct DCR for the
// collector's Logs Ingestion sink. Independent of infra/bicep/workbook (workbook-only mode)
// and of the app (app-only mode). Resource-group scope. Review with `what-if` before deploying.
targetScope = 'resourceGroup'

@description('Create a new workspace (true) or reference an existing one (false).')
param createWorkspace bool = false

@description('Workspace name (new or existing).')
param workspaceName string

@description('Resource group of an existing workspace. Ignored when createWorkspace is true.')
param existingWorkspaceResourceGroup string = resourceGroup().name

@description('Region for new resources. The DCR must be in the same region as the workspace.')
param location string = resourceGroup().location

@description('Interactive retention in days for every table. 397 days is the minimum that covers 13 months; 30 is the Log Analytics minimum and limits the History tab to about 30 days.')
@minValue(30)
@maxValue(4383)
param retentionDays int = 400

@description('Daily ingestion cap in GB for a NEW workspace (-1 = no cap). Ignored for an existing workspace.')
@minValue(-1)
param dailyQuotaGb int = -1

@description('Name of the data collection rule.')
param dcrName string = 'dcr-compliance-reporting'

@description('Create a data collection endpoint. Direct DCRs expose their own ingestion endpoint, so this is normally false.')
param deployDataCollectionEndpoint bool = false

@description('Name of the data collection endpoint (used only when deployDataCollectionEndpoint is true).')
param dceName string = 'dce-compliance-reporting'

@description('Object id of the collector identity that may write to the DCR. Leave empty to assign nothing.')
param ingestionPrincipalObjectId string = ''

var schema = loadJsonContent('../../../contracts/logs-schema.json')

module workspace 'modules/workspace.bicep' = {
  name: 'reporting-workspace'
  params: {
    create: createWorkspace
    workspaceName: workspaceName
    existingResourceGroup: existingWorkspaceResourceGroup
    location: location
    retentionDays: retentionDays
    dailyQuotaGb: dailyQuotaGb
  }
}

module tables 'modules/tables.bicep' = {
  name: 'reporting-tables'
  scope: resourceGroup(createWorkspace ? resourceGroup().name : existingWorkspaceResourceGroup)
  params: {
    workspaceName: workspaceName
    tables: schema.tables
    retentionDays: retentionDays
  }
  dependsOn: [workspace]
}

module dcr 'modules/dcr.bicep' = {
  name: 'reporting-dcr'
  params: {
    dcrName: dcrName
    location: location
    workspaceResourceId: workspace.outputs.workspaceId
    tables: schema.tables
    streamPrefix: schema.streamPrefix
    deployDataCollectionEndpoint: deployDataCollectionEndpoint
    dceName: dceName
    ingestionPrincipalObjectId: ingestionPrincipalObjectId
  }
  dependsOn: [tables]
}

@description('Immutable id to configure as ACD_LOGS_DCR_IMMUTABLE_ID.')
output dcrImmutableId string = dcr.outputs.immutableId

@description('Ingestion endpoint to configure as ACD_LOGS_INGESTION_ENDPOINT.')
output ingestionEndpoint string = dcr.outputs.ingestionEndpoint

output workspaceResourceId string = workspace.outputs.workspaceId
output retentionDays int = retentionDays
