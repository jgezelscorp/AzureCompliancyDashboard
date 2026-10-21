using 'main.bicep'

param createWorkspace = false
param workspaceName = 'law-example'
param existingWorkspaceResourceGroup = 'rg-example'
param retentionDays = 400
param deployDataCollectionEndpoint = false
// Collector identity object id (placeholder).
param ingestionPrincipalObjectId = '00000000-0000-0000-0000-000000000000'
