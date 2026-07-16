# 智能问答模块联调验证脚本（Windows PowerShell）
# 用法：.\scripts\verify_qa_stack.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "=== [1/5] 启动核心服务 ===" -ForegroundColor Cyan
docker compose up -d postgres redis chroma api web nginx
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "=== [2/5] 等待 API 健康 ===" -ForegroundColor Cyan
$maxRetry = 30
$ok = $false
for ($i = 1; $i -le $maxRetry; $i++) {
    try {
        $resp = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/monitor/health" -TimeoutSec 5
        if ($resp.status -eq "ok" -or $resp.status -eq "degraded") {
            Write-Host "健康检查通过: $($resp | ConvertTo-Json -Compress)"
            $ok = $true
            break
        }
    } catch {
        Write-Host "等待 API 就绪 ($i/$maxRetry)..."
        Start-Sleep -Seconds 5
    }
}
if (-not $ok) {
    Write-Host "API 健康检查失败，查看日志: docker compose logs api" -ForegroundColor Red
    exit 1
}

Write-Host "=== [3/5] 执行 Alembic 迁移（容器内） ===" -ForegroundColor Cyan
docker compose exec -T api alembic -c /app/alembic.ini upgrade head

Write-Host "=== [4/5] 访客 SSE 问答冒烟 ===" -ForegroundColor Cyan
$body = @{ question = "什么是 RAG？"; strategy = "hybrid"; top_k = 3 } | ConvertTo-Json
$headers = @{
    "Content-Type" = "application/json"
    "Accept"       = "text/event-stream"
    "X-Guest-Id"   = [guid]::NewGuid().ToString()
}
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/qa/ask" `
        -Method POST -Body $body -Headers $headers -TimeoutSec 120
    Write-Host "SSE 状态码: $($response.StatusCode)"
    $preview = $response.Content.Substring(0, [Math]::Min(500, $response.Content.Length))
    Write-Host "SSE 预览:`n$preview"
} catch {
    Write-Host "SSE 请求异常（可能无公开知识库或 LLM 未配置）: $_" -ForegroundColor Yellow
}

Write-Host "=== [5/5] 统一入口探活 ===" -ForegroundColor Cyan
try {
    $nginx = Invoke-RestMethod -Uri "http://localhost:8080/api/v1/monitor/health" -TimeoutSec 10
    Write-Host "Nginx 代理健康: $($nginx | ConvertTo-Json -Compress)"
} catch {
    Write-Host "Nginx 入口未就绪: $_" -ForegroundColor Yellow
}

Write-Host "`n联调完成。前端访问: http://localhost:8080/" -ForegroundColor Green
