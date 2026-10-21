// Read-only RBAC for the collector identity on a monitored subscription. Subscription scope.
// Run: az deployment sub what-if -l <region> -f rbac-subscription.bicep -p principalId=<object id>
// Reader (*/read) already covers Microsoft.PolicyInsights/*/read and guest configuration reads, so no
// separate Policy Insights role is assigned by default (Policy Insights Data Writer is a write role).
targetScope = 'subscription'

@description('Object id of the collector identity (output collectorPrincipalId of main.bicep).')
param principalId string

@description('Role definition GUIDs to assign. Default: Reader.')
param roleDefinitionIds array = ['acdd72a7-3385-48ef-bd42-f606fba81ae7']

resource assignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for roleId in roleDefinitionIds: {
  name: guid(subscription().id, principalId, roleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]
