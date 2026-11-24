# Tauri 构建环境准备（Windows PowerShell）
# 作用：把 MSVC 的 link.exe 放到 PATH 最前，压过 Git Bash 的 GNU link.exe，
#       并注入 VC 的 include/lib 环境变量（vcvars64）。
#
# 用法（在 PowerShell 里）：
#   .\scripts\build-env.ps1        # 只设置当前会话环境
#   .\scripts\build-env.ps1 -Build # 设置环境并直接构建

param([switch]$Build)

$ErrorActionPreference = "Stop"

# 1. 找 vswhere
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) { throw "vswhere not found - install VS Build Tools first" }

# 2. 找最新 VS 安装（含 VC 工具集）
$vsPath = & $vswhere -latest -products * -property installationPath | Select-Object -First 1
if (-not $vsPath) {
  # vswhere 还没注册（安装器仍在收尾）：直接探测常见 BuildTools 路径
  foreach ($candidate in @(
      "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\BuildTools",
      "$env:ProgramFiles\Microsoft Visual Studio\2022\BuildTools")) {
    if (Test-Path (Join-Path $candidate "VC\Auxiliary\Build\vcvars64.bat")) {
      $vsPath = $candidate; break
    }
  }
}
if (-not $vsPath) { throw "VS install not found - install VS Build Tools first" }

# 3. 找 vcvars64.bat
$vcvars = Join-Path $vsPath "VC\Auxiliary\Build\vcvars64.bat"
if (-not (Test-Path $vcvars)) { throw "vcvars64.bat not found: $vcvars" }

# 4. 用 cmd 执行 vcvars64 并把环境导入当前 PowerShell
$envLines = cmd /c "`"$vcvars`" `"&&`" set"
foreach ($line in $envLines) {
  if ($line -match "^([^=]+)=(.*)$") {
    $name = $Matches[1]
    $value = $Matches[2]
    if ($name -eq "PATH" -or $name -eq "INCLUDE" -or $name -eq "LIB" -or $name -eq "LIBPATH") {
      [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
  }
}

# 5. 验证：link.exe 必须是 MSVC 版（不是 Git Bash 的 GNU link）
$linkPath = (Get-Command link.exe -ErrorAction SilentlyContinue).Source
if (-not $linkPath -or $linkPath -notmatch "Visual Studio") {
  throw "link.exe is not MSVC (current: $linkPath). Check PATH vs Git Bash."
}
Write-Host "[build-env] MSVC linker ready: $linkPath"

if ($Build) {
  $root = Split-Path -Parent $PSScriptRoot
  Push-Location $root
  try {
    npm run tauri build -- --no-bundle
    if ($LASTEXITCODE -ne 0) { throw "Tauri build failed (exit $LASTEXITCODE)" }
    Write-Host "[build-env] build success"
  } finally { Pop-Location }
}
