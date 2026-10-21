// Deploys the live compliance workbook as a shared Azure Workbook into a resource group.
// Subscription / resource-group scope of the DATA is chosen in the workbook parameters at run
// time; nothing is hard-coded. Read-only reporting: the workbook only runs Resource Graph queries.
targetScope = 'resourceGroup'

@description('Display name shown in the Azure Monitor workbooks gallery.')
param workbookDisplayName string = 'Azure Policy and Machine Configuration compliance (live)'

@description('Region for the workbook resource (the resource group location by default).')
param location string = resourceGroup().location

@description('Stable workbook resource name (GUID). Keep the default so redeployment updates the same workbook.')
param workbookName string = guid(resourceGroup().id, 'azure-compliance-dashboard-live-workbook')

@description('Tags applied to the workbook resource.')
param tags object = {}

var serializedData = loadTextContent('../../../workbooks/azure-compliance.workbook.json')

resource workbook 'Microsoft.Insights/workbooks@2023-06-01' = {
  name: workbookName
  location: location
  kind: 'shared'
  tags: tags
  properties: {
    displayName: workbookDisplayName
    category: 'workbook'
    version: 'Notebook/1.0'
    sourceId: 'Azure Monitor'
    serializedData: serializedData
  }
}

output workbookResourceId string = workbook.id
