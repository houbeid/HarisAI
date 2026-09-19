# test-webhook.ps1
# Envoie un vrai webhook signe HMAC vers fraud-backend, pour valider
# le pipeline complet en conditions reelles : .NET -> FastAPI -> reponse.
#
# Prerequis :
#   1. fraud-ml-service tourne sur FastApi:BaseUrl (voir appsettings.Development.json)
#   2. fraud-backend API tourne (dotnet run --project src/FraudDetection.API)
#   3. OperatorSecrets:BANKILY est configure dans appsettings.Development.json
#   4. Redis et PostgreSQL sont demarres (docker start harisai-redis / harisai-migration-db)
#
# Usage :
#   .\test-webhook.ps1                  -> transaction normale (APPROVE attendu)
#   .\test-webhook.ps1 -Suspicious       -> transaction suspecte (REVIEW/BLOCK attendu,
#                                            genere une vraie alerte dans le dashboard)

param(
    [switch]$Suspicious
)

# --- Configuration - doit correspondre exactement a appsettings.Development.json ---
$ApiUrl = "http://localhost:5000/webhook"   # ajuster selon le port reel de l'API
$OperatorCode = "BANKILY"                    # doit etre un operateur reel accepte
                                              # par fraud-ml-service (BANKILY/SEDAD/MASRVI)
                                              # - "TEST" est rejete par la validation
                                              # Pydantic cote Python, voir echange precedent
$Secret = "dev-only-hmac-secret-never-use-in-production-32c"  # OperatorSecrets:BANKILY

# --- Corps du webhook - format attendu par GenericMobileMoneyWebhookAdapter ---
if ($Suspicious) {
    Write-Host "Mode SUSPICIOUS - transaction concue pour declencher REVIEW/BLOCK" -ForegroundColor Magenta
    Write-Host "(sim_changed_72h=true est le signal le plus discriminant du modele" -ForegroundColor DarkGray
    Write-Host " XGBoost - distance de Cohen 2.45, voir doc technique chapitre 6)" -ForegroundColor DarkGray
    Write-Host ""

    $BodyObject = @{
        transaction_id           = "SUSPECT-$(Get-Date -Format 'yyyyMMddHHmmss')"
        client_phone              = "22233445566"
        amount                     = 250000          # montant nettement plus eleve que la normale
        channel                    = "MOBILE_APP"
        zone                       = "ROSSO"           # zone differente de l'exemple normal
        device_id                  = "hash-device-jamais-vu-avant"
        sim_changed_72h             = $true            # signal principal
        beneficiary_phone           = "22299887766"
        beneficiary_is_merchant      = $false
        timestamp                   = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    }
}
else {
    $BodyObject = @{
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
    }
}

$Body = $BodyObject | ConvertTo-Json -Compress

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

    if ($response.decision -in @("REVIEW", "BLOCK")) {
        Write-Host ""
        Write-Host "Une alerte a du etre creee - verifie le dashboard (GET /alerts)." -ForegroundColor Green
    }
    elseif ($Suspicious) {
        Write-Host ""
        Write-Host "Decision = $($response.decision) malgre le mode Suspicious -" -ForegroundColor Yellow
        Write-Host "le score n'a peut-etre pas depasse le seuil REVIEW (40) cette fois." -ForegroundColor Yellow
    }
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