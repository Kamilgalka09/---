param(
    [string]$OutputDir = "dist",
    [string]$Version = "1.0"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$ArchiveName = "radar-bot-hosting_$Version.zip"
$ArchivePath = Join-Path $ProjectRoot $OutputDir $ArchiveName

Write-Host "=== Радар БПЛА - упаковка для хостинга ===" -ForegroundColor Cyan
Write-Host ""

# Создаём директорию вывода
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
    Write-Host "[+] Создана директория: $OutputDir" -ForegroundColor Green
}

# Файлы, которые должны войти в архив
$IncludedFiles = @(
    "bot.py",
    "config.py",
    "fetch_tg.py",
    "maprender.py",
    "parse.py",
    "regions.py",
    "report.py",
    "state.py",
    "tg_api.py",
    "amvera.yaml",
    "requirements.txt",
    "README.md",
    ".env.example",
    "data/lexicon.json",
    "data/regions.geojson",
    "assets/fonts/NotoSans-Bold.ttf",
    "assets/fonts/NotoSans-Regular.ttf"
)

# Проверяем наличие всех файлов
$Missing = @()
foreach ($f in $IncludedFiles) {
    $path = Join-Path $ProjectRoot $f
    if (Test-Path $path) {
        Write-Host "[+] $f" -ForegroundColor Green
    } else {
        Write-Host "[-] НЕ НАЙДЕН: $f" -ForegroundColor Red
        $Missing += $f
    }
}

if ($Missing.Count -gt 0) {
    Write-Host ""
    Write-Host "[-] Пропущены файлы: $($Missing -join ', ')" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Удаляем старый архив
if (Test-Path $ArchivePath) {
    Remove-Item $ArchivePath -Force
    Write-Host "[x] Удалён старый архив" -ForegroundColor Yellow
}

# Создаём временную директорию для сборки
$TempDir = Join-Path $env:TEMP "radar-bot-build-$([System.Guid]::NewGuid().ToString().Substring(0,8))"
New-Item -ItemType Directory -Path $TempDir | Out-Null

try {
    # Копируем файлы в временную директорию
    foreach ($f in $IncludedFiles) {
        $src = Join-Path $ProjectRoot $f
        $dst = Join-Path $TempDir $f
        $dstDir = Split-Path $dst -Parent
        if (-not (Test-Path $dstDir)) {
            New-Item -ItemType Directory -Path $dstDir -Force | Out-Null
        }
        Copy-Item $src $dst -Force
    }

    # Создаём zip-архив
    $oldPwd = Get-Location
    Set-Location $TempDir
    Compress-Archive -Path $IncludedFiles -DestinationPath $ArchivePath -Force
    Set-Location $oldPwd

    $size = (Get-Item $ArchivePath).Length / 1MB
    Write-Host ""
    Write-Host "[+] Архив создан: $ArchivePath" -ForegroundColor Green
    Write-Host "    Размер: $([math]::Round($size, 2)) МБ" -ForegroundColor Green
    Write-Host ""
    Write-Host "=== Готово! ===" -ForegroundColor Cyan
    Write-Host "Загрузите $ArchiveName в Amvera через панель проектов." -ForegroundColor Yellow
}
finally {
    # Очищаем временную директорию
    if (Test-Path $TempDir) {
        Remove-Item $TempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
