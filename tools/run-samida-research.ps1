$apiUrl = 'http://127.0.0.1:8000/api/research/run?research_type=ai_general'
$requestId = [guid]::NewGuid().ToString()

for ($attempt = 1; $attempt -le 12; $attempt++) {
    try {
        Invoke-RestMethod -Uri $apiUrl -Method Post -Headers @{ 'Idempotency-Key' = $requestId } -TimeoutSec 180 | Out-Null
        exit 0
    } catch {
        if ($attempt -eq 12) {
            exit 1
        }
        Start-Sleep -Seconds 10
    }
}
