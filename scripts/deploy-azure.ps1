<#
  Manual deploy to AKS (the GitHub Actions workflow does the same thing on every push).
  Run from the repo root after `terraform apply`:

      .\scripts\deploy-azure.ps1            # build locally with Docker Desktop
      .\scripts\deploy-azure.ps1 -AcrBuild  # build in Azure (ACR Tasks) - no local Docker needed,
                                            # but ACR Tasks may be disabled on free/student subscriptions
#>
param(
    [switch]$AcrBuild,
    [string]$Tag = (Get-Date -Format "yyyyMMdd-HHmmss")
)
$ErrorActionPreference = "Stop"

$tf = Join-Path $PSScriptRoot "..\terraform"
$rg  = terraform -chdir="$tf" output -raw resource_group
$aks = terraform -chdir="$tf" output -raw aks_name
$acr = terraform -chdir="$tf" output -raw acr_name
$image = "$acr.azurecr.io/product-service:$Tag"

Write-Host "Building $image"
if ($AcrBuild) {
    az acr build --registry $acr --image "product-service:$Tag" (Join-Path $PSScriptRoot "..\app")
} else {
    az acr login --name $acr
    docker build -t $image (Join-Path $PSScriptRoot "..\app")
    docker push $image
}
if (-not $?) { throw "image build/push failed" }

az aks get-credentials --resource-group $rg --name $aks --overwrite-existing

$rendered = Join-Path $env:TEMP "flash-sale-k8s"
New-Item -ItemType Directory -Force $rendered | Out-Null
Copy-Item (Join-Path $PSScriptRoot "..\k8s\*.yaml") $rendered -Force
$dep = Join-Path $rendered "10-deployment.yaml"
(Get-Content $dep -Raw) `
    -replace "image: product-service:local", "image: $image" `
    -replace "imagePullPolicy: IfNotPresent", "imagePullPolicy: Always" `
    -replace 'value: "v1"', "value: `"$Tag`"" |
    Set-Content $dep -Encoding utf8

kubectl apply -f $rendered
kubectl -n flash-sale rollout status deployment/product-service --timeout=300s
kubectl -n flash-sale get pods,svc,hpa -o wide

Write-Host "`nWaiting for the load balancer public IP..."
for ($i = 0; $i -lt 30; $i++) {
    $ip = kubectl -n flash-sale get svc product-service -o jsonpath="{.status.loadBalancer.ingress[0].ip}"
    if ($ip) { Write-Host "Product Service: http://$ip/products"; break }
    Start-Sleep -Seconds 10
}
