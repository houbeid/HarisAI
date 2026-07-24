# test-webhook.ps1
# Envoie un vrai webhook signe HMAC vers fraud-backend, pour valider
# le pipeline complet en conditions reelles : .NET -> FastAPI -> reponse.
#
# Prerequis :
#   1. fraud-ml-service tourne sur FastApi:BaseUrl (voir appsettings.Development.json)
#   2. fraud-backend API tourne (dotnet run --project src/FraudDetection.API)
#   3. OperatorSecrets:TEST est configure dans appsettings.Development.json
#
# Usage : .\test-webhook.ps1

# --- Configuration - doit correspondre exactement a appsettings.Development.json ---
$ApiUrl = "http://localhost:5000/webhook"   # ajuster selon le port reel de l'API
$OperatorCode = "TEST"
$Secret = "dev-only-hmac-secret-never-use-in-production-32c"  # OperatorSecrets:TEST

# --- Corps du webhook - format attendu par GenericMobileMoneyWebhookAdapter ---
$Body = @{
    transaction_id           = "TEST-$(Get-Date -Format 'yyyyMMddHHmmss')"
    client_phone              = "22233445566"
    amount                     = 47000
    channel                    = "MOBILE_APP"
    zone                       = "NOUAKCHOTT"
    device_id                  = "test-device-integration-001"
    sim_changed_72h             = $false
    beneficiary_phone           = "22299887766"
    beneficiary_is_merchant      = $false
    timestamp                   = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
} | ConvertTo-Json -Compress

Write-Host "Corps du webhook :" -ForegroundColor Cyan
Write-Host $Body
Write-Host ""

# --- Calcul de la signature HMAC-SHA256 - DOIT reproduire exactement ---
# --- HmacAuthenticationHandler.ComputeHmacSha256() :                  ---
# --- signedPayload = "{timestamp_unix}.{rawBody}"                     ---
$TimestampUnix = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$SignedPayload = "$TimestampUnix.$Body"

$hmac = New-Object System.Security.Cryptography.HMACSHA256
$hmac.Key = [System.Text.Encoding]::UTF8.GetBytes($Secret)
$hashBytes = $hmac.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($SignedPayload))
$Signature = [System.BitConverter]::ToString($hashBytes).Replace("-", "").ToLower()

Write-Host "Timestamp Unix : $TimestampUnix" -ForegroundColor Cyan
Write-Host "Signature HMAC : $Signature" -ForegroundColor Cyan
Write-Host ""

# --- Envoi de la requete ---
$Headers = @{
    "X-Operator-Code" = $OperatorCode
    "X-Signature"      = $Signature
    "X-Timestamp"       = $TimestampUnix.ToString()
    "Content-Type"       = "application/json"
}

Write-Host "Envoi du webhook vers $ApiUrl ..." -ForegroundColor Yellow

try {
    $response = Invoke-RestMethod -Uri $ApiUrl -Method Post -Headers $Headers -Body $Body -ErrorAction Stop
    Write-Host ""
    Write-Host "SUCCES - reponse recue :" -ForegroundColor Green
    $response | ConvertTo-Json -Depth 5
}
catch {
    Write-Host ""
    Write-Host "ECHEC :" -ForegroundColor Red
    Write-Host $_.Exception.Message
    if ($_.ErrorDetails) {
        Write-Host "Details :" -ForegroundColor Red
        Write-Host $_.ErrorDetails.Message
    }
}