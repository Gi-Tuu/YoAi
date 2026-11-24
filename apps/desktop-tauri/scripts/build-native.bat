@echo off
REM Build Tauri Rust with MSVC environment. Run via: cmd /c build-native.bat
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 (
  echo [build-native] vcvars64 failed
  exit /b 1
)
where link.exe
echo [build-native] MSVC env ready, building...
call "%USERPROFILE%\.cargo\bin\cargo.exe" build --manifest-path "%~dp0..\src-tauri\Cargo.toml" --release
echo [build-native] cargo exit=%errorlevel%
exit /b %errorlevel%
