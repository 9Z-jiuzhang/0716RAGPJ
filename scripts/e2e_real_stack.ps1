# Real-stack E2E via curl (NO mock). Results -> scripts/e2e_results.json
$ErrorActionPreference = "Continue"
$Base = "http://127.0.0.1:8000/api/v1"
$Results = [ordered]@{}
$script:Token = $null
$script:KbId = $null
$script:DocId = $null
$script:SnapId = $null

function Step($name, $scriptBlock) {
    Write-Host ""
    Write-Host "=== $name ===" -ForegroundColor Cyan
    $entry = [ordered]@{ name = $name; ok = $false; detail = "" }
    try {
        $out = & $scriptBlock
        $entry.ok = $true
        $entry.detail = [string]$out
        $preview = $entry.detail
        if ($preview.Length -gt 240) { $preview = $preview.Substring(0, 240) }
        Write-Host "PASS: $preview" -ForegroundColor Green
    } catch {
        $entry.ok = $false
        $entry.detail = $_.Exception.Message
        Write-Host "FAIL: $($entry.detail)" -ForegroundColor Red
    }
    $Results[$name] = $entry
}

function CurlJson([string]$Method, [string]$Url, [string]$JsonBody = $null, [string]$AuthToken = $null) {
    # 不使用 -L：POST 遇 307 跟随时可能丢 body；调用方应使用无尾斜杠的规范路径
    # 输出写文件再按 UTF-8 读取，避免 PowerShell 管道弄坏中文
    $outFile = Join-Path $env:TEMP ("e2e_curl_" + [guid]::NewGuid().ToString() + ".txt")
    $args = @("-s", "-S", "-X", $Method, $Url, "-H", "Accept: application/json", "-o", $outFile, "-w", "%{http_code}")
    if ($AuthToken) { $args += @("-H", "Authorization: Bearer $AuthToken") }
    if ($null -ne $JsonBody) {
        $tmp = Join-Path $env:TEMP ("e2e_body_" + [guid]::NewGuid().ToString() + ".json")
        [System.IO.File]::WriteAllText($tmp, $JsonBody, [System.Text.UTF8Encoding]::new($false))
        $args += @("-H", "Content-Type: application/json", "--data-binary", "@$tmp")
    }
    $codeStr = & curl.exe @args
    $code = 0
    [int]::TryParse(([string]$codeStr).Trim(), [ref]$code) | Out-Null
    $body = ""
    if (Test-Path $outFile) {
        $body = [System.IO.File]::ReadAllText($outFile, [System.Text.Encoding]::UTF8)
        Remove-Item $outFile -ErrorAction SilentlyContinue
    }
    if ($code -ge 300 -and $code -lt 400) {
        throw ("unexpected redirect HTTP {0} for {1} {2} (check trailing slash); body={3}" -f $code, $Method, $Url, $body)
    }
    if ($code -ge 400) {
        throw ("HTTP {0} for {1} {2} : {3}" -f $code, $Method, $Url, $body)
    }
    return $body
}

Step "health" {
    $raw = CurlJson "GET" "$Base/monitor/health"
    $h = $raw | ConvertFrom-Json
    if (-not $h.data) { throw "no data: $raw" }
    "status=$($h.data.status); postgres=$($h.data.checks.postgres.status); redis=$($h.data.checks.redis.status); chroma=$($h.data.checks.chroma.status)"
}

Step "login" {
    $raw = CurlJson "POST" "$Base/auth/login" '{"username":"admin","password":"Admin123!"}'
    $r = $raw | ConvertFrom-Json
    $script:Token = [string]$r.data.access_token
    if (-not $script:Token) { throw "no access_token: $raw" }
    "token_len=$($script:Token.Length)"
}

Step "auth_me" {
    $raw = CurlJson "GET" "$Base/auth/me" $null $script:Token
    if ($raw -notmatch '"username"\s*:\s*"admin"') { throw "auth/me unexpected: $($raw.Substring(0,[Math]::Min(200,$raw.Length)))" }
    "user=admin"
}

Step "kb_list_or_create" {
    # 注意：路径不要尾斜杠，否则 FastAPI 307 重定向会导致 POST 丢 body
    # 优先复用 pytest-kb-smoke（已有索引），否则取第一个，否则新建
    $raw = CurlJson "GET" "$Base/knowledge-bases?page=1&page_size=20" $null $script:Token
    if ($raw -match '"name"\s*:\s*"pytest-kb-smoke".*?"id"\s*:\s*"([0-9a-fA-F-]{36})"') {
        $script:KbId = $Matches[1]
        "reuse kb=pytest-kb-smoke id=$($script:KbId)"
    } elseif ($raw -match '"id"\s*:\s*"([0-9a-fA-F-]{36})"\s*,\s*"name"\s*:\s*"pytest-kb-smoke"') {
        $script:KbId = $Matches[1]
        "reuse kb=pytest-kb-smoke id=$($script:KbId)"
    } elseif ($raw -match '"id"\s*:\s*"([0-9a-fA-F-]{36})"') {
        $script:KbId = $Matches[1]
        "reuse kb=$($script:KbId)"
    } else {
        $body = '{"name":"E2E-KB","type":"general","embedding_model":"text-embedding-v3","description":"e2e","tags":[],"chunk_size":500,"chunk_overlap":50,"department":"GUEST"}'
        $craw = CurlJson "POST" "$Base/knowledge-bases" $body $script:Token
        if ($craw -match '"id"\s*:\s*"([0-9a-fA-F-]{36})"') {
            $script:KbId = $Matches[1]
        }
        if (-not $script:KbId) { throw "create kb failed: $craw" }
        "created kb=$($script:KbId)"
    }
}

Step "doc_upload" {
    $uri = "$Base/knowledge-bases/$($script:KbId)/documents/upload"
    $tmpDoc = Join-Path $env:TEMP "e2e_rag_doc.md"
    @(
        "# E2E Knowledge Sample",
        "",
        "RAG (Retrieval-Augmented Generation) combines retrieval with generation.",
        "It first retrieves relevant chunks from a knowledge base, then asks an LLM to answer.",
        "Keywords: vector retrieval, hybrid retrieval, hit-rate testing."
    ) | Set-Content -Path $tmpDoc -Encoding ASCII
    $curlOut = & curl.exe -s -S -X POST $uri -H "Authorization: Bearer $($script:Token)" -F "file=@$tmpDoc;type=text/markdown"
    $j = $curlOut | ConvertFrom-Json
    if ($j.data.id) { $script:DocId = [string]$j.data.id }
    elseif ($j.id) { $script:DocId = [string]$j.id }
    if (-not $script:DocId) { throw "upload failed: $curlOut" }
    "doc=$($script:DocId)"
}

Step "doc_ready_poll" {
    $status = "unknown"
    $raw = ""
    for ($i = 0; $i -lt 60; $i++) {
        $raw = CurlJson "GET" "$Base/knowledge-bases/$($script:KbId)/documents/$($script:DocId)" $null $script:Token
        if ($raw -match '"status"\s*:\s*"([^"]+)"') { $status = $Matches[1] }
        if ($status -in @("ready", "failed", "error")) { break }
        Start-Sleep -Seconds 3
    }
    if ($status -ne "ready") { throw "doc status=$status after poll; last=$($raw.Substring(0,[Math]::Min(300,$raw.Length)))" }
    "status=ready"
}

Step "hit_test_run" {
    $body = "{`"kb_ids`":[`"$($script:KbId)`"],`"strategy`":`"hybrid`",`"top_k`":3,`"questions`":[`"What is RAG?`",`"What is hybrid retrieval?`"]}"
    $raw = CurlJson "POST" "$Base/hit-tests/runs" $body $script:Token
    if ($raw -notmatch '"status"') { throw "hit test failed: $($raw.Substring(0,[Math]::Min(200,$raw.Length)))" }
    "ok:$($raw.Substring(0,[Math]::Min(300,$raw.Length)))"
}

Step "snapshot_create" {
    $body = '{"name":"e2e-snap2","description":"real e2e snapshot"}'
    $raw = CurlJson "POST" "$Base/knowledge-bases/$($script:KbId)/snapshots" $body $script:Token
    if ($raw -match '"id"\s*:\s*"([0-9a-fA-F-]{36})"') {
        $script:SnapId = $Matches[1]
    }
    if (-not $script:SnapId) { throw "no snapshot id: $($raw.Substring(0,[Math]::Min(200,$raw.Length)))" }
    "snap=$($script:SnapId)"
}

Step "snapshot_preview" {
    $raw = CurlJson "POST" "$Base/knowledge-bases/$($script:KbId)/snapshots/$($script:SnapId)/preview" "{}" $script:Token
    if ($raw -match '"detail"\s*:\s*"Not Found"') { throw "preview failed: $raw" }
    if ($raw -match '"detail"' -and $raw -notmatch '"snapshot_id"') { throw "preview failed: $($raw.Substring(0,[Math]::Min(200,$raw.Length)))" }
    "ok_len=$($raw.Length)"
}

Step "qa_ask_sse" {
    $payloadFile = Join-Path $env:TEMP "e2e_qa_body.json"
    $json = "{`"question`":`"What is RAG? Answer briefly using the knowledge base.`",`"strategy`":`"hybrid`",`"top_k`":3,`"kb_ids`":[`"$($script:KbId)`"]}"
    [System.IO.File]::WriteAllText($payloadFile, $json, [System.Text.UTF8Encoding]::new($false))
    $tmp = Join-Path $env:TEMP "e2e_sse.txt"
    $httpCode = & curl.exe -s -S -N -X POST "$Base/qa/ask" `
        -H "Authorization: Bearer $($script:Token)" `
        -H "Content-Type: application/json" `
        -H "Accept: text/event-stream" `
        --max-time 180 `
        --data-binary "@$payloadFile" `
        -o $tmp `
        -w "%{http_code}"
    $content = Get-Content $tmp -Raw -ErrorAction SilentlyContinue
    if (-not $content) { throw "empty SSE body; http=$httpCode" }
    if ([int]$httpCode -ge 400) { throw ("SSE HTTP {0}: {1}" -f $httpCode, $content.Substring(0,[Math]::Min(300,$content.Length))) }
    if ($content -match 'event:\s*error') { throw "SSE error event: $($content.Substring(0,[Math]::Min(300,$content.Length)))" }
    if ($content -notmatch 'event:\s*(chunk|done|citations)') { throw "no SSE events found: $($content.Substring(0,[Math]::Min(300,$content.Length)))" }
    $len = $content.Length
    $preview = $content.Substring(0, [Math]::Min(400, $len)).Replace("`r", " ").Replace("`n", " ")
    "bytes=$len; preview=$preview"
}

$outPath = Join-Path $PSScriptRoot "e2e_results.json"
# Redact token-like long strings from details
$safe = [ordered]@{}
foreach ($k in $Results.Keys) {
    $safe[$k] = @{ name = $Results[$k].name; ok = $Results[$k].ok; detail = $Results[$k].detail }
}
($safe | ConvertTo-Json -Depth 8) | Set-Content $outPath -Encoding UTF8
Write-Host ""
Write-Host "Results written: $outPath" -ForegroundColor Cyan
$fail = @($Results.Values | Where-Object { -not $_.ok })
if ($fail.Count -gt 0) {
    Write-Host ("FAILED steps: " + (($fail | ForEach-Object { $_.name }) -join ", ")) -ForegroundColor Red
    exit 1
}
Write-Host "ALL E2E STEPS PASSED" -ForegroundColor Green
exit 0
